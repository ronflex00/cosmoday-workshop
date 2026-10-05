import asyncio
import json
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.websocket import WebSocketManager
from app.config import Settings
from app.main import create_app
from app.models.schemas import TELEMETRY_TOPIC, VISION_TOPIC
from app.mqtt.client import MQTTEvent
from app.services.state import StateService
from test_api import FakeMQTT
from test_schemas import telemetry, vision


def wait_connected(client):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if client.get("/api/v1/state").json()["system"]["mqtt_connected"]:
            return
        time.sleep(0.01)
    raise AssertionError("Fake MQTT connection not processed")


class WebSocketTests(unittest.TestCase):
    def test_initial_state_multiple_clients_and_disconnect(self):
        app = create_app(Settings())
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            initial = client.get("/api/v1/state").json()
            with client.websocket_connect("/ws", headers={"Origin": "http://localhost:5173"}) as first:
                self.assertEqual(first.receive_json(), {"type": "state", "data": initial})
                with client.websocket_connect("/ws") as second:
                    self.assertEqual(second.receive_json()["data"], initial)
                    for detected in (False, True, True):
                        app.state.mqtt.events.put_nowait(MQTTEvent(
                            VISION_TOPIC, json.dumps(vision(person_detected=detected)).encode()))
                        left, right = first.receive_json(), second.receive_json()
                        self.assertEqual(left, right)
                        self.assertEqual(left["data"]["vision"]["person_detected"], detected)
                        intrusion = [a for a in left["data"]["alerts"] if a["type"] == "INTRUSION"]
                        self.assertEqual(len(intrusion), 1 if detected else 0)
                # Invalid messages are skipped; the following telemetry still reaches the survivor.
                app.state.mqtt.events.put_nowait(MQTTEvent(TELEMETRY_TOPIC, b"{invalid"))
                app.state.mqtt.events.put_nowait(MQTTEvent(TELEMETRY_TOPIC, json.dumps(telemetry()).encode()))
                update = first.receive_json()["data"]
                self.assertEqual(update["telemetry"]["temperature"], 24.3)
                with client.websocket_connect("/ws") as reconnected:
                    self.assertEqual(reconnected.receive_json()["data"], update)

    def test_alert_post_broadcasts_updated_history(self):
        app = create_app(Settings())
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            with client.websocket_connect("/ws") as websocket:
                websocket.receive_json()
                response = client.post("/api/v1/alerts", json={
                    "ts": "2026-10-05T14:30:00Z", "type": "system",
                    "severity": "warning", "message": "Manual integration test"})
                self.assertEqual(response.status_code, 201)
                state = websocket.receive_json()["data"]
                self.assertEqual(state["alerts"][0], response.json())
                self.assertEqual(client.get("/api/v1/state").json(), state)

    def test_unconfigured_browser_origin_is_rejected(self):
        app = create_app(Settings())
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            with self.assertRaises(WebSocketDisconnect) as error:
                with client.websocket_connect("/ws", headers={"Origin": "http://untrusted.test"}):
                    pass
            self.assertEqual(error.exception.code, 1008)


class DummySocket:
    def __init__(self, *, broken=False, slow=False):
        self.broken = broken
        self.slow = slow
        self.received = asyncio.Queue()
        self.closed = asyncio.Event()

    async def send_text(self, payload):
        if self.broken:
            raise RuntimeError("Client disconnected")
        if self.slow:
            await asyncio.Event().wait()
        await self.received.put(json.loads(payload))

    async def close(self, code):
        self.closed.set()


class ClientIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def check_isolation(self, faulty):
        manager = WebSocketManager(send_timeout=0.05)
        healthy = DummySocket()
        store = StateService()
        tasks = [asyncio.create_task(manager.send_updates(socket, manager.connect(socket, store.snapshot())))
                 for socket in (faulty, healthy)]
        try:
            await asyncio.wait_for(healthy.received.get(), 1)
            # Pending snapshots are bounded to one per client; the latest must survive a burst.
            for value in range(10):
                store.apply_message(TELEMETRY_TOPIC, json.dumps(telemetry(gas=value)).encode())
                manager.broadcast(store.snapshot())
            update = await asyncio.wait_for(healthy.received.get(), 1)
            self.assertEqual(update["data"]["telemetry"]["gas"], 9)
            await asyncio.wait_for(faulty.closed.wait(), 1)
            store.apply_message(TELEMETRY_TOPIC, json.dumps(telemetry(gas=100)).encode())
            manager.broadcast(store.snapshot())
            update = await asyncio.wait_for(healthy.received.get(), 1)
            self.assertEqual(update["data"]["telemetry"]["gas"], 100)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await manager.close()

    async def test_broken_client_does_not_interrupt_healthy_client(self):
        await self.check_isolation(DummySocket(broken=True))

    async def test_slow_client_does_not_block_healthy_client(self):
        await self.check_isolation(DummySocket(slow=True))


if __name__ == "__main__":
    unittest.main()
