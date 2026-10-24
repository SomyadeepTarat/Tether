"""Load credentials only into the backend process, never into frontend bundles."""
from pathlib import Path
from dotenv import load_dotenv


def load_backend_environment(root: Path):
    # Explicit shell/service variables win, followed by the backend file.
    for path in (root / 'backend' / '.env', root / '.env'):
        load_dotenv(path, override=False, interpolate=False, encoding='utf-8-sig')
