# ECO-SENTINEL

AI-Based Vegetation Loss Detection & Classification with Alerting System.

Built module-by-module, matching the approved system architecture exactly.
See each `app/<module>/` folder for that module's code as it's built.

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Module 1 - Data Sources & Ingestion

Place your real datasets in the following locations before running validation:

```
data/raw_images/ndvi/NDVI_2023.tif
data/raw_images/ndvi/NDVI_2025.tif
data/raw_images/landcover/ESA_WorldCover_2021.tif
data/raw_images/forest_samples/Forest_Sample_2023.tif
data/raw_images/forest_samples/Forest_Sample_2025.tif
data/raw_images/boundaries/gadm41_IND.gpkg
data/raw_images/fire_archive/fire_archive_SV-C2_778067.csv
data/raw_images/fire_archive/fire_archive_SV-C2_778068.csv
```

Then run:

```bash
python -m app.data_sources.cli validate
```

This validates every file (raster integrity, CRS, geometry validity, required
CSV columns) and writes `data/data_catalog.json` - the manifest that Module 2
onward will read instead of touching raw files directly.

### Run tests

```bash
pytest tests/test_data_sources.py -v
```

## Project status

- [x] Module 1 - Data Sources & Ingestion
- [ ] Module 2 - Data Acquisition & Scheduler
- [ ] Module 3 - Google Earth Engine Processing
- [ ] Module 4 - Vegetation Loss Detection
- [ ] Module 5 - Polygon Generation & Analysis
- [ ] Module 6 - Forest Boundary Check
- [ ] Module 7 - Alert Generation (Inside Forest)
- [ ] Module 7A - Alert Generation (Outside Forest)
- [ ] Module 8 - Evidence Generation
- [ ] Module 9 - Blockchain Integrity Layer
- [ ] Module 10 - Government Dashboard
- [ ] Module 7B - NGO Dashboard
