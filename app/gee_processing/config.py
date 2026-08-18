"""
Configuration for Module 3 - GEE Processing.

Band indices below are confirmed from the actual band descriptions found in
Forest_Sample_2023.tif / Forest_Sample_2025.tif via Module 1's inspection
tool (both years share identical band order) - not assumed.
"""

from app.config import NDVI_PROCESSED_DIR

BAND_INDEX = {
    "B1": 1, "B2": 2, "B3": 3, "B4": 4, "B5": 5, "B6": 6, "B7": 7,
    "B8": 8, "B8A": 9, "B9": 10, "B11": 11, "B12": 12,
    "AOT": 13, "WVP": 14, "SCL": 15,
    "TCI_R": 16, "TCI_G": 17, "TCI_B": 18,
    "MSK_CLDPRB": 19, "MSK_SNWPRB": 20,
    "QA10": 21, "QA20": 22, "QA60": 23,
    "MSK_CLASSI_OPAQUE": 24, "MSK_CLASSI_CIRRUS": 25, "MSK_CLASSI_SNOW_ICE": 26,
}

NIR_BAND = "B8"
RED_BAND = "B4"
SCL_BAND = "SCL"

# Sentinel-2 L2A Scene Classification Layer codes considered "cloud" for
# masking purposes: 0=no data, 1=saturated/defective, 3=cloud shadow,
# 8=cloud medium probability, 9=cloud high probability, 10=thin cirrus.
# (Vegetation=4, bare soil=5, water=6, dark area=2, unclassified=7, and
# snow=11 are NOT masked here - masking those would be scope creep beyond
# "Cloud Masking" as named in the architecture.)
CLOUD_SCL_CODES = {0, 1, 3, 8, 9, 10}

NDVI_NODATA = -9999.0
