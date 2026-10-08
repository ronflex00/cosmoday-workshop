"""Physical deadlines advance on an injected clock, without real 1/5s sleeps."""

import asyncio
import unittest
from threading import Event

from app.models.schemas import Command
from app.services.alarm import AlarmOrchestrator


class ControlledClock:
    def __init__(self):
        self.now = 0.0
        self.waiters = []

    async def sleep(self, delay):
        if delay <= 0:
            await asyncio.sleep(0)
            return
        future = asyncio.get_running_loop().create_future()
        self.waiters.append((self.now + delay, future))
        await future

    def advance(self, seconds):
        self.now = round(self.now + seconds, 6)
        for deadline, future in self.waiters:
            if deadline <= self.now and not future.done():
                future.set_result(None)
        self.waiters = [(deadline, future) for deadline, future in self.waiters if not future.done()]


async def eventually(predicate):
    deadline = asyncio.get_running_loop().time() + 2
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("Async alarm action did not finish")
        await asyncio.sleep(0.001)


class AlarmTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = ControlledClock()
        self.commands = []
        self.saved = []
        self.failures = set()

        def publish(command):
            self.commands.append((self.clock.now, command.model_dump(mode="json")))
            return len(self.commands) not in self.failures

        async def persist(state):
            self.saved.append(state)

        self.alarm = AlarmOrchestrator(publish, enabled=True, sleep=self.clock.sleep,
                                       clock=lambda: self.clock.now, persist=persist)
        await self.alarm.set_connected(True)

    async def asyncTearDown(self):
        await self.alarm.close()

    async def start_pulse(self):
        self.alarm.critical()
        await eventually(lambda: len(self.commands) >= 1 and len(self.clock.waiters) >= 1)

    async def test_buzzer_one_second_and_red_led_five_seconds(self):
        await self.start_pulse()
        self.assertEqual(self.commands, [(0, {"buzzer": True, "led": "red"})])
        self.clock.advance(0.999)
        await asyncio.sleep(0)
        self.assertEqual(len(self.commands), 1)
        self.clock.advance(0.001)
        await eventually(lambda: len(self.commands) == 2 and len(self.clock.waiters) >= 1)
        self.assertEqual(self.commands[1], (1, {"buzzer": False, "led": "red"}))
        self.clock.advance(3.999)
        await asyncio.sleep(0)
        self.assertEqual(len(self.commands), 2)
        self.clock.advance(0.001)
        await eventually(lambda: len(self.commands) == 3 and not self.alarm._cleanup_needed)
        self.assertEqual(self.commands[2], (5, {"buzzer": False, "led": "green"}))

    async def test_manual_alarm_during_pulse_is_never_interrupted_by_timers(self):
        await self.start_pulse()
        self.clock.advance(0.5)
        self.assertTrue(await self.alarm.manual(Command(buzzer=True, led="red")))
        self.clock.advance(0.5)
        await eventually(lambda: len(self.clock.waiters) >= 1)
        self.clock.advance(4)
        await eventually(lambda: not self.alarm._cleanup_needed)
        self.assertTrue(all(command["buzzer"] and command["led"] == "red" for _, command in self.commands))
        await self.alarm.manual(Command(buzzer=False, led="green"))
        self.assertEqual(self.commands[-1][1], {"buzzer": False, "led": "green"})

    async def test_manual_red_led_is_preserved_after_ai_red_expires(self):
        await self.start_pulse()
        await self.alarm.manual(Command(buzzer=False, led="red"))
        self.clock.advance(1)
        await eventually(lambda: len(self.commands) == 3 and len(self.clock.waiters) >= 1)
        self.clock.advance(4)
        await eventually(lambda: not self.alarm._cleanup_needed)
        self.assertEqual(len(self.commands), 3)
        self.assertEqual(self.commands[-1][1], {"buzzer": False, "led": "red"})

    async def test_manual_stop_cancels_active_and_queued_ai_pulses(self):
        await self.start_pulse()
        await self.alarm.manual(Command(buzzer=False, led="green"))
        self.clock.advance(10)
        await asyncio.sleep(0)
        self.assertEqual(len(self.commands), 2)
        self.alarm.critical()
        await self.alarm.manual(Command(buzzer=False, led="green"))
        await eventually(lambda: not self.alarm._starts)
        self.assertEqual(len(self.commands), 3)
        self.assertEqual(self.commands[-1][1], {"buzzer": False, "led": "green"})

    async def test_disabled_flag_produces_no_startup_timer_or_shutdown_commands(self):
        self.alarm.enabled = False
        self.alarm.critical()
        self.clock.advance(10)
        await self.alarm.close()
        self.assertEqual(self.commands, [])
        self.assertTrue(await self.alarm.manual(Command(buzzer=True, led="red")))
        self.assertEqual(len(self.commands), 1)

    async def test_disconnect_then_reconnect_cleans_up_without_replaying_on(self):
        await self.start_pulse()
        self.clock.advance(0.5)
        await self.alarm.set_connected(False)
        self.clock.advance(10)
        await asyncio.sleep(0)
        self.assertEqual(len(self.commands), 1)
        self.assertTrue(self.saved[-1]["cleanup_pending"])
        await self.alarm.set_connected(True)
        self.assertEqual(self.commands[-1][1], {"buzzer": False, "led": "green"})
        self.assertFalse(self.saved[-1]["cleanup_pending"])
        self.assertEqual(len(self.commands), 2)

    async def test_cleanup_failure_retries_current_desired_output(self):
        self.failures.add(2)
        await self.start_pulse()
        self.clock.advance(1)
        await eventually(lambda: len(self.commands) == 2 and len(self.clock.waiters) >= 2)
        await self.alarm.manual(Command(buzzer=True, led="red"))
        self.clock.advance(1)
        await eventually(lambda: len(self.commands) == 4)
        self.assertEqual(self.commands[-1][1], {"buzzer": True, "led": "red"})
        self.clock.advance(3)
        await eventually(lambda: not self.alarm._cleanup_needed)
        self.assertEqual(self.commands[-1][1], {"buzzer": True, "led": "red"})

    async def test_failed_activation_is_not_retried_as_an_on_pulse(self):
        self.failures.update({1, 2})
        self.alarm.critical()
        await eventually(lambda: len(self.commands) == 2 and len(self.clock.waiters) >= 1)
        self.clock.advance(1)
        await eventually(lambda: len(self.commands) == 3)
        self.assertEqual([command["buzzer"] for _, command in self.commands], [True, False, False])

    async def test_restored_manual_state_is_quiet_and_interrupted_ai_cleanup_preserves_it(self):
        await self.alarm.close()
        def publish(command):
            self.commands.append((self.clock.now, command.model_dump(mode="json")))
            return True
        saved = {"manual": {"buzzer": True, "led": "red"}, "cleanup_pending": False}
        self.alarm = AlarmOrchestrator(publish, enabled=True, saved=saved,
                                       sleep=self.clock.sleep, clock=lambda: self.clock.now)
        await self.alarm.set_connected(True)
        self.assertEqual(self.commands, [])
        await self.start_pulse()
        await self.alarm.close()
        self.assertTrue(self.commands[-1][1]["buzzer"])
        saved["cleanup_pending"] = True
        self.alarm = AlarmOrchestrator(publish, enabled=False, saved=saved)
        await self.alarm.set_connected(True)
        self.assertEqual(self.commands[-1][1], {"buzzer": True, "led": "red"})

    async def test_shutdown_removes_ai_output_but_preserves_manual_alarm(self):
        await self.start_pulse()
        await self.alarm.close()
        self.assertEqual(self.commands[-1][1], {"buzzer": False, "led": "green"})
        self.assertFalse(self.saved[-1]["cleanup_pending"])

    async def test_unknown_legacy_manual_state_requires_explicit_rest_ownership(self):
        self.alarm._manual_known = False
        with self.assertLogs("ENVIRONMENT", level="WARNING"):
            self.alarm.critical()
        await asyncio.sleep(0)
        self.assertEqual(self.commands, [])
        await self.alarm.manual(Command(buzzer=False, led="green"))
        self.alarm.critical()
        await eventually(lambda: len(self.commands) == 2)
        self.assertEqual(self.commands[-1][1], {"buzzer": True, "led": "red"})

    async def test_result_that_expires_while_saving_ownership_never_publishes_on(self):
        eligible = True
        async def persist(state):
            nonlocal eligible
            eligible = False
        self.alarm._persist = persist
        self.alarm.critical(lambda: eligible)
        await eventually(lambda: not self.alarm._starts)
        self.assertEqual(self.commands, [])

    async def test_publication_latency_does_not_shorten_buzzer_deadline(self):
        original = self.alarm._publish
        def delayed(command):
            if command.buzzer:
                self.clock.advance(2)
            return original(command)
        self.alarm._publish = delayed
        await self.start_pulse()
        self.assertEqual(self.commands[0][0], 2)
        self.clock.advance(0.999)
        await asyncio.sleep(0)
        self.assertEqual(len(self.commands), 1)
        self.clock.advance(0.001)
        await eventually(lambda: len(self.commands) == 2)
        self.assertEqual(self.commands[-1][0], 3)

    async def test_canceled_manual_request_still_saves_completed_publication(self):
        entered, release = Event(), Event()
        original = self.alarm._publish
        def blocked(command):
            entered.set()
            release.wait(2)
            return original(command)
        self.alarm._publish = blocked
        operation = asyncio.create_task(self.alarm.manual(Command(buzzer=True, led="red")))
        try:
            await eventually(entered.is_set)
            operation.cancel()
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await operation
        self.assertEqual(self.saved[-1]["manual"], {"buzzer": True, "led": "red"})
        self.assertEqual(self.commands[-1][1], self.saved[-1]["manual"])

    async def test_database_failure_cannot_publish_an_unrecorded_manual_activation(self):
        async def unavailable(state):
            raise OSError("offline database")
        self.alarm._persist = unavailable
        with self.assertLogs("ENVIRONMENT", level="ERROR"):
            self.assertFalse(await self.alarm.manual(Command(buzzer=True, led="red")))
        self.assertEqual(self.commands, [])
        self.assertEqual(self.alarm._manual, Command(buzzer=False, led="green"))

    async def test_failed_manual_publication_restores_saved_previous_ownership(self):
        self.failures.add(1)
        self.assertFalse(await self.alarm.manual(Command(buzzer=True, led="red")))
        self.assertEqual(self.saved[0]["manual"], {"buzzer": True, "led": "red"})
        self.assertEqual(self.saved[-1]["manual"], {"buzzer": False, "led": "green"})


if __name__ == "__main__":
    unittest.main()
