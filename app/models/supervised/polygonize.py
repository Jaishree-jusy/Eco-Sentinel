"""
Fast polygonization of supervised deforestation predictions.

Converts the binary prediction raster into connected deforestation
polygons using rasterio.features.shapes instead of scanning every
pixel with np.where().
"""

import os
import json
from datetime import datetime, timezone

import numpy as np
import rasterio
from rasterio.features import shapes
from shapely.geometry import shape, mapping
from pyproj import Geod


GEOD = Geod(ellps="WGS84")


def _area_ha(geom):
    """Calculate geodesic polygon area in hectares."""
    if geom.is_empty:
        return 0.0

    if geom.geom_type == "Polygon":
        area, _ = GEOD.geometry_area_perimeter(geom)
        return abs(area) / 10000.0

    if geom.geom_type == "MultiPolygon":
        return sum(_area_ha(part) for part in geom.geoms)

    return 0.0


def polygonize_supervised_prediction(
    prediction_raster_path,
    probability_raster_path,
    output_geojson_path,
    min_probability=0.50,
    min_area_ha=0.01,
):
    """
    Convert supervised deforestation predictions into polygons.

    prediction raster:
        1 = deforestation
        0 = no deforestation
        255 = nodata

    probability raster:
        Random Forest probability of deforestation [0, 1].
    """

    os.makedirs(
        os.path.dirname(os.path.abspath(output_geojson_path)),
        exist_ok=True,
    )

    with rasterio.open(prediction_raster_path) as pred_src:

        prediction = pred_src.read(1)
        transform = pred_src.transform
        crs = pred_src.crs

        # ---------------------------------------------------------
        # Build a simple binary mask.
        # No np.where() and no per-pixel geometry creation.
        # ---------------------------------------------------------

        mask = prediction == 1

        if not np.any(mask):
            result = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "prediction_raster": prediction_raster_path,
                "probability_raster": probability_raster_path,
                "min_probability": min_probability,
                "polygon_count": 0,
                "total_deforestation_area_ha": 0.0,
                "output_geojson": output_geojson_path,
            }

            with open(output_geojson_path, "w") as f:
                json.dump(
                    {
                        "type": "FeatureCollection",
                        "features": [],
                    },
                    f,
                    indent=2,
                )

            return result

        # ---------------------------------------------------------
        # Polygonize connected regions directly.
        # ---------------------------------------------------------

        polygon_features = []

        for geom_json, value in shapes(
            prediction.astype("uint8"),
            mask=mask,
            transform=transform,
        ):

            if value != 1:
                continue

            geom = shape(geom_json)

            if geom.is_empty:
                continue

            area_ha = _area_ha(geom)

            if area_ha < min_area_ha:
                continue

            polygon_features.append(
                {
                    "geometry": mapping(geom),
                    "area_ha": area_ha,
                }
            )

        # ---------------------------------------------------------
        # Read probabilities only for retained polygons.
        # ---------------------------------------------------------

        probability_values = []

        with rasterio.open(probability_raster_path) as prob_src:

            for item in polygon_features:

                geom = shape(item["geometry"])

                try:
                    from rasterio.mask import mask as raster_mask

                    data, _ = raster_mask(
                        prob_src,
                        [geom],
                        crop=True,
                        filled=False,
                    )

                    values = data[0]

                    if np.ma.isMaskedArray(values):
                        values = values.compressed()

                    values = np.asarray(values)

                    values = values[
                        np.isfinite(values)
                    ]

                    if values.size:
                        mean_probability = float(
                            np.mean(values)
                        )
                    else:
                        mean_probability = 0.0

                except Exception:
                    mean_probability = 0.0

                probability_values.append(
                    mean_probability
                )

        # ---------------------------------------------------------
        # Apply probability threshold.
        # ---------------------------------------------------------

        final_features = []

        for index, item in enumerate(polygon_features):

            probability = probability_values[index]

            if probability < min_probability:
                continue

            geom = shape(item["geometry"])

            final_features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(geom),
                    "properties": {
                        "prediction": "deforestation",
                        "deforestation_probability": round(
                            probability,
                            4,
                        ),
                        "area_ha": round(
                            item["area_ha"],
                            4,
                        ),
                    },
                }
            )

        # ---------------------------------------------------------
        # Write GeoJSON.
        # ---------------------------------------------------------

        geojson = {
            "type": "FeatureCollection",
            "features": final_features,
        }

        with open(output_geojson_path, "w") as f:
            json.dump(
                geojson,
                f,
                indent=2,
            )

        total_area = sum(
            feature["properties"]["area_ha"]
            for feature in final_features
        )

        result = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "prediction_raster": prediction_raster_path,
            "probability_raster": probability_raster_path,
            "min_probability": min_probability,
            "min_area_ha": min_area_ha,
            "polygon_count": len(final_features),
            "total_deforestation_area_ha": round(
                total_area,
                4,
            ),
            "output_geojson": output_geojson_path,
        }

        return result