"""
Tests for Module 4 - Vegetation Loss Detection.
"""

import numpy as np
from app.loss_detection.threshold import apply_threshold
from app.loss_detection.config import LOSS_VALUE, NO_LOSS_VALUE, MASK_NODATA
from app.gee_processing.config import NDVI_NODATA


def test_apply_threshold_detects_loss():
    diff = np.array([-0.5, -0.2, -0.1, 0.0, 0.3])
    mask = apply_threshold(diff, threshold=-0.2)

    # -0.5 < -0.2 -> loss ; -0.2 is NOT < -0.2 -> no loss (boundary is exclusive)
    expected = [LOSS_VALUE, NO_LOSS_VALUE, NO_LOSS_VALUE, NO_LOSS_VALUE, NO_LOSS_VALUE]
    assert mask.tolist() == expected


def test_apply_threshold_preserves_nodata():
    diff = np.array([-0.5, NDVI_NODATA, 0.1])
    mask = apply_threshold(diff, threshold=-0.2)

    assert mask[0] == LOSS_VALUE
    assert mask[1] == MASK_NODATA
    assert mask[2] == NO_LOSS_VALUE


def test_apply_threshold_all_loss():
    diff = np.full((3, 3), -0.9)
    mask = apply_threshold(diff, threshold=-0.2)
    assert np.all(mask == LOSS_VALUE)


def test_apply_threshold_all_stable():
    diff = np.full((3, 3), 0.05)
    mask = apply_threshold(diff, threshold=-0.2)
    assert np.all(mask == NO_LOSS_VALUE)
