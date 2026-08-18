"""
Thresholding - Module 4 core logic.

Converts a continuous NDVI-diff raster into a binary vegetation-loss mask.
"""

import numpy as np
from app.loss_detection.config import THRESHOLD, LOSS_VALUE, NO_LOSS_VALUE, MASK_NODATA
from app.gee_processing.config import NDVI_NODATA


def apply_threshold(diff_array, threshold=THRESHOLD):
    """Returns a uint8 mask: LOSS_VALUE where diff < threshold (and valid),
    NO_LOSS_VALUE where diff >= threshold (and valid), MASK_NODATA where
    the source diff pixel was nodata."""
    invalid = (diff_array == NDVI_NODATA)

    mask = np.where(diff_array < threshold, LOSS_VALUE, NO_LOSS_VALUE).astype("uint8")
    mask[invalid] = MASK_NODATA

    return mask
