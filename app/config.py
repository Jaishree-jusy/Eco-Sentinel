"""
Central configuration for ECO-SENTINEL.

Every module reads paths from here instead of hardcoding strings,
so if we ever move the data/ or db/ folders, only this file changes.
"""

import os

# Project root = the eco-sentinel/ folder (two levels up from this file)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- Data Sources (Module 1) ---
DATA_DIR = os.path.join(BASE_DIR, "data")
RAW_IMAGES_DIR = os.path.join(DATA_DIR, "raw_images")
NDVI_RAW_DIR = os.path.join(RAW_IMAGES_DIR, "ndvi")
LANDCOVER_DIR = os.path.join(RAW_IMAGES_DIR, "landcover")
FOREST_SAMPLES_DIR = os.path.join(RAW_IMAGES_DIR, "forest_samples")
BOUNDARIES_DIR = os.path.join(RAW_IMAGES_DIR, "boundaries")
FIRE_ARCHIVE_DIR = os.path.join(RAW_IMAGES_DIR, "fire_archive")

# --- Processed data (Module 3 onward) ---
NDVI_PROCESSED_DIR = os.path.join(DATA_DIR, "ndvi_processed")
EVIDENCE_STORE_DIR = os.path.join(DATA_DIR, "evidence_store")
POLYGON_ANALYSIS_DIR = os.path.join(DATA_DIR, "polygon_analysis")
ALERTS_DIR = os.path.join(DATA_DIR, "alerts")
BLOCKCHAIN_DIR = os.path.join(DATA_DIR, "blockchain")

# --- Database (Data Stores box) ---
DB_DIR = os.path.join(BASE_DIR, "db")
DB_PATH = os.path.join(DB_DIR, "eco_sentinel.db")

# --- Data catalog output (Module 1) ---
DATA_CATALOG_PATH = os.path.join(DATA_DIR, "data_catalog.json")
