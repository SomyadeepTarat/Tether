"""Load the repository's ignored .env without overriding explicit process settings."""
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def load_environment(path=None):
    return load_dotenv(dotenv_path=path or ROOT / '.env', override=False, interpolate=False, encoding='utf-8-sig')
