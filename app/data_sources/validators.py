
"""
Validators for each dataset type used in ECO-SENTINEL Module 1.

Each validator returns:
    {
        "valid": bool,
        "errors": [str, ...],
        "warnings": [str, ...],
        "metadata": {...}
    }
"""

import os
import traceback

import rasterio
import fiona
import geopandas as gpd
import pandas as pd

from app.data_sources.config import REQUIRED_FIRE_CSV_COLUMNS


def _base_result():
    return {
        "valid": True,
        "errors": [],
        "warnings": [],
        "metadata": {},
    }


def validate_raster(path):
    """Validate a GeoTIFF and collect its metadata."""
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
                "resolution": {
                    "x": src.res[0],
                    "y": src.res[1],
                },
                "dtype": src.dtypes[0] if src.count > 0 else None,
                "nodata": src.nodata,
            }

    except Exception as e:
        result["valid"] = False
        result["errors"].append(
            f"Could not open raster: {type(e).__name__}: {e}"
        )

    return result


def validate_gpkg(path):
    """
    Validate a GeoPackage by checking its layers, reading a layer,
    and collecting metadata.

    Geometry validity checks are warnings only. A geometry-operation
    error must not invalidate a readable GeoPackage.
    """
    result = _base_result()

    if not os.path.exists(path):
        result["valid"] = False
        result["errors"].append(f"File not found: {path}")
        return result

    try:
        layer_names = fiona.listlayers(path)

        if not layer_names:
            result["valid"] = False
            result["errors"].append("GeoPackage contains no layers")
            return result

        layer_name = layer_names[0]
        gdf = gpd.read_file(path, layer=layer_name)

        if gdf.empty:
            result["valid"] = False
            result["errors"].append(
                f"Layer '{layer_name}' has no features"
            )

        if gdf.crs is None:
            result["valid"] = False
            result["errors"].append(
                "GeoPackage layer has no CRS defined"
            )

        # Geometry validation is non-fatal.
        # Catch errors from Shapely/GEOS or incompatible geometry types.
        try:
            if not gdf.empty and gdf.geometry is not None:
                invalid_geom_count = int(
                    (~gdf.geometry.is_valid).sum()
                )

                if invalid_geom_count:
                    result["warnings"].append(
                        f"{invalid_geom_count} invalid geometries "
                        f"found in layer '{layer_name}'"
                    )

        except Exception as geom_error:
            result["warnings"].append(
                "Geometry validity check could not be completed: "
                f"{type(geom_error).__name__}: {geom_error}"
            )

        # Collect metadata separately so a bounds/geometry operation
        # failure does not erase successful layer-reading results.
        bounds = None
        try:
            if not gdf.empty:
                bounds = [
                    float(value) for value in gdf.total_bounds
                ]
        except Exception as bounds_error:
            result["warnings"].append(
                "Could not calculate layer bounds: "
                f"{type(bounds_error).__name__}: {bounds_error}"
            )

        result["metadata"] = {
            "layers": layer_names,
            "primary_layer": layer_name,
            "feature_count": len(gdf),
            "crs": str(gdf.crs) if gdf.crs else None,
            "columns": list(gdf.columns),
            "bounds": bounds,
        }

    except Exception as e:
        result["valid"] = False
        result["errors"].append(
            f"Could not open GeoPackage: "
            f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        )

    return result


def validate_csv(path, required_columns=None):
    """Validate a CSV and check its required columns."""
    result = _base_result()
    required_columns = (
        required_columns or REQUIRED_FIRE_CSV_COLUMNS
    )

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

        missing_cols = [
            column
            for column in required_columns
            if column not in df.columns
        ]

        if missing_cols:
            result["valid"] = False
            result["errors"].append(
                f"Missing required columns: {missing_cols}"
            )

        if "latitude" in df.columns:
            bad_lat = df[
                (df["latitude"] < -90)
                | (df["latitude"] > 90)
            ]
            if not bad_lat.empty:
                result["warnings"].append(
                    f"{len(bad_lat)} rows have out-of-range latitude"
                )

        if "longitude" in df.columns:
            bad_lon = df[
                (df["longitude"] < -180)
                | (df["longitude"] > 180)
            ]
            if not bad_lon.empty:
                result["warnings"].append(
                    f"{len(bad_lon)} rows have out-of-range longitude"
                )

        result["metadata"] = {
            "row_count": len(df),
            "columns": list(df.columns),
            "date_range": {
                "min": (
                    str(df["acq_date"].min())
                    if "acq_date" in df.columns
                    else None
                ),
                "max": (
                    str(df["acq_date"].max())
                    if "acq_date" in df.columns
                    else None
                ),
            },
        }

    except Exception as e:
        result["valid"] = False
        result["errors"].append(
            f"Could not read CSV: {type(e).__name__}: {e}"
        )

    return result


VALIDATORS = {
    "raster": validate_raster,
    "gpkg": validate_gpkg,
    "csv": validate_csv,
}
