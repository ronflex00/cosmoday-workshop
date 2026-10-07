"""BDE Diagnose Python dependencies and USB capture; never install or download models."""

import argparse
import importlib
import platform
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def report(label: str, status: str) -> None:
    print(f"{label:.<18} {status}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-index", type=int, help="Override AI_CAMERA_INDEX")
    parser.add_argument("--skip-camera", action="store_true", help="Check dependencies only")
    args = parser.parse_args()
    if args.camera_index is not None and args.camera_index < 0:
        parser.error("--camera-index must be >= 0")
    print("Sentinel-X AI environment check\n", flush=True)
    valid = sys.version_info >= (3, 10)
    report("Python", f"{'OK' if valid else 'FAIL'} {platform.python_version()} (minimum 3.10)")
    report("Architecture", f"{platform.machine()} / {struct.calcsize('P') * 8}-bit Python")
    for label, name in (("OpenCV", "cv2"), ("Scikit-learn", "sklearn"),
                        ("Ultralytics", "ultralytics"), ("MQTT client", "paho.mqtt.client")):
        try:
            importlib.import_module(name)
            report(label, "OK")
        except Exception as exc:
            valid = False
            report(label, f"FAIL {type(exc).__name__}: {exc}")
    if args.skip_camera:
        report("Camera", "SKIPPED")
        return 0 if valid else 1
    camera = None
    try:
        from src.config import Config
        from src.vision.camera import Camera

        config = Config.from_env()
        index = config.camera_index if args.camera_index is None else args.camera_index
        camera = Camera(index, config.camera_width, config.camera_height)
        camera.open()
        frame = camera.read()
        report(f"Camera {index}", f"OK {frame.shape[1]}x{frame.shape[0]}")
    except Exception as exc:
        valid = False
        report("Camera", f"FAIL {type(exc).__name__}: {exc}")
    finally:
        if camera is not None:
            try:
                camera.close()
            except Exception as exc:
                valid = False
                report("Camera release", f"FAIL {type(exc).__name__}: {exc}")
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
