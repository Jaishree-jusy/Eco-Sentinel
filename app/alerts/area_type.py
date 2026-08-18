"""
Area type classification - Module 7A only.

Reuses the same "sample the WorldCover raster at a point" approach as
Module 6's forest classification, but maps the result to Urban/Rural/Others
instead of forest/non-forest.
"""

import rasterio
from app.alerts.config import AREA_TYPE_MAPPING, DEFAULT_AREA_TYPE


def classify_area_types(worldcover_path, lons, lats):
    """For each (lon, lat), returns 'Urban', 'Rural', or 'Others' based on
    the WorldCover class at that point. Returns 'Others' for points outside
    the raster's extent (a safe, non-alarming default)."""
    with rasterio.open(worldcover_path) as src:
        band = src.read(1)
        height, width = band.shape

        results = []
        for lon, lat in zip(lons, lats):
            row, col = src.index(lon, lat)
            if 0 <= row < height and 0 <= col < width:
                pixel_value = int(band[row, col])
                results.append(AREA_TYPE_MAPPING.get(pixel_value, DEFAULT_AREA_TYPE))
            else:
                results.append(DEFAULT_AREA_TYPE)

    return results
