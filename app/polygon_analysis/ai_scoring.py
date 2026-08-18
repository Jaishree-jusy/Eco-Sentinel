"""
Per-polygon AI disturbance sampling - Module 5 extension.

Mirrors severity.py's pattern exactly: samples the AI anomaly-score raster
(Module 4B's output) within each polygon's geometry, producing a mean
score used for the NDVI+AI fusion classification.
"""

import numpy as np
import rasterio
import rasterio.mask

from app.loss_detection.ai_disturbance import ANOMALY_NODATA
from app.loss_detection.fusion import classify_polygon_detection


def estimate_ai_disturbance(gdf, anomaly_raster_path):
    """Adds 'mean_anomaly_score' and 'detection_class' columns. Every
    polygon here is already an NDVI-loss polygon (Module 5 vectorizes
    from Module 4's mask), so detection_class only distinguishes
    'vegetation_loss' (AI disagrees/unavailable) from 'high_confidence_loss'
    (AI agrees) - it never produces 'potential_disturbance' here, since
    that category requires areas NDVI didn't flag at all, which aren't in
    this polygon set by construction."""
    if gdf.empty:
        gdf["mean_anomaly_score"] = []
        gdf["detection_class"] = []
        return gdf

    gdf = gdf.copy()
    mean_scores = []

    with rasterio.open(anomaly_raster_path) as src:
        for geom in gdf.geometry:
            try:
                out_image, _ = rasterio.mask.mask(src, [geom], crop=True, nodata=ANOMALY_NODATA)
                data = out_image[0]
                valid = data[data != ANOMALY_NODATA]
                mean_scores.append(float(np.mean(valid)) if valid.size else None)
            except ValueError:
                mean_scores.append(None)

    gdf["mean_anomaly_score"] = mean_scores
    gdf["detection_class"] = [classify_polygon_detection(s, is_ndvi_loss=True) for s in mean_scores]
    return gdf


def default_detection_class_no_ai(gdf):
    """Used when Module 4B hasn't been run - every polygon is classified
    purely on the existing NDVI baseline, exactly matching prior behavior
    (no AI = no change to how this project already worked)."""
    if gdf.empty:
        gdf["mean_anomaly_score"] = []
        gdf["detection_class"] = []
        return gdf

    gdf = gdf.copy()
    gdf["mean_anomaly_score"] = None
    gdf["detection_class"] = "vegetation_loss"
    return gdf
