"""
Severity Estimation - Module 5, step 3.
"""

import numpy as np
import rasterio
import rasterio.mask

from app.gee_processing.config import NDVI_NODATA
from app.polygon_analysis.config import SEVERITY_BINS


def _classify_severity(mean_diff):
    if mean_diff is None:
        return "unknown"
    for label, lower, upper in SEVERITY_BINS:
        if lower <= mean_diff < upper:
            return label
    return "unknown"


def estimate_severity(gdf, diff_raster_path):
    """Adds 'mean_ndvi_diff' and 'severity_level' columns by sampling the
    NDVI diff raster within each polygon's geometry."""
    if gdf.empty:
        gdf["mean_ndvi_diff"] = []
        gdf["severity_level"] = []
        return gdf

    gdf = gdf.copy()
    mean_diffs = []

    with rasterio.open(diff_raster_path) as src:
        for geom in gdf.geometry:
            try:
                out_image, _ = rasterio.mask.mask(src, [geom], crop=True, nodata=NDVI_NODATA)
                data = out_image[0]
                valid = data[data != NDVI_NODATA]
                mean_diffs.append(float(np.mean(valid)) if valid.size else None)
            except ValueError:
                # geometry doesn't overlap raster - shouldn't happen since
                # the mask came from this same raster's grid, but guard anyway
                mean_diffs.append(None)

    gdf["mean_ndvi_diff"] = mean_diffs
    gdf["severity_level"] = [_classify_severity(d) for d in mean_diffs]
    return gdf
