"""
Configuration for Module 4 - Vegetation Loss Detection.

THRESHOLD: a pixel is classified as vegetation loss if
    ndvi_diff (comparison_year - base_year) < THRESHOLD

-0.2 is a standard, commonly-cited default in NDVI change-detection
literature - conservative enough to avoid flagging normal seasonal
NDVI fluctuation as loss, sensitive enough to catch real clearing events.

To tune: change THRESHOLD here. Nothing else in this module needs to change.
"""

from app.config import DATA_DIR
import os

THRESHOLD = -0.2

LOSS_MASK_DIR = os.path.join(DATA_DIR, "ndvi_processed")  # masks live alongside the diff raster

# Mask raster values
LOSS_VALUE = 1
NO_LOSS_VALUE = 0
MASK_NODATA = 255
