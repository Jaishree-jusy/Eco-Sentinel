"""
Configuration for Module 8 - Evidence Generation.
"""

from app.config import EVIDENCE_STORE_DIR

# TCI band indices in the raw Forest_Sample rasters (confirmed via Module 1's inspection)
TCI_R_BAND = 16
TCI_G_BAND = 17
TCI_B_BAND = 18

# Minimum map snapshot size, in pixels, along each axis. Small polygons get
# their buffer expanded so the snapshot always shows meaningful context
# rather than a near-empty crop.
MIN_SNAPSHOT_PIXELS = 60

# Base buffer around the polygon bounding box, in degrees, before the
# minimum-size adjustment above is applied.
BASE_BUFFER_DEG = 0.0005
