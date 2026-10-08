"""Run vision only: python -m src.vision_main; leave environment_main running."""

from .main import main


if __name__ == "__main__":
    raise SystemExit(main(run_environment=False))
