"""Own the backend's remote command output while preserving manual intent.

Other publishers cannot communicate their origin in the existing command contract;
managed manual commands therefore enter through the existing REST endpoint.
"""

import asyncio
import logging
import time
from typing import Awaitable, Callable

from ..models.schemas import Command

logger = logging.getLogger("ENVIRONMENT")


class AlarmOrchestrator:
    def __init__(self, publish: Callable[[Command], bool], *, enabled: bool = False,
                 saved: dict | None = None,
                 persist: Callable[[dict], Awaitable[None]] | None = None,
                 require_manual: bool = False,
                 on_published: Callable[[Command], None] | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.enabled = enabled
        self._publish = publish
        self._on_published = on_published
        self._persist = persist
        self._sleep = sleep
        self._clock = clock
        self._lock = asyncio.Lock()
        self._manual = Command.model_validate(saved["manual"]) if saved else Command(buzzer=False, led="green")
        self._manual_known = not require_manual or saved is not None
        self._cleanup_needed = bool(saved and saved.get("cleanup_pending"))
        self._ai_buzzer = False
        self._ai_led = False
        self._connected = False
        self._closing = False
        self._last_sent: Command | None = None
        self._pulse: asyncio.Task | None = None
        self._pulse_beeps = 1
        self._retry: asyncio.Task | None = None
        self._starts: set[asyncio.Task] = set()
        self._generation = 0

    @property
    def generation(self) -> int:
        """A STOP invalidates alarm decisions awaiting their DB commit too."""
        return self._generation

    def _desired(self) -> Command:
        return Command(buzzer=self._manual.buzzer or self._ai_buzzer,
                       led="red" if self._manual.led == "red" or self._ai_led else "green")

    def _state(self) -> dict:
        return {"manual": self._manual.model_dump(mode="json"), "cleanup_pending": self._cleanup_needed}

    async def _save(self) -> bool:
        if self._persist is None:
            return True
        try:
            await asyncio.wait_for(self._persist(self._state()), timeout=6)
            return True
        except Exception:
            # Avoid credential-bearing SQL details in user-visible logs.
            logger.error("Could not persist remote alarm ownership")
            return False

    async def _send(self, *, force: bool = False) -> bool:
        command = self._desired()
        if not force and command == self._last_sent:
            return True
        try:
            publication = asyncio.create_task(asyncio.to_thread(self._publish, command))
            try:
                success = await asyncio.shield(publication)
            except asyncio.CancelledError:
                # A thread cannot be cancelled. Keep ownership locked until it
                # finishes so STOP/cleanup cannot be overtaken by an earlier ON.
                success = await publication
                if success:
                    self._last_sent = command
                raise
        except Exception:
            logger.error("Remote alarm command publication failed")
            success = False
        if success:
            self._last_sent = command
            if self._on_published is not None:
                self._on_published(command)
        return success

    def _cancel_pulse(self) -> None:
        if self._pulse is not None:
            self._pulse.cancel()
            self._pulse = None

    def _ensure_retry(self) -> None:
        if self._closing or not self._connected or not self._cleanup_needed:
            return
        if self._retry is None or self._retry.done():
            self._retry = asyncio.create_task(self._retry_cleanup())

    async def _cleanup(self) -> bool:
        if not self._connected:
            return False
        if await self._send(force=True):
            self._cleanup_needed = self._ai_buzzer or self._ai_led
            await self._save()
            return True
        self._cleanup_needed = True
        await self._save()
        return False

    async def _retry_cleanup(self) -> None:
        try:
            while not self._closing:
                await self._sleep(1)
                async with self._lock:
                    if not self._connected or not self._cleanup_needed:
                        return
                    # A retry only removes expired AI output, never replays ON.
                    if await self._cleanup():
                        return
        except asyncio.CancelledError:
            pass

    async def set_connected(self, connected: bool) -> None:
        async with self._lock:
            self._connected = connected
            if not connected:
                self._generation += 1
                owned = self._ai_buzzer or self._ai_led
                self._cancel_pulse()
                self._ai_buzzer = self._ai_led = False
                if self._retry is not None:
                    self._retry.cancel()
                if owned:
                    self._cleanup_needed = True
                    await self._save()
            elif self._cleanup_needed:
                # The only automatic startup command is cleanup of a recorded
                # interrupted pulse; cached anomaly results never trigger ON.
                if not await self._cleanup():
                    self._ensure_retry()

    async def manual(self, command: Command) -> bool:
        if not command.buzzer and command.led == "green":
            # Invalidate scheduled ON immediately, before awaiting its lock.
            self._generation += 1
        # An HTTP disconnect must not leave a published manual ON unrecorded.
        operation = asyncio.create_task(self._manual_transition(command))
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            await operation
            raise

    async def _manual_transition(self, command: Command) -> bool:
        async with self._lock:
            previous = self._manual
            previous_cleanup = self._cleanup_needed
            stop = not command.buzzer and command.led == "green"
            if stop:
                self._cancel_pulse()
                self._ai_buzzer = self._ai_led = False
            self._manual = command
            # Write ownership ahead of physical output. If publication or the
            # process is interrupted, restart cleanup preserves this intent.
            self._cleanup_needed = True
            if not await self._save():
                if stop:
                    # STOP can still help physically, but REST returns 503
                    # because its durable ownership could not be guaranteed.
                    await self._send(force=True)
                    self._ensure_retry()
                else:
                    self._manual = previous
                    self._cleanup_needed = previous_cleanup
                return False
            success = await self._send(force=True)
            if success:
                self._manual_known = True
                self._cleanup_needed = self._ai_buzzer or self._ai_led
                await self._save()
            elif stop:
                # STOP remains the desired output even when the broker fails.
                self._cleanup_needed = True
                await self._save()
                self._ensure_retry()
            else:
                self._manual = previous
                self._cleanup_needed = previous_cleanup
                await self._save()
            return success

    def critical(self, eligible: Callable[[], bool] | None = None, *, generation: int | None = None,
                 beeps: int = 1) -> None:
        if beeps not in (1, 2):
            raise ValueError("Alarm supports one or two beeps")
        if not self.enabled or self._closing:
            return
        if not self._manual_known:
            logger.warning("Automatic alarm suppressed: establish remote ownership with a manual REST command")
            return
        task = asyncio.create_task(self._start_pulse(self._generation if generation is None else generation, eligible, beeps))
        self._starts.add(task)
        task.add_done_callback(self._starts.discard)

    async def _start_pulse(self, generation: int, eligible: Callable[[], bool] | None, beeps: int) -> None:
        async with self._lock:
            if (self._closing or not self._connected or generation != self._generation
                    or (eligible is not None and not eligible())):
                return
            if self._pulse is not None and not self._pulse.done() and beeps < self._pulse_beeps:
                return  # A camera notification must not interrupt the critical double beep.
            self._cancel_pulse()
            self._pulse_beeps = beeps
            self._ai_buzzer = self._ai_led = True
            self._cleanup_needed = True
            # Record ownership before ON so a crash can safely restore manual
            # output on reconnect without replaying a historical alarm.
            if not await self._save():
                self._ai_buzzer = self._ai_led = False
                return
            if generation != self._generation or (eligible is not None and not eligible()):
                self._ai_buzzer = self._ai_led = self._cleanup_needed = False
                await self._save()
                return
            if not await self._send():
                self._ai_buzzer = self._ai_led = False
                if not await self._cleanup():
                    self._ensure_retry()
                return
            started = self._clock()
            self._pulse = asyncio.create_task(self._finish_pulse(started, beeps))

    async def _finish_pulse(self, started: float, beeps: int) -> None:
        try:
            transitions = ((0.5, False), (0.8, True), (1.3, False)) if beeps == 2 else ((1, False),)
            for deadline, active in transitions:
                await self._sleep(max(0, started + deadline - self._clock()))
                async with self._lock:
                    self._ai_buzzer = active
                    if self._connected and not await self._send():
                        self._ai_buzzer = False
                        self._ensure_retry()
                        break  # Never retry a failed second ON as another beep.
            await self._sleep(max(0, started + 5 - self._clock()))
            async with self._lock:
                self._ai_led = False
                if self._connected and await self._send():
                    self._cleanup_needed = False
                    await self._save()
                else:
                    self._cleanup_needed = True
                    await self._save()
                    self._ensure_retry()
        except asyncio.CancelledError:
            pass

    async def close(self) -> None:
        self._closing = True
        for task in self._starts:
            task.cancel()
        pulse, retry = self._pulse, self._retry
        self._cancel_pulse()
        if retry is not None:
            retry.cancel()
        await asyncio.gather(*self._starts, *(task for task in (pulse, retry) if task is not None),
                             return_exceptions=True)
        async with self._lock:
            self._ai_buzzer = self._ai_led = False
            if self._cleanup_needed:
                await self._cleanup()
