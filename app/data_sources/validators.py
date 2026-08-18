"""
Validators for each dataset type used in ECO-SENTINEL Module 1.

Each validator takes a file path and returns a dict:
    {
        "valid": bool,
        "errors": [str, ...],     # empty if valid
        "warnings": [str, ...],   # non-fatal issues
        "metadata": {...}          # type-specific metadata for the catalog
    }

Design note: a "warning" does not fail validation (e.g. CRS mismatch between
rasters is worth flagging now, but Module 3/5 will reproject as needed rather
than blocking us at ingestion time).
"""

import os
import rasterio
import fiona
import geopandas as gpd
import pandas as pd

from app.data_sources.config import REQUIRED_FIRE_CSV_COLUMNS


def _base_result():
    return {"valid": True, "errors": [], "warnings": [], "metadata": {}}


def validate_raster(path):
    """Validate a GeoTIFF: file opens, has a CRS, has at least one band,
    has non-zero dimensions, and bounds are sane."""
    result = _base_result()

    if not os.path.exists(path):
        result["valid"] = False
        result["errors"].append(f"File not found: {path}")
        return result

    try:
        with rasterio.open(path) as src:
            if src.crs is None:
                result["valid"] = False
                result["errors"].append("Raster has no CRS defined")

            if src.count < 1:
                result["valid"] = False
                result["errors"].append("Raster has no bands")

            if src.width <= 0 or src.height <= 0:
                result["valid"] = False
                result["errors"].append("Raster has invalid dimensions")

            result["metadata"] = {
                "crs": str(src.crs) if src.crs else None,
                "width": src.width,
                "height": src.height,
                "band_count": src.count,
                "bounds": {
                    "left": src.bounds.left,
                    "bottom": src.bounds.bottom,
                    "right": src.bounds.right,
                    "top": src.bounds.top,
                },
                "resolution": {"x": src.res[0], "y": src.res[1]},
                "dtype": src.dtypes[0] if src.count > 0 else None,
                "nodata": src.nodata,
            }

    except Exception as e:
        result["valid"] = False
        result["errors"].append(f"Could not open raster: {e}")

    return result


def validate_gpkg(path):
    """Validate a GeoPackage: file opens, has at least one layer with
    geometries, and has a CRS."""
    result = _base_result()

    if not os.path.exists(path):
        result["valid"] = False
        result["errors"].append(f"File not found: {path}")
        return result

    try:
        # fiona.listlayers is stable across geopandas versions (unlike
        # gpd.list_layers, which isn't available in older geopandas releases).
        layer_names = fiona.listlayers(path)

        if not layer_names:
            result["valid"] = False
            result["errors"].append("GeoPackage contains no layers")
            return result

        # Read the first layer to confirm it actually loads and has geometry.
        gdf = gpd.read_file(path, layer=layer_names[0])

        if gdf.empty:
            result["valid"] = False
            result["errors"].append(f"Layer '{layer_names[0]}' has no features")

        if gdf.crs is None:
            result["valid"] = False
            result["errors"].append("GeoPackage layer has no CRS defined")

        invalid_geom_count = (~gdf.geometry.is_valid).sum() if not gdf.empty else 0
        if invalid_geom_count > 0:
            result["warnings"].append(
                f"{invalid_geom_count} invalid geometries found in layer '{layer_names[0]}'"
            )

        result["metadata"] = {
            "layers": layer_names,
            "primary_layer": layer_names[0],
            "feature_count": len(gdf),
            "crs": str(gdf.crs) if gdf.crs else None,
            "columns": list(gdf.columns),
            "bounds": list(gdf.total_bounds) if not gdf.empty else None,
        }

    except Exception as e:
        result["valid"] = False
        result["errors"].append(f"Could not open GeoPackage: {e}")

    return result


def validate_csv(path, required_columns=None):
    """Validate a CSV: file opens, is non-empty, and has the required columns
    (defaults to the FIRMS fire-archive schema)."""
    result = _base_result()
    required_columns = required_columns or REQUIRED_FIRE_CSV_COLUMNS

    if not os.path.exists(path):
        result["valid"] = False
        result["errors"].append(f"File not found: {path}")
        return result

    try:
        df = pd.read_csv(path)

        if df.empty:
            result["valid"] = False
            result["errors"].append("CSV has no rows")
            return result

        missing_cols = [c for c in required_columns if c not in df.columns]
        if missing_cols:
            result["valid"] = False
            result["errors"].append(f"Missing required columns: {missing_cols}")

        # Sanity-check lat/lon ranges if those columns exist.
        if "latitude" in df.columns:
            bad_lat = df[(df["latitude"] < -90) | (df["latitude"] > 90)]
            if not bad_lat.empty:
                result["warnings"].append(f"{len(bad_lat)} rows have out-of-range latitude")

        if "longitude" in df.columns:
            bad_lon = df[(df["longitude"] < -180) | (df["longitude"] > 180)]
            if not bad_lon.empty:
                result["warnings"].append(f"{len(bad_lon)} rows have out-of-range longitude")

        result["metadata"] = {
            "row_count": len(df),
            "columns": list(df.columns),
            "date_range": {
                "min": str(df["acq_date"].min()) if "acq_date" in df.columns else None,
                "max": str(df["acq_date"].max()) if "acq_date" in df.columns else None,
            },
        }

    except Exception as e:
        result["valid"] = False
        result["errors"].append(f"Could not read CSV: {e}")

    return result


VALIDATORS = {
    "raster": validate_raster,
    "gpkg": validate_gpkg,
    "csv": validate_csv,
}
