"""
GEE image registry - Module 2.

Persists which GEE image IDs have already been acquired, so a rerun never
re-downloads the same image. This is real dedup against the actual GEE
image ID (not a guess or a time-based heuristic).
"""

import os
import json

from app.config import DATA_DIR
from app.acquisition.config import GEE_IMAGE_REGISTRY_PATH_NAME

REGISTRY_PATH = os.path.join(DATA_DIR, "acquisition_runs", GEE_IMAGE_REGISTRY_PATH_NAME)


def _load_registry(registry_path=None):
    registry_path = registry_path or REGISTRY_PATH
    if not os.path.exists(registry_path):
        return {}
    with open(registry_path) as f:
        return json.load(f)


def _save_registry(registry, registry_path=None):
    registry_path = registry_path or REGISTRY_PATH
    os.makedirs(os.path.dirname(registry_path), exist_ok=True)
    with open(registry_path, "w") as f:
        json.dump(registry, f, indent=2)


def already_acquired(gee_image_id, registry_path=None):
    """Returns the registry entry if this exact GEE image was already
    downloaded AND the local file still exists, else None."""
    registry = _load_registry(registry_path)
    entry = registry.get(gee_image_id)
    if entry and os.path.exists(entry["local_path"]):
        return entry
    return None


def register_acquisition(gee_image_id, local_path, sha256, acquired_at, cloud_cover_pct, registry_path=None):
    registry = _load_registry(registry_path)
    registry[gee_image_id] = {
        "local_path": local_path,
        "sha256": sha256,
        "acquired_at": acquired_at,
        "cloud_cover_pct": cloud_cover_pct,
    }
    _save_registry(registry, registry_path)
