"""
Builds data_catalog.json - the manifest that every downstream module
(Module 2 onward) reads instead of touching raw files directly.

Also performs a cross-dataset consistency check: since NDVI 2023/2025,
WorldCover, and Forest Sample rasters all get overlaid together in later
modules, we flag (warn, not fail) if their CRS values differ, so we know
upfront whether Module 3 needs a reprojection step.
"""

import os
import json
import hashlib
from datetime import datetime, timezone

from app.config import DATA_CATALOG_PATH
from app.data_sources.config import DATASET_REGISTRY
from app.data_sources.validators import VALIDATORS


def _file_checksum(path, chunk_size=8192):
    """SHA-256 checksum, so we can later detect if a raw dataset was
    silently replaced/corrupted between runs."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def build_catalog():
    """Validates every dataset in the registry and returns the catalog dict.
    Does not write to disk - see save_catalog() for that."""
    catalog = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "datasets": {},
    }

    raster_crs_seen = {}  # dataset_key -> crs, for the consistency check

    for key, entry in DATASET_REGISTRY.items():
        path = os.path.join(entry["folder"], entry["filename"])
        validator = VALIDATORS[entry["type"]]
        result = validator(path)

        record = {
            "filename": entry["filename"],
            "path": path,
            "type": entry["type"],
            "role": entry.get("role", "unclassified"),
            "description": entry["description"],
            "exists": os.path.exists(path),
            "valid": result["valid"],
            "errors": result["errors"],
            "warnings": result["warnings"],
            "metadata": result["metadata"],
        }

        if record["exists"]:
            record["file_size_bytes"] = os.path.getsize(path)
            record["sha256"] = _file_checksum(path)
        else:
            record["file_size_bytes"] = None
            record["sha256"] = None

        if entry["type"] == "raster" and result["valid"]:
            raster_crs_seen[key] = result["metadata"].get("crs")

        catalog["datasets"][key] = record

    # Cross-raster CRS consistency check
    distinct_crs = set(v for v in raster_crs_seen.values() if v is not None)
    catalog["raster_crs_consistency"] = {
        "consistent": len(distinct_crs) <= 1,
        "crs_by_dataset": raster_crs_seen,
    }

    catalog["summary"] = {
        "total_datasets": len(DATASET_REGISTRY),
        "valid": sum(1 for d in catalog["datasets"].values() if d["valid"]),
        "invalid": sum(1 for d in catalog["datasets"].values() if not d["valid"]),
        "missing": sum(1 for d in catalog["datasets"].values() if not d["exists"]),
    }

    return catalog


def save_catalog(catalog=None):
    """Builds (if not provided) and writes the catalog to DATA_CATALOG_PATH."""
    if catalog is None:
        catalog = build_catalog()

    os.makedirs(os.path.dirname(DATA_CATALOG_PATH), exist_ok=True)
    with open(DATA_CATALOG_PATH, "w") as f:
        json.dump(catalog, f, indent=2)

    return DATA_CATALOG_PATH
