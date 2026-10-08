import json
import signal
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from PIL import Image
import sentinel_dashboard as dashboard


class DisplayTests(unittest.TestCase):
    def test_rgb565_primary_colors(self):
        for color, expected in [('red', b'\x00\xf8'), ('lime', b'\xe0\x07'), ('blue', b'\x1f\x00')]:
            pixels = dashboard.rgb565(Image.new('RGB', dashboard.SIZE, color))
            self.assertEqual(pixels[:2], expected)
            self.assertEqual(len(pixels), 320 * 240 * 2)

    def test_each_websocket_update_redraws_screen(self):
        frames, handlers = [], {}
        class Screen:
            def __init__(self, _): pass
            def write(self, image): frames.append(image.tobytes())
            def close(self): pass
        class Socket:
            count = 0
            def recv(self, timeout):
                self.count += 1
                if self.count == 3:
                    handlers[signal.SIGTERM]()
                return json.dumps({'type': 'state', 'data': {
                    'telemetry': {'temperature': 20 + self.count, 'humidity': 50,
                                  'gas': 12, 'motion': False, 'ts': datetime.now(timezone.utc).isoformat()},
                    'system': {'mqtt_connected': True}, 'device': {'online': True}, 'alerts': []}})
            def close(self): pass
        with patch('sys.argv', ['dashboard']), patch.object(dashboard, 'Framebuffer', Screen), \
             patch.object(dashboard.signal, 'signal', side_effect=lambda sig, fn: handlers.update({sig: fn})), \
             patch('websockets.sync.client.connect', return_value=Socket()):
            dashboard.main()
        self.assertEqual(len(frames), 3)
        self.assertEqual(len(set(frames)), 3)

    def test_framebuffer_write_preserves_stride_padding(self):
        screen = dashboard.Framebuffer.__new__(dashboard.Framebuffer)
        screen.stride = 648
        screen.offset = 16
        screen.memory = bytearray(b'\xaa' * (16 + 648 * 240))
        screen.write(Image.new('RGB', dashboard.SIZE, 'red'))
        for row in (0, 1, 239):
            start = 16 + row * 648
            self.assertEqual(screen.memory[start:start + 640], b'\x00\xf8' * 320)
            self.assertEqual(screen.memory[start + 640:start + 648], b'\xaa' * 8)


if __name__ == '__main__':
    unittest.main()
