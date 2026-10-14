"""Runtime JSON storage, with Railway volume defaults and atomic writes."""

import json
import os
import tempfile
from pathlib import Path


def data_path(variable, filename):
    if override := os.getenv(variable):
        return Path(override)
    if mount := os.getenv("RAILWAY_VOLUME_MOUNT_PATH"):
        return Path(mount) / filename
    return Path(filename)


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
