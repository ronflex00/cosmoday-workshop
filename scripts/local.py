"""Start, inspect and stop the local Linux demo from a single integrated clone."""
import argparse
import json
import logging
import os
from pathlib import Path
from queue import Queue
import re
import shutil
import signal
import socket
import subprocess
import sys
from threading import Event, Thread
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
STATE_FILE = RUNTIME / 'processes.json'


def configuration():
    values = {}
    profile = ROOT / '.env.local'
    if profile.exists():
        for number, line in enumerate(profile.read_text().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            name, separator, value = line.partition('=')
            name, value = name.strip(), value.strip()
            if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', name):
                raise ValueError(f'Invalid .env.local assignment at line {number}')
            if value.startswith(('"', "'")):
                if value[-1:] != value[:1] or len(value) < 2:
                    raise ValueError(f'Invalid quoting at .env.local line {number}')
                value = value[1:-1]
            if name in values:
                raise ValueError(f'Duplicate variable {name} in .env.local')
            values[name] = value
    env = os.environ.copy()
    defaults = dict(MQTT_HOST='localhost', MQTT_PORT='18883', MQTT_TLS='false',
                    MQTT_USERNAME='', MQTT_PASSWORD='', MQTT_TLS_CA='', MQTT_TLS_CERT='', MQTT_TLS_KEY='',
                    API_HOST='127.0.0.1', API_PORT='8000', FRONTEND_HOST='localhost', FRONTEND_PORT='5173',
                    AI_CAMERA_INDEX='0', AI_SHOW_WINDOW='false', AI_TRAINING_SAMPLES='20',
                    AI_CONTAMINATION='0.1', AI_LOG_LEVEL='INFO', OMP_NUM_THREADS='2', PYTHONUNBUFFERED='1')
    for name, value in defaults.items():
        env.setdefault(name, values.get(name, value))
    for name, value in values.items():
        env.setdefault(name, value)
    for name in ('MQTT_PORT', 'API_PORT', 'FRONTEND_PORT'):
        if not env[name].isdigit() or not 1 <= int(env[name]) <= 65535:
            raise ValueError(f'{name} must be between 1 and 65535')
    api_host = 'localhost' if env['API_HOST'] == '0.0.0.0' else env['API_HOST']
    frontend_host = 'localhost' if env['FRONTEND_HOST'] == '0.0.0.0' else env['FRONTEND_HOST']
    api_url = f"http://{api_host}:{env['API_PORT']}"
    ui_url = f"http://{frontend_host}:{env['FRONTEND_PORT']}"
    env.setdefault('CORS_ORIGINS', ui_url)
    env.setdefault('VITE_API_URL', api_url)
    env.setdefault('VITE_WS_URL', api_url.replace('http://', 'ws://', 1) + '/ws')
    env.setdefault('VITE_DATA_STALE_SECONDS', '30')
    env.setdefault('AI_YOLO_MODEL', str(ROOT / 'ai/yolov8n.pt'))
    return env, api_url, ui_url


def start_ticks(pid):
    try:
        # Field 22; ignore the process name, which can itself contain spaces.
        fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except (OSError, IndexError):
        return None


def alive(record):
    return record['ticks'] is not None and start_ticks(record['pid']) == record['ticks']


def busy(port, host='localhost'):
    try:
        with socket.create_connection((host, int(port)), timeout=0.3):
            return True
    except OSError:
        return False


def api_state(api_url):
    with urlopen(api_url + '/api/v1/state', timeout=1) as response:
        return json.load(response)


def stop_processes(records):
    for record in reversed(records):
        if alive(record):
            try:
                os.killpg(record['pid'], signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 8
    while any(alive(record) for record in records) and time.monotonic() < deadline:
        time.sleep(0.1)
    for record in records:
        if alive(record):
            try:
                os.killpg(record['pid'], signal.SIGKILL)
            except ProcessLookupError:
                pass


def launch(args):
    if not sys.platform.startswith('linux'):
        raise RuntimeError('This launcher targets Linux / Raspberry Pi OS. See the manual guides for other systems.')
    env, api_url, ui_url = configuration()
    if STATE_FILE.exists() and any(alive(record) for record in json.loads(STATE_FILE.read_text())['processes']):
        raise RuntimeError('A managed session already exists. Use status or stop first.')
    backend_python = ROOT / 'backend/.venv/bin/python'
    ai_python = ROOT / 'ai/.venv/bin/python'
    vite = ROOT / 'frontend/node_modules/vite/bin/vite.js'
    for path in (backend_python, ai_python, vite):
        if not path.exists():
            raise RuntimeError('Dependencies missing. Run bash scripts/setup_local.sh first.')
    for program in ('node', 'mosquitto', 'mosquitto_sub'):
        if shutil.which(program) is None:
            raise RuntimeError(f'Missing prerequisite: {program}')
    for port in (env['API_PORT'], env['FRONTEND_PORT']):
        if busy(port):
            raise RuntimeError(f'Port {port} is already used. Stop the existing service or set different ports in .env.local.')
    RUNTIME.mkdir(exist_ok=True)
    records, children = [], []

    def start(name, command, cwd):
        log_path = RUNTIME / f'{name}.log'
        offset = log_path.stat().st_size if log_path.exists() else 0
        with log_path.open('a') as output:
            child = subprocess.Popen([str(item) for item in command], cwd=cwd, env=env,
                                     stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        children.append(child)
        records.append({'name': name, 'pid': child.pid, 'ticks': start_ticks(child.pid), 'log_offset': offset})
        print(f'{name}: started', flush=True)

    def wait_until(predicate, label, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if any(child.poll() is not None for child in children):
                raise RuntimeError(f'A service stopped during {label}; check .runtime/*.log')
            try:
                if predicate():
                    return
            except (OSError, URLError):
                pass
            time.sleep(0.2)
        raise RuntimeError(f'Timeout waiting for {label}; check .runtime/*.log')

    try:
        if env['MQTT_HOST'] in ('localhost', '127.0.0.1') and env['MQTT_TLS'].lower() in ('false', '0', 'no'):
            if not busy(env['MQTT_PORT']):
                start('broker', ['mosquitto', '-p', env['MQTT_PORT']], ROOT)
                wait_until(lambda: busy(env['MQTT_PORT']), 'broker')
            else:
                print('broker: reusing existing listener', flush=True)
        start('backend', [backend_python, '-m', 'app.main'], ROOT / 'backend')
        wait_until(lambda: api_state(api_url)['system']['mqtt_connected'], 'backend and MQTT')
        start('frontend', ['node', vite, '--host', env['FRONTEND_HOST'], '--port', env['FRONTEND_PORT'], '--strictPort'], ROOT / 'frontend')
        def ui_ready():
            with urlopen(ui_url, timeout=1) as response:
                return response.status == 200
        wait_until(ui_ready, 'frontend')
        if args.no_camera:
            start('ai', [ai_python, Path(__file__), '_anomaly'], ROOT / 'ai')
        else:
            start('ai', [ai_python, '-m', 'src.main'], ROOT / 'ai')
        ai_record = records[-1]
        def ai_subscribed():
            with (RUNTIME / 'ai.log').open('rb') as output:
                output.seek(ai_record['log_offset'])
                return b'Subscribed to sentinel/telemetry' in output.read()
        wait_until(ai_subscribed, 'AI subscription', 45)
        if not args.no_camera:
            wait_until(lambda: api_state(api_url)['vision'] is not None, 'webcam and YOLO', 45)
        if not args.no_demo:
            start('telemetry', [ai_python, Path(__file__), '_telemetry'], ROOT / 'ai')
        if env['MQTT_TLS'].lower() in ('false', '0', 'no') and not env['MQTT_USERNAME']:
            start('events', ['mosquitto_sub', '-h', env['MQTT_HOST'], '-p', env['MQTT_PORT'], '-t', 'sentinel/commands', '-t', 'sentinel/alerts', '-v'], ROOT)
        STATE_FILE.write_text(json.dumps({'api_url': api_url, 'ui_url': ui_url, 'processes': records}, indent=2))
        print(f'Dashboard: {ui_url}\nAPI: {api_url}/docs\nLogs: {RUNTIME}\nStop: python3 scripts/local.py stop', flush=True)
        if args.no_camera:
            print('Vision disabled; IsolationForest is active. No artificial vision results are published.')
        if not args.no_demo:
            print('Simulated sensor node sentinel-demo: 20 normal measurements then 5 extreme measurements, repeated.')
    except BaseException:
        stop_processes(records)
        raise


def anomaly_only():
    sys.path.insert(0, str(ROOT / 'ai'))
    from src.anomaly.detector import AnomalyDetector
    from src.anomaly.service import process_telemetry
    from src.common.mqtt_client import MQTTClient
    from src.config import Config
    logging.basicConfig(level=logging.INFO, format='[%(name)s] %(message)s')
    stop, queue = Event(), Queue(maxsize=128)
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda signum, frame: stop.set())
    config = Config.from_env()
    client = MQTTClient(config, queue)
    worker = Thread(target=process_telemetry, args=(queue, AnomalyDetector(config.training_samples, config.contamination), client, stop))
    worker.start()
    try:
        client.start()
        stop.wait()
    finally:
        stop.set()
        worker.join()
        client.stop()


def telemetry_loop():
    stop, child = Event(), None
    def shutdown(signum, frame):
        stop.set()
        if child is not None and child.poll() is None:
            child.terminate()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, shutdown)
    while not stop.is_set():
        child = subprocess.Popen([sys.executable, str(ROOT / 'ai/scripts/send_fake_telemetry.py'),
                                  '--mode', 'demo', '--normal-count', os.environ.get('AI_TRAINING_SAMPLES', '20'),
                                  '--interval', '1', '--device-id', 'sentinel-demo'], cwd=ROOT / 'ai')
        code = child.wait()
        if code and not stop.is_set():
            print('Telemetry generator stopped; retrying in five seconds', flush=True)
        stop.wait(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('start', 'stop', 'status', '_anomaly', '_telemetry'))
    parser.add_argument('--no-camera', action='store_true', help='Run IsolationForest without opening a webcam')
    parser.add_argument('--no-demo', action='store_true', help='Use real ESP telemetry instead of simulated measurements')
    args = parser.parse_args()
    if args.command == '_anomaly':
        anomaly_only()
    elif args.command == '_telemetry':
        telemetry_loop()
    elif args.command == 'start':
        launch(args)
    elif not STATE_FILE.exists():
        print('No managed local session.')
    else:
        state = json.loads(STATE_FILE.read_text())
        if args.command == 'stop':
            stop_processes(state['processes'])
            STATE_FILE.unlink()
            print('Managed services stopped. Reused services were left running.')
        else:
            for record in state['processes']:
                print(record['name'] + ': ' + ('RUNNING' if alive(record) else 'STOPPED'))
            print('Dashboard: ' + state['ui_url'])


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
