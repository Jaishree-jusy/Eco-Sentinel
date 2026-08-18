"""
Region/Division assignment - Module 6.

Assigns a human-readable region label (for the "Region / Division" field
in Module 7's alerts) by spatially joining each point against the GADM
administrative boundary layer.
"""

import geopandas as gpd

from app.boundary_check.config import GADM_REGION_LAYER, GADM_REGION_COLUMN_CANDIDATES


def assign_regions(points_gdf, gadm_path, layer=GADM_REGION_LAYER):
    """points_gdf: GeoDataFrame of Point geometries (EPSG:4326).
    Returns a list of region label strings, one per point, in the same order."""

    admin_gdf = gpd.read_file(gadm_path, layer=layer)

    if admin_gdf.crs != points_gdf.crs:
        admin_gdf = admin_gdf.to_crs(points_gdf.crs)

    region_column = None
    for candidate in GADM_REGION_COLUMN_CANDIDATES:
        if candidate in admin_gdf.columns:
            region_column = candidate
            break

    if region_column is None:
        # No expected column found - fall back to whatever non-geometry
        # column exists, rather than crashing the whole pipeline.
        non_geom_cols = [c for c in admin_gdf.columns if c != "geometry"]
        region_column = non_geom_cols[0] if non_geom_cols else None

    admin_subset = admin_gdf[[region_column, "geometry"]] if region_column else admin_gdf[["geometry"]]

    joined = gpd.sjoin(points_gdf, admin_subset, how="left", predicate="within")

    if region_column and region_column in joined.columns:
        return joined[region_column].fillna("Unknown").tolist(), region_column
    return ["Unknown"] * len(points_gdf), None
