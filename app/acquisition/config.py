"""
Configuration for Module 2 - Data Acquisition & Scheduler.

REGIONS defines the area(s) under monitoring ("region-wise monitoring" in
the architecture diagram). For now there's one region, matching the bounds
of your real NDVI datasets. Adding a second region later means adding one
entry here - nothing else in this module needs to change.

DEFAULT_YEAR_PAIR defines which two NDVI snapshots a run compares. This is
what Module 3/4 will use to know which "before" and "after" rasters to diff.
"""

from app.config import DATA_DIR
import os

ACQUISITION_RUNS_DIR = os.path.join(DATA_DIR, "acquisition_runs")

REGIONS = {
    "region_1": {
        "name": "Region 1 (Karnataka AOI)",
        # Matches the bounds already confirmed in data_catalog.json for
        # NDVI_2023 / NDVI_2025 / WorldCover / Forest_Sample.
        "bbox": {
            "left": 74.74998260145473,
            "bottom": 12.599949838117233,
            "right": 75.1000560676761,
            "top": 13.000059465664068,
        },
    },
}

DEFAULT_REGION = "region_1"

DEFAULT_YEAR_PAIR = {
    "base_year": 2023,
    "comparison_year": 2025,
}

# --- Live GEE acquisition config ---
# The 2023 baseline stays the historical local file (already validated,
# already produced the confirmed 5,078/979 real results - never
# re-downloaded). Only the comparison side is acquired live going forward.
GEE_CLOUD_COVER_THRESHOLD = 20  # percent, images cloudier than this are skipped
GEE_ACQUISITION_WINDOW_DAYS = 30  # search the most recent N days for a usable image
GEE_OUTPUT_DIR_NAME = "forest_samples"  # same folder as historical files
GEE_IMAGE_REGISTRY_PATH_NAME = "gee_image_registry.json"

# Maps a year to the dataset registry keys (from Module 1) needed for that year.
# Module 3 onward reads dataset paths from the manifest, not from this map directly.
YEAR_TO_DATASET_KEYS = {
    2023: {"ndvi": "ndvi_2023", "raw_imagery": "forest_sample_2023"},
    2025: {"ndvi": "ndvi_2025", "raw_imagery": "forest_sample_2025"},
}

# Dataset keys (from Module 1's registry) that every run needs regardless of year.
STATIC_DATASET_KEYS = ["worldcover_2021", "gadm_forest_boundary", "fire_archive_1", "fire_archive_2"]
