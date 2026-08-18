"""
Configuration for Module 6 - Forest Boundary Check.
"""

from app.config import DATA_DIR
import os

BOUNDARY_CHECK_DIR = os.path.join(DATA_DIR, "boundary_check")

# ESA WorldCover 2021 standard class code for "Tree cover".
# (Full scheme: 10=Tree cover, 20=Shrubland, 30=Grassland, 40=Cropland,
# 50=Built-up, 60=Bare/sparse veg, 70=Snow/ice, 80=Water, 90=Wetland,
# 95=Mangroves, 100=Moss/lichen.)
FOREST_CLASS_VALUE = 10

# GADM layer used to assign a Region/Division label to each alert.
# ADM_ADM_2 = district level (finer than state, coarser than sub-district).
GADM_REGION_LAYER = "ADM_ADM_2"

# Column name candidates to try, in order, for the region/division label -
# GADM schema varies slightly by version/country, so we check what's
# actually present rather than assuming one fixed name.
GADM_REGION_COLUMN_CANDIDATES = ["NAME_2", "NAME_1", "COUNTRY"]

# --- Module 6B: Legality / Authorization ---
# No real permit/authorization dataset exists in this project. This stays
# None until you explicitly supply one - do not point this at a fabricated
# file. When None, every polygon's legality_status is "legal_status_unknown".
AUTHORIZATION_DATASET_PATH = None
