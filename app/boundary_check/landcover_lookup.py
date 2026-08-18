"""
Forest boundary classification - Module 6, "Overlay with Forest Boundaries" step.

Classifies each point (loss polygon centroid) as inside or outside forest
by sampling the ESA WorldCover raster's class value at that exact location.
"""

import numpy as np
import rasterio

from app.boundary_check.config import FOREST_CLASS_VALUE


class BoundaryCheckError(Exception):
    pass


def classify_points_by_landcover(worldcover_path, lons, lats):
    """For each (lon, lat), samples the WorldCover raster and returns
    'inside_forest' if the pixel's class == FOREST_CLASS_VALUE,
    'outside_forest' otherwise, or 'out_of_extent' if the point falls
    outside the raster's coverage entirely."""

    with rasterio.open(worldcover_path) as src:
        band = src.read(1)
        height, width = band.shape

        # Sanity check: confirm this raster actually contains the forest
        # class value anywhere, rather than silently trusting the filename.
        if not np.any(band == FOREST_CLASS_VALUE):
            raise BoundaryCheckError(
                f"WorldCover raster at {worldcover_path} contains no pixels with "
                f"class value {FOREST_CLASS_VALUE} (expected 'Tree cover' in the "
                f"standard ESA WorldCover scheme). This dataset may not use "
                f"standard class codes - verify before trusting boundary classification."
            )

        classifications = []
        for lon, lat in zip(lons, lats):
            row, col = src.index(lon, lat)
            if 0 <= row < height and 0 <= col < width:
                pixel_value = int(band[row, col])
                classifications.append(
                    "inside_forest" if pixel_value == FOREST_CLASS_VALUE else "outside_forest"
                )
            else:
                classifications.append("out_of_extent")

    return classifications
