"""Serve the annotated camera preview and live inference metrics over HTTP."""

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Condition, Thread

logger = logging.getLogger("VISION")


class VisionStream:
    def __init__(self, host: str, port: int, allowed_origin: str = "http://localhost:5173"):
        self._condition = Condition()
        self._jpeg: bytes | None = None
        self._sequence = 0
        self._stopping = False
        self._metrics: dict[str, str | float | bool] = {"status": "starting"}
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None
        stream = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def do_GET(self) -> None:
                if self.path == "/metrics":
                    body = json.dumps(stream.metrics()).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Access-Control-Allow-Origin", stream.allowed_origin)
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if self.path != "/stream.mjpg":
                    self.send_error(404)
                    return

                if not stream.wait_for_frame():
                    self.send_error(503, "Camera frame not available")
                    return

                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                sequence = -1
                try:
                    while True:
                        frame = stream.next_frame(sequence)
                        if frame is None:
                            if stream.stopping:
                                return
                            continue
                        sequence, jpeg = frame
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                        self.wfile.write(jpeg + b"\r\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return

            def log_message(self, format_string: str, *args: object) -> None:
                logger.debug("Vision stream: " + format_string, *args)

        self._handler = Handler
        self.host = host
        self.port = port
        self.allowed_origin = allowed_origin

    def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("Vision stream is already running")
        self._stopping = False
        self._server = ThreadingHTTPServer((self.host, self.port), self._handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = Thread(target=self._server.serve_forever,
                              name="vision-stream", daemon=True)
        self._thread.start()
        logger.info("Vision stream listening on http://%s:%s", self.host, self.port)

    def publish(self, jpeg: bytes, metrics: dict[str, str | float | bool]) -> None:
        if not jpeg:
            raise ValueError("Cannot publish an empty camera frame")
        with self._condition:
            self._jpeg = jpeg
            self._metrics = metrics.copy()
            self._sequence += 1
            self._condition.notify_all()

    def metrics(self) -> dict[str, str | float | bool]:
        with self._condition:
            return self._metrics.copy()

    @property
    def stopping(self) -> bool:
        with self._condition:
            return self._stopping

    def wait_for_frame(self, timeout: float = 10.0) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: self._jpeg is not None, timeout)

    def next_frame(self, previous_sequence: int) -> tuple[int, bytes] | None:
        with self._condition:
            self._condition.wait_for(
                lambda: self._sequence != previous_sequence or self._server is None,
                timeout=2.0,
            )
            if self._sequence == previous_sequence or self._jpeg is None:
                return None
            return self._sequence, self._jpeg

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        if server is None:
            return
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        self._server = None
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError("Vision stream server did not stop")
        self._thread = None
        logger.info("Vision stream stopped")
