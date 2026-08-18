"""
Area calculation - Module 5, step 2.
"""

from app.polygon_analysis.config import AREA_CALC_CRS
from app.common.content_id import stable_id


def compute_area_ha(gdf):
    """Adds an 'area_ha' column, computed by reprojecting to a metric UTM
    CRS (degrees are not area-accurate). Returns the original gdf (in its
    original CRS) with the new column - does not change gdf's CRS."""
    if gdf.empty:
        gdf["area_ha"] = []
        return gdf

    projected = gdf.geometry.to_crs(AREA_CALC_CRS)
    area_m2 = projected.area
    gdf = gdf.copy()
    gdf["area_ha"] = (area_m2 / 10000).round(4)
    return gdf


def filter_by_min_area(gdf, min_area_ha):
    """Drops polygons smaller than min_area_ha. Requires 'area_ha' column
    to already exist (call compute_area_ha first)."""
    if gdf.empty:
        return gdf
    return gdf[gdf["area_ha"] >= min_area_ha].reset_index(drop=True)


def compute_centroids(gdf):
    """Adds 'centroid_lon'/'centroid_lat' columns, computed correctly by
    reprojecting to the metric UTM CRS first, taking the centroid there,
    then reprojecting the centroid point back to EPSG:4326.

    Computing centroids directly on geographic (lat/long) coordinates is
    geometrically wrong - it's an unweighted average of degrees, not the
    true geometric center - so we deliberately don't do gdf.geometry.centroid
    directly here.
    """
    if gdf.empty:
        gdf["centroid_lon"] = []
        gdf["centroid_lat"] = []
        return gdf

    gdf = gdf.copy()
    original_crs = gdf.crs

    projected_centroids = gdf.geometry.to_crs(AREA_CALC_CRS).centroid
    centroids_geo = projected_centroids.to_crs(original_crs)

    gdf["centroid_lon"] = centroids_geo.x.round(6)
    gdf["centroid_lat"] = centroids_geo.y.round(6)
    return gdf


def assign_polygon_ids(gdf, base_year, comparison_year):
    """Assigns a stable, content-derived polygon_id to each row, based on
    its centroid + year pair - NOT its row position. Requires centroid_lon/
    centroid_lat columns to already exist (call compute_centroids first).

    This is what guarantees rerunning the pipeline against the same
    underlying data always produces the same polygon_id for the same
    real-world location, regardless of what order polygons were
    discovered in during vectorization.
    """
    if gdf.empty:
        gdf["polygon_id"] = []
        return gdf

    gdf = gdf.copy()
    gdf["polygon_id"] = [
        stable_id(row.centroid_lon, row.centroid_lat, base_year, comparison_year, prefix="LOSS-")
        for row in gdf.itertuples()
    ]
    return gdf
