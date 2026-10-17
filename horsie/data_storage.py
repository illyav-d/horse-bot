"""Runtime JSON storage, with Railway volume defaults and atomic writes."""

import json
import os
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
DATA_DIR = PROJECT_ROOT / "data"

def data_path(variable, filename):
    if override := os.getenv(variable):
        return Path(override)
    if mount := os.getenv("RAILWAY_VOLUME_MOUNT_PATH"):
        return Path(mount) / filename
    # Keep existing local saves readable until the stopped bot's files have
    # been moved into data/. Never replace a live save with an empty one.
    legacy = PROJECT_ROOT / filename
    if legacy.exists() and not (DATA_DIR / filename).exists():
        return legacy
    return DATA_DIR / filename


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as file:
            temporary = Path(file.name)
            json.dump(data, file, indent=4)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
