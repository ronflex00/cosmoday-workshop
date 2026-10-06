"""The launcher must only stop processes from its own recorded session."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

path = Path(__file__).resolve().parents[1] / 'scripts/local.py'
spec = importlib.util.spec_from_file_location('local_launcher', path)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux process ownership checks')
class LauncherOwnershipTests(unittest.TestCase):
    def test_stale_record_does_not_stop_unrelated_process(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        try:
            launcher.stop_processes([{'pid': child.pid, 'ticks': 'stale-session'}])
            self.assertIsNone(child.poll())
        finally:
            child.terminate()
            child.wait(timeout=3)

    def test_managed_process_is_stopped(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        try:
            record = {'pid': child.pid, 'ticks': launcher.start_ticks(child.pid)}
            self.assertIsNotNone(record['ticks'])
            launcher.stop_processes([record])
            self.assertIsNotNone(child.wait(timeout=3))
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=3)


if __name__ == '__main__':
    unittest.main()
