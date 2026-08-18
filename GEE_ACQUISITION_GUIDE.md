# ECO-SENTINEL — Live Acquisition & Automated Pipeline Guide

## 1. Earth Engine Authentication (one-time, on your Windows machine)

This project never stores, requests, or reads Earth Engine credentials
itself. It relies entirely on the standard local `earthengine-api`
authentication flow.

**Steps:**

1. Make sure you have a Google account registered for Earth Engine access
   (sign up at https://earthengine.google.com if you haven't already — this
   requires approval from Google, which can take anywhere from minutes to
   a few days for a new account).
2. In PowerShell, with your project's virtual environment activated:
   ```powershell
   earthengine authenticate
   ```
3. This opens a browser window. Sign in with your Earth-Engine-enabled
   Google account and approve access.
4. A token is stored under your Windows user profile
   (`%APPDATA%\earthengine\credentials` or similar, managed entirely by
   the `earthengine-api` package — not by this project).
5. You only need to do this once per machine. After this, `ee.Initialize()`
   (called internally by this project) picks up the stored token
   automatically — no credentials are ever read from or written to this
   repository.

**To verify authentication worked**, run:
```powershell
python -c "import ee; ee.Initialize(); print('Earth Engine authenticated OK')"
```
If this prints the success message, you're ready. If it raises an error,
re-run `earthengine authenticate`.

## 2. Configuration

All acquisition configuration lives in `app/acquisition/config.py`:

| Setting | Where | Default |
|---|---|---|
| AOI (region bounding box) | `REGIONS["region_1"]["bbox"]` | Your existing confirmed AOI |
| Cloud cover threshold | `GEE_CLOUD_COVER_THRESHOLD` | 20% |
| Base (baseline) year | `DEFAULT_YEAR_PAIR["base_year"]` | 2023 (stays local/historical) |
| Comparison year | `DEFAULT_YEAR_PAIR["comparison_year"]` | 2025 (live-acquired going forward) |
| Bands downloaded | `app/acquisition/gee_client.py` -> `BAND_SET` | Only what the pipeline actually uses |

## 3. Commands

```powershell
# Acquisition only (Module 2), live GEE by default
python -m app.acquisition.cli run

# Acquisition using local historical files instead (offline/testing fallback)
python -m app.acquisition.cli run --no-live-gee

# The FULL pipeline: acquisition through dashboards, one command
python -m app.acquisition.cli trigger

# Full pipeline, but only generate evidence for 5 alerts (quick test)
python -m app.acquisition.cli trigger --evidence-limit 5

# Register the monthly scheduled job (does not fire immediately)
python -m app.acquisition.cli start-scheduler
```

## 4. How duplicate-download prevention works

Every real GEE image has a unique ID (e.g.
`COPERNICUS/S2_SR_HARMONIZED/20250115T053...`). Before downloading
anything, the system checks `data/acquisition_runs/gee_image_registry.json`
- if that exact image was already downloaded and the local file still
exists, it's reused, nothing is re-downloaded, and the manifest is marked
`status: "no_new_data"`. The orchestrator sees this status and stops
immediately - Modules 3 through 9 are never rerun, and your existing
results are left untouched.

## 5. How a pipeline run is tracked

Every `trigger` run gets one row in the new `pipeline_runs` SQLite table,
recording start/finish time, trigger mode, overall status, and - if it
failed - exactly which stage failed and why. Each stage's own run ID
(acquisition, gee_processing, loss_detection, ai_disturbance,
polygon_analysis, boundary_check, legality_check, alert_generation,
evidence_generation, blockchain) is recorded too, so you can trace a
failure to the exact manifest file for that stage.

## 6. What happens when a stage fails

The run stops immediately at that stage. No later stage runs. Your
previous valid results (existing alerts, evidence, blockchain records)
are never touched or deleted by a failed run - only a fully successful
run's own new data gets written.

## 7. Earth Engine limitations and quota considerations

- Earth Engine has usage quotas per Google account (compute time, request
  rate). A single small-AOI image download is normally well within free-tier
  limits, but repeated large exports can hit quota - if you see quota
  errors, wait or check your Earth Engine usage dashboard.
- `getDownloadURL()` (used here) works well for small-to-moderate AOIs.
  For very large regions, Earth Engine may require `Export.image.toDrive()`
  with asynchronous task polling instead - not implemented here, since your
  AOI is small enough for direct download.
- Sentinel-2 revisit time is ~5 days, but usable (low-cloud) imagery for a
  specific small AOI may not appear every revisit - the cloud-cover filter
  can legitimately return "no imagery found" for some date windows.

## 8. Adding a real legality/authorization dataset

Currently `AUTHORIZATION_DATASET_PATH` in `app/boundary_check/config.py` is
`None`, and every alert's legality status is honestly `legal_status_unknown`.
To activate real legality checking, supply a GeoPackage matching the schema
documented in `app/boundary_check/legality.py`
(`REQUIRED_AUTHORIZATION_COLUMNS`) and point `AUTHORIZATION_DATASET_PATH`
at it. No such dataset is included with this project - it must come from
real Forest Department / Revenue Department records.
