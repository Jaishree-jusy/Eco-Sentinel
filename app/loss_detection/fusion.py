"""
Fusion - combines Module 4 (NDVI threshold) with Module 4B (AI anomaly
score) into a single detection_class per pixel, per the approved table:

    NDVI=true,  AI=true   -> high_confidence_loss
    NDVI=true,  AI=false  -> vegetation_loss       (baseline behavior, unchanged)
    NDVI=false, AI=true   -> potential_disturbance
    neither                -> no_detection

Module 4's own output/behavior is completely unchanged by this - this
reads both existing outputs and produces a new, separate classification.
"""

import numpy as np

from app.loss_detection.config import LOSS_VALUE as NDVI_LOSS_VALUE
from app.loss_detection.ai_disturbance import ANOMALY_NODATA

ANOMALY_SCORE_THRESHOLD = 0.5  # score > this counts as an AI-flagged pixel

DETECTION_CLASS_HIGH_CONFIDENCE = "high_confidence_loss"
DETECTION_CLASS_VEGETATION_LOSS = "vegetation_loss"
DETECTION_CLASS_POTENTIAL_DISTURBANCE = "potential_disturbance"
DETECTION_CLASS_NONE = "no_detection"

_CLASS_CODES = {
    DETECTION_CLASS_NONE: 0,
    DETECTION_CLASS_VEGETATION_LOSS: 1,
    DETECTION_CLASS_POTENTIAL_DISTURBANCE: 2,
    DETECTION_CLASS_HIGH_CONFIDENCE: 3,
}
CLASS_CODES = _CLASS_CODES
CODE_TO_CLASS = {v: k for k, v in _CLASS_CODES.items()}


def fuse_arrays(ndvi_mask, anomaly_score, anomaly_score_threshold=ANOMALY_SCORE_THRESHOLD):
    """ndvi_mask: Module 4's output array (LOSS_VALUE where flagged).
    anomaly_score: Module 4B's output array (ANOMALY_NODATA where invalid).
    Returns an integer array of class codes (see CLASS_CODES)."""
    ndvi_flag = (ndvi_mask == NDVI_LOSS_VALUE)
    ai_flag = (anomaly_score != ANOMALY_NODATA) & (anomaly_score > anomaly_score_threshold)

    result = np.full(ndvi_mask.shape, _CLASS_CODES[DETECTION_CLASS_NONE], dtype="uint8")
    result[ndvi_flag & ~ai_flag] = _CLASS_CODES[DETECTION_CLASS_VEGETATION_LOSS]
    result[~ndvi_flag & ai_flag] = _CLASS_CODES[DETECTION_CLASS_POTENTIAL_DISTURBANCE]
    result[ndvi_flag & ai_flag] = _CLASS_CODES[DETECTION_CLASS_HIGH_CONFIDENCE]
    return result


def classify_polygon_detection(mean_anomaly_score, is_ndvi_loss, anomaly_score_threshold=ANOMALY_SCORE_THRESHOLD):
    """Per-polygon version, used by Module 5 once a polygon's mean anomaly
    score has been sampled (mirrors how severity is already computed)."""
    ai_flag = mean_anomaly_score is not None and mean_anomaly_score > anomaly_score_threshold
    if is_ndvi_loss and ai_flag:
        return DETECTION_CLASS_HIGH_CONFIDENCE
    if is_ndvi_loss and not ai_flag:
        return DETECTION_CLASS_VEGETATION_LOSS
    if not is_ndvi_loss and ai_flag:
        return DETECTION_CLASS_POTENTIAL_DISTURBANCE
    return DETECTION_CLASS_NONE
