"""Minimal 320x240 PiTFT dashboard; reads the local FastAPI, never MQTT secrets."""

import argparse
import ctypes
from datetime import datetime, timezone
import json
from functools import lru_cache
import math
import mmap
import os
from pathlib import Path
import signal
import struct
import sys
import time
from urllib.request import urlopen

from PIL import Image, ImageDraw, ImageFont

SIZE = (320, 240)
BG = '#0b1017'
TEXT = '#e2e8f0'
MUTED = '#8b99aa'
RED = '#ff5c68'


@lru_cache(maxsize=32)
def font(size):
    for path in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'C:/Windows/Fonts/segoeui.ttf'):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def age(timestamp, now):
    try:
        value = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if value.tzinfo is None:
            return math.inf
        return (now - value).total_seconds()
    except (AttributeError, TypeError, ValueError):
        return math.inf


def number(value, digits=1):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        return '—'
    return f'{value:.{digits}f}'


def presence_reading(value, fresh):
    if not fresh or not isinstance(value, bool):
        return '—'
    return 'OUI' if value else 'NON'


def render(state=None, reachable=False, now=None):
    now = now or datetime.now(timezone.utc)
    state = state if isinstance(state, dict) else {}
    telemetry = state.get('telemetry') or {}
    device = state.get('device') or {}
    system = state.get('system') or {}
    online = reachable and system.get('mqtt_connected') is True and device.get('online') is not False
    fresh = online and -30 <= age(telemetry.get('ts'), now) <= 30
    alerts = state.get('alerts') or []
    recent = [alert for alert in alerts if isinstance(alert, dict)
              and alert.get('severity') in ('warning', 'critical')
              and -5 <= age(alert.get('ts'), now) <= 60]
    mqtt_connected = reachable and system.get('mqtt_connected') is True
    command = state.get('alarm_command') or {}
    buzzer_active = fresh and telemetry.get('buzzer') is True
    command_active = mqtt_connected and command.get('buzzer') is True
    if buzzer_active or command_active or (mqtt_connected and any(a['severity'] == 'critical' for a in recent)):
        alert_status, alert_color = 'En alerte', RED
    elif mqtt_connected and recent:
        alert_status, alert_color = 'Avertissement', '#ffbd66'
    elif fresh:
        alert_status, alert_color = 'Neutre', '#9aa9bb'
    else:
        alert_status, alert_color = '—', MUTED
    distance = telemetry.get('distance_cm')
    distance_ready = telemetry.get('distance_sensor') is True
    distance_value = 'Sans écho' if distance is None else number(distance)
    presence = telemetry.get('presence')
    presence_value = presence_reading(presence, fresh)

    image = Image.new('RGB', SIZE, BG)
    draw = ImageDraw.Draw(image)
    draw.text((12, 7), 'SENTINEL-X', font=font(15), fill=TEXT)
    mqtt_color = '#6de0b0' if mqtt_connected else MUTED
    draw.ellipse((169, 13, 176, 20), fill=mqtt_color)
    draw.text((183, 8), 'MQTT connecté' if mqtt_connected else 'MQTT déconnecté', font=font(12), fill=mqtt_color)
    readings = [
        ('TEMP', number(telemetry.get('temperature')), '°C', '#ffb45c', '#251d19'),
        ('HUM', number(telemetry.get('humidity')), '%', '#67cfff', '#132330'),
        ('GAZ', number(telemetry.get('gas'), 0), '', '#6de0b0', '#14271f'),
        ('DISTANCE', distance_value if distance_ready else '—', 'cm' if distance_ready and distance is not None else '', '#c1a1ff', '#221d30'),
        ('PRESENCE', presence_value, '', '#ffa7cd', '#2a1b25'),
        ('ALERTE', alert_status, '', alert_color, '#1b222b'),
    ]
    for index, (label, value, unit, accent, background) in enumerate(readings):
        x, y = 10 + (index % 2) * 155, 36 + (index // 2) * 66
        draw.rounded_rectangle((x, y, x + 145, y + 59), radius=7, fill=background)
        draw.text((x + 10, y + 5), label, font=font(11), fill=accent)
        visible = fresh if index < 4 else (fresh and isinstance(presence, bool)) if index == 4 else True
        value = value if visible else '—'
        value_font = font(23)
        for size in range(23, 11, -1):
            value_font = font(size)
            if draw.textlength(value, font=value_font) <= (100 if unit else 122):
                break
        draw.text((x + 10, y + 25), value, font=value_font, fill=accent if visible else MUTED)
        if fresh and unit:
            width = draw.textlength(value, font=value_font)
            draw.text((x + 14 + width, y + 34), unit, font=font(11), fill=accent)
    return image


def rgb565(image):
    result = bytearray(SIZE[0] * SIZE[1] * 2)
    for i, (r, g, b) in enumerate(image.convert('RGB').getdata()):
        struct.pack_into('<H', result, i * 2, ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3))
    return result


class FixedInfo(ctypes.Structure):
    _fields_ = [('id', ctypes.c_char * 16), ('smem_start', ctypes.c_ulong),
                ('smem_len', ctypes.c_uint32), ('type', ctypes.c_uint32),
                ('type_aux', ctypes.c_uint32), ('visual', ctypes.c_uint32),
                ('xpanstep', ctypes.c_uint16), ('ypanstep', ctypes.c_uint16),
                ('ywrapstep', ctypes.c_uint16), ('line_length', ctypes.c_uint32),
                ('mmio_start', ctypes.c_ulong), ('mmio_len', ctypes.c_uint32),
                ('accel', ctypes.c_uint32), ('capabilities', ctypes.c_uint16),
                ('reserved', ctypes.c_uint16 * 2)]


class Framebuffer:
    def __init__(self, path):
        import fcntl
        self.fd = os.open(path, os.O_RDWR)
        try:
            variable = bytearray(160)
            fixed = bytearray(ctypes.sizeof(FixedInfo))
            fcntl.ioctl(self.fd, 0x4600, variable, True)
            fcntl.ioctl(self.fd, 0x4602, fixed, True)
            width, height, _, _, xoff, yoff, bpp, grayscale = struct.unpack_from('=8I', variable)
            channels = [struct.unpack_from('=3I', variable, offset) for offset in (32, 44, 56)]
            if (width, height) != SIZE or bpp != 16 or grayscale or channels != [(11, 5, 0), (5, 6, 0), (0, 5, 0)] or sys.byteorder != 'little':
                raise ValueError('Expected 320x240 RGB565 little-endian framebuffer')
            info = FixedInfo.from_buffer_copy(fixed)
            if info.type != 0 or info.line_length < width * 2:
                raise ValueError('Unsupported framebuffer layout')
            self.stride = info.line_length
            self.offset = yoff * self.stride + xoff * 2
            if self.offset + (height - 1) * self.stride + width * 2 > info.smem_len:
                raise ValueError('Framebuffer memory is too small')
            self.memory = mmap.mmap(self.fd, info.smem_len, flags=mmap.MAP_SHARED,
                                    prot=mmap.PROT_READ | mmap.PROT_WRITE)
        except Exception:
            os.close(self.fd)
            raise

    def write(self, image):
        pixels = rgb565(image)
        for row in range(SIZE[1]):
            data = pixels[row * 640:(row + 1) * 640]
            offset = self.offset + row * self.stride
            self.memory[offset:offset + len(data)] = data

    def close(self):
        self.memory.close()
        os.close(self.fd)


def fetch(url):
    with urlopen(url, timeout=2) as response:
        payload = response.read(1024 * 1024 + 1)
    if len(payload) > 1024 * 1024:
        raise ValueError('API response too large')
    return validate_state(json.loads(payload))


def validate_state(state):
    if not isinstance(state, dict):
        raise ValueError('Invalid API state')
    for key in ('telemetry', 'device', 'system'):
        if state.get(key) is not None and not isinstance(state[key], dict):
            raise ValueError('Invalid API state')
    if not isinstance(state.get('alerts', []), list):
        raise ValueError('Invalid API alerts')
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', default='http://127.0.0.1:8000/api/v1/state')
    parser.add_argument('--websocket', default='ws://127.0.0.1:8000/ws')
    parser.add_argument('--framebuffer', default='/dev/fb0')
    parser.add_argument('--tty', help='Console to suspend while displaying, usually /dev/tty1')
    parser.add_argument('--preview', type=Path, help='Render a PNG without accessing the screen')
    parser.add_argument('--demo', action='store_true', help='Use demo values, never live data')
    args = parser.parse_args()
    demo = {'telemetry': {'temperature': 27.9, 'humidity': 59.0, 'gas': 12.0,
                         'distance_sensor': True, 'distance_cm': 29.4, 'presence': None,
                         'motion': False, 'ts': datetime.now(timezone.utc).isoformat()},
            'system': {'mqtt_connected': True}, 'device': {'online': True}, 'alerts': []}
    if args.preview:
        state = demo if args.demo else fetch(args.api)
        render(state, True).save(args.preview)
        return
    from websockets.sync.client import connect
    from websockets.exceptions import WebSocketException
    screen = Framebuffer(args.framebuffer)
    tty_fd = None
    old_mode = None
    socket = None
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        if args.tty:
            import fcntl
            tty_fd = os.open(args.tty, os.O_WRONLY)
            mode = bytearray(4)
            fcntl.ioctl(tty_fd, 0x4B3B, mode, True)  # KDGETMODE
            old_mode = struct.unpack('=i', mode)[0]
            fcntl.ioctl(tty_fd, 0x4B3A, 1)  # KD_GRAPHICS: console no longer overwrites pixels.
        print('PiTFT dashboard started (demo)' if args.demo else 'PiTFT dashboard started', flush=True)
        state = None
        retry_at = 0
        reachable = False
        first_frame = True
        last_pixels = None
        while not stopped:
            started = time.monotonic()
            try:
                if args.demo:
                    demo['telemetry']['ts'] = datetime.now(timezone.utc).isoformat()
                    state, reachable = demo, True
                    time.sleep(0.2)
                elif socket is None:
                    if started >= retry_at:
                        socket = connect(args.websocket, open_timeout=2, close_timeout=1,
                                         max_size=1024 * 1024, proxy=None)
                    else:
                        time.sleep(0.1)
                if socket is not None:
                    message = json.loads(socket.recv(timeout=1))
                    if not isinstance(message, dict) or message.get('type') != 'state':
                        raise ValueError('Invalid WebSocket message')
                    state = validate_state(message.get('data'))
                    reachable = True
            except TimeoutError:
                # No new message: refresh freshness, keep connection.
                if socket is None:
                    reachable = False
                    retry_at = time.monotonic() + 2
            except (OSError, ValueError, WebSocketException):
                reachable = False
                if socket is not None:
                    socket.close()
                    socket = None
                retry_at = time.monotonic() + 2
            frame = render(state, reachable)
            pixels = frame.tobytes()
            if pixels != last_pixels:
                screen.write(frame)
                last_pixels = pixels
            if first_frame:
                print('First frame written to framebuffer', flush=True)
                first_frame = False
    finally:
        if socket is not None:
            socket.close()
        if tty_fd is not None:
            try:
                if old_mode is not None:
                    fcntl.ioctl(tty_fd, 0x4B3A, old_mode)
            finally:
                os.close(tty_fd)
        screen.close()


if __name__ == '__main__':
    main()
