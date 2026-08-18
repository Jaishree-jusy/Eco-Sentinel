"""
Configuration for Module 5 - Polygon Generation & Analysis.
"""

# Your AOI (lon ~74.75-75.10, lat ~12.6-13.0) falls in UTM Zone 43N.
# Used only for accurate area calculation - final output geometries are
# reported back in EPSG:4326 to stay consistent with GADM (Module 6 input).
AREA_CALC_CRS = "EPSG:32643"

# Raster-to-polygon conversion always produces single/few-pixel noise
# specks. Polygons smaller than this are dropped. Tune if needed -
# ~10 pixels at this dataset's resolution (~10m).
MIN_POLYGON_AREA_HA = 0.1

# Severity classification bins, based on mean NDVI diff within each polygon.
# Diff is negative for loss; more negative = more severe.
SEVERITY_BINS = [
    ("severe", float("-inf"), -0.50),
    ("moderate", -0.50, -0.35),
    ("mild", -0.35, -0.20),
]
