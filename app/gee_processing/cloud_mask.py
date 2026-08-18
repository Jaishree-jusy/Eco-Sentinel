"""
Cloud masking - Module 3, step 1.

Builds a boolean mask from the Scene Classification Layer (SCL) band and
applies it to any array (NIR, RED, or the final NDVI result).
"""

import numpy as np
from app.gee_processing.config import CLOUD_SCL_CODES


def build_cloud_mask(scl_array):
    """Returns a boolean array where True = cloud-affected pixel (to be masked out)."""
    mask = np.isin(scl_array, list(CLOUD_SCL_CODES))
    return mask


def apply_mask(array, mask, nodata_value):
    """Sets masked-out pixels to nodata_value. Returns a new array (does not mutate input)."""
    result = array.copy().astype("float32")
    result[mask] = nodata_value
    return result
