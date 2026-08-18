"""
Configuration for Module 7 / 7A - Alert Generation.
"""

# ESA WorldCover class -> Area Type mapping, used only for OUTSIDE-forest
# alerts (Box 7A's "Region / Area Type" field). This is a reasonable,
# data-grounded interpretation of "Urban/Rural/Others" - not a dataset we
# have labeled that way directly, so flagged here for visibility.
AREA_TYPE_MAPPING = {
    50: "Urban",       # Built-up
    20: "Rural",       # Shrubland
    30: "Rural",       # Grassland
    40: "Rural",       # Cropland
}
DEFAULT_AREA_TYPE = "Others"  # bare soil, water, wetland, snow, etc.

ALERT_ID_PREFIX_INSIDE = "ALERT-IN"
ALERT_ID_PREFIX_OUTSIDE = "ALERT-OUT"
