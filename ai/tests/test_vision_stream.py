import json
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from src.vision.stream import VisionStream


class VisionStreamTests(unittest.TestCase):
    def setUp(self):
        self.stream = VisionStream("127.0.0.1", 0)
        self.stream.start()
        self.base_url = f"http://127.0.0.1:{self.stream.port}"

    def tearDown(self):
        self.stream.stop()

    def test_metrics_endpoint_reports_latest_values_and_allows_dashboard_origin(self):
        metrics = {
            "status": "active",
            "model": "yolov8n.pt",
            "fps": 18.0,
            "latency_ms": 72.0,
            "person_detected": True,
            "confidence": 0.94,
            "ts": "2026-10-06T15:00:00Z",
        }
        self.stream.publish(b"\xff\xd8\xff\xd9", metrics)

        with urlopen(f"{self.base_url}/metrics", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Access-Control-Allow-Origin"], "http://localhost:5173")
            self.assertEqual(json.load(response), metrics)

    def test_stream_endpoint_serves_annotated_jpeg_frames(self):
        self.stream.publish(b"\xff\xd8test-jpeg\xff\xd9", {"status": "active"})

        with urlopen(f"{self.base_url}/stream.mjpg", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("multipart/x-mixed-replace", response.headers["Content-Type"])
            self.assertEqual(response.read(9), b"--frame\r\n")
            content_type = b"Content-Type: image/jpeg\r\n"
            self.assertEqual(response.read(len(content_type)), content_type)

    def test_unknown_endpoint_returns_404(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(f"{self.base_url}/unknown", timeout=2)
        self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
