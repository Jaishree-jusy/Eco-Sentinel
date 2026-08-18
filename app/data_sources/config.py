"""
Dataset registry for Module 1.

This is the contract: every file listed here is expected to exist under
data/raw_images/<subfolder>/<filename>. The validator and catalog builder
both read from this single list, so adding a new dataset later means
editing ONE place, not scattering filenames across the codebase.

type:
    "raster"  -> validated with rasterio (NDVI, WorldCover, Forest Sample)
    "gpkg"    -> validated with geopandas/fiona (GADM forest boundary)
    "csv"     -> validated with pandas (NASA FIRMS fire archive)
"""

from app.config import (
    NDVI_RAW_DIR,
    LANDCOVER_DIR,
    FOREST_SAMPLES_DIR,
    BOUNDARIES_DIR,
    FIRE_ARCHIVE_DIR,
)

DATASET_REGISTRY = {
    "ndvi_2023": {
        "filename": "NDVI_2023.tif",
        "folder": NDVI_RAW_DIR,
        "type": "raster",
        "role": "processed_ndvi_output",
        "description": "Sentinel-2 derived NDVI, 2023 (already-processed output of GEE Processing / Box 3)",
    },
    "ndvi_2025": {
        "filename": "NDVI_2025.tif",
        "folder": NDVI_RAW_DIR,
        "type": "raster",
        "role": "processed_ndvi_output",
        "description": "Sentinel-2 derived NDVI, 2025 (already-processed output of GEE Processing / Box 3)",
    },
    "worldcover_2021": {
        "filename": "ESA_WorldCover_2021.tif",
        "folder": LANDCOVER_DIR,
        "type": "raster",
        "role": "reference_landcover",
        "description": "ESA WorldCover land cover classification, 2021",
    },
    "forest_sample_2023": {
        "filename": "Forest_Sample_2023.tif",
        "folder": FOREST_SAMPLES_DIR,
        "type": "raster",
        "role": "raw_source_imagery",
        "description": (
            "Raw Sentinel-2 Level-2A multispectral surface reflectance imagery, 2023 "
            "(26 bands: B1-B12/B8A spectral bands, AOT/WVP, SCL, TCI true-color, QA/mask bands). "
            "Feeds Module 3 (GEE Processing: cloud masking, scene classification, NDVI calculation). "
            "NOT NDVI, NOT training labels - confirmed via band-level inspection on 2026-08-04."
        ),
    },
    "forest_sample_2025": {
        "filename": "Forest_Sample_2025.tif",
        "folder": FOREST_SAMPLES_DIR,
        "type": "raster",
        "role": "raw_source_imagery",
        "description": (
            "Raw Sentinel-2 Level-2A multispectral surface reflectance imagery, 2025 "
            "(26 bands: B1-B12/B8A spectral bands, AOT/WVP, SCL, TCI true-color, QA/mask bands). "
            "Feeds Module 3 (GEE Processing: cloud masking, scene classification, NDVI calculation). "
            "NOT NDVI, NOT training labels - confirmed via band-level inspection on 2026-08-04."
        ),
    },
    "gadm_forest_boundary": {
        "filename": "gadm41_IND.gpkg",
        "folder": BOUNDARIES_DIR,
        "type": "gpkg",
        "role": "reference_boundary",
        "description": "GADM administrative/forest boundary data for India",
    },
    "fire_archive_1": {
        "filename": "fire_archive_SV-C2_778067.csv",
        "folder": FIRE_ARCHIVE_DIR,
        "type": "csv",
        "role": "reference_fire_context",
        "description": "NASA FIRMS fire archive (batch 1)",
    },
    "fire_archive_2": {
        "filename": "fire_archive_SV-C2_778068.csv",
        "folder": FIRE_ARCHIVE_DIR,
        "type": "csv",
        "role": "reference_fire_context",
        "description": "NASA FIRMS fire archive (batch 2)",
    },
}

# Columns we require to trust a FIRMS-style fire archive CSV.
# These are the columns actually used later by boundary/severity logic.
REQUIRED_FIRE_CSV_COLUMNS = ["latitude", "longitude", "acq_date"]
