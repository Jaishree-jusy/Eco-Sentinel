"""
Raster to Polygon conversion - Module 5, step 1.
"""

import geopandas as gpd
import rasterio
import rasterio.features
from shapely.geometry import shape

from app.loss_detection.config import LOSS_VALUE


def raster_to_polygons(mask_path):
    """Reads a binary loss-mask raster and returns a GeoDataFrame of polygons
    for every contiguous region where mask == LOSS_VALUE, in the raster's
    native CRS."""
    with rasterio.open(mask_path) as src:
        mask_array = src.read(1)
        transform = src.transform
        crs = src.crs

        loss_binary = (mask_array == LOSS_VALUE)

        polygons = []
        for geom, value in rasterio.features.shapes(mask_array, mask=loss_binary, transform=transform):
            if value == LOSS_VALUE:
                polygons.append(shape(geom))

    if not polygons:
        return gpd.GeoDataFrame({"geometry": []}, crs=crs)

    gdf = gpd.GeoDataFrame({"geometry": polygons}, crs=crs)
    # NOTE: polygon_id is deliberately NOT assigned here. Assigning it from
    # row position (e.g. f"loss_{i:05d}") would make it depend on iteration
    # order, which can shift between reruns even when the underlying loss
    # areas haven't changed. The pipeline assigns a stable, content-derived
    # ID later, once each polygon's centroid is known.
    return gdf
