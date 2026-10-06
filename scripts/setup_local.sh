#!/usr/bin/env bash
set -euo pipefail

sentinel_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
sentinel_no_camera=false
if [[ "${1:-}" == "--no-camera" && $# == 1 ]]; then
  sentinel_no_camera=true
elif [[ $# != 0 ]]; then
  echo 'Usage: bash scripts/setup_local.sh [--no-camera]' >&2
  exit 2
fi
for sentinel_program in python3 node npm mosquitto mosquitto_sub; do
  if ! command -v "$sentinel_program" >/dev/null 2>&1; then
    echo "Missing prerequisite: $sentinel_program. See README.md." >&2
    exit 1
  fi
done
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else "Python 3.11+ required")'
node -e 'const [major,minor]=process.versions.node.split(".").map(Number); if (!((major===20&&minor>=19)||(major===22&&minor>=12)||major>22)) { console.error("Node 20.19+ or 22.12+ required"); process.exit(1); }'

cd -- "$sentinel_root"
echo 'Installing backend in backend/.venv ...'
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt

echo 'Installing AI in ai/.venv ...'
python3 -m venv ai/.venv
if "$sentinel_no_camera"; then
  ai/.venv/bin/python -m pip install -r scripts/requirements-anomaly.txt
else
  ai/.venv/bin/python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
  ai/.venv/bin/python -m pip install -r ai/requirements.txt
  echo 'Preparing the local YOLO model (first setup needs Internet) ...'
  (
    cd ai
    .venv/bin/python -c 'from ultralytics import YOLO; YOLO("yolov8n.pt")'
  )
fi

echo 'Installing frontend from package-lock.json ...'
(
  cd frontend
  npm ci --no-fund
)
backend/.venv/bin/python -m pip check
ai/.venv/bin/python -m pip check
echo 'Setup ready. Run: python3 scripts/local.py start'
if "$sentinel_no_camera"; then
  echo 'For this lightweight setup, use: python3 scripts/local.py start --no-camera'
fi
