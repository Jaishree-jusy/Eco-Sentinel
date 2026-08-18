"""
Tests for fusion.py - verifies the exact approved fusion table.
"""

import numpy as np
from app.loss_detection.fusion import (
    fuse_arrays, classify_polygon_detection, CODE_TO_CLASS,
    DETECTION_CLASS_HIGH_CONFIDENCE, DETECTION_CLASS_VEGETATION_LOSS,
    DETECTION_CLASS_POTENTIAL_DISTURBANCE, DETECTION_CLASS_NONE,
)
from app.loss_detection.config import LOSS_VALUE, NO_LOSS_VALUE
from app.loss_detection.ai_disturbance import ANOMALY_NODATA


def test_fuse_arrays_exact_table():
    ndvi_mask = np.array([LOSS_VALUE, LOSS_VALUE, NO_LOSS_VALUE, NO_LOSS_VALUE])
    anomaly_score = np.array([0.8, 0.2, 0.8, 0.2])  # threshold is 0.5

    result = fuse_arrays(ndvi_mask, anomaly_score)
    classes = [CODE_TO_CLASS[c] for c in result]

    assert classes == [
        DETECTION_CLASS_HIGH_CONFIDENCE,
        DETECTION_CLASS_VEGETATION_LOSS,
        DETECTION_CLASS_POTENTIAL_DISTURBANCE,
        DETECTION_CLASS_NONE,
    ]


def test_fuse_arrays_treats_anomaly_nodata_as_not_flagged():
    ndvi_mask = np.array([LOSS_VALUE])
    anomaly_score = np.array([ANOMALY_NODATA])
    result = fuse_arrays(ndvi_mask, anomaly_score)
    assert CODE_TO_CLASS[result[0]] == DETECTION_CLASS_VEGETATION_LOSS


def test_classify_polygon_detection_matches_array_version():
    assert classify_polygon_detection(0.8, True) == DETECTION_CLASS_HIGH_CONFIDENCE
    assert classify_polygon_detection(0.2, True) == DETECTION_CLASS_VEGETATION_LOSS
    assert classify_polygon_detection(0.8, False) == DETECTION_CLASS_POTENTIAL_DISTURBANCE
    assert classify_polygon_detection(0.2, False) == DETECTION_CLASS_NONE
    assert classify_polygon_detection(None, False) == DETECTION_CLASS_NONE
