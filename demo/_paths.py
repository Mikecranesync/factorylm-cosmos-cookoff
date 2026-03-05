import sys
from pathlib import Path


def get_base_path() -> Path:
    """Return bundle dir (PyInstaller) or repo root (dev)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


BASE_PATH = get_base_path()
DEMO_DIR = BASE_PATH / "demo"
CLIPS_DIR = DEMO_DIR / "clips"
CONFIG_DIR = BASE_PATH / "config"
PROMPTS_PATH = DEMO_DIR / "prompts" / "factory_diagnosis.yaml"
OUTPUT_DIR = Path.cwd() / "output"
