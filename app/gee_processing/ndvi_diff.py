"""
NDVI Difference Analysis - Module 3, step 4.

diff = comparison_year_NDVI - base_year_NDVI
Negative values indicate vegetation loss (NDVI dropped); this raster is
what Module 4 (Vegetation Loss Detection) will threshold.
"""

import numpy as np
import rasterio

from app.gee_processing.config import NDVI_NODATA


def compute_ndvi_diff(base_ndvi_path, comparison_ndvi_path, output_path):
    with rasterio.open(base_ndvi_path) as base_src, rasterio.open(comparison_ndvi_path) as comp_src:
        if base_src.width != comp_src.width or base_src.height != comp_src.height:
            raise ValueError(
                f"NDVI rasters have mismatched dimensions: "
                f"base={base_src.width}x{base_src.height}, "
                f"comparison={comp_src.width}x{comp_src.height}. "
                f"They must share the same grid to be differenced."
            )

        base = base_src.read(1)
        comp = comp_src.read(1)

        invalid_mask = (base == NDVI_NODATA) | (comp == NDVI_NODATA)

        diff = (comp.astype("float32") - base.astype("float32"))
        diff[invalid_mask] = NDVI_NODATA

        profile = base_src.profile.copy()
        profile.update(count=1, dtype="float32", nodata=NDVI_NODATA)

        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(diff, 1)

    valid = diff[diff != NDVI_NODATA]
    stats = {
        "output_path": output_path,
        "total_pixels": int(diff.size),
        "invalid_pixel_count": int(np.sum(invalid_mask)),
        "valid_pixel_count": int(valid.size),
        "diff_min": float(np.min(valid)) if valid.size else None,
        "diff_max": float(np.max(valid)) if valid.size else None,
        "diff_mean": float(np.mean(valid)) if valid.size else None,
    }
    return stats
