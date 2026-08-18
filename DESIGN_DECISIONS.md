# Design Decision: NDVI Source (Raw Sentinel-2 Imagery vs. Precomputed NDVI)

## Context

Your original dataset inventory included two things that could both serve
as the basis for "NDVI Calculation" (architecture Box 3):

1. `NDVI_2023.tif` / `NDVI_2025.tif` - already-computed NDVI rasters
2. `Forest_Sample_2023.tif` / `Forest_Sample_2025.tif` - raw Sentinel-2
   Level-2A multispectral imagery (26 bands: B1-B12/B8A spectral bands,
   AOT/WVP, SCL scene classification, TCI true-color, QA/mask bands),
   confirmed via Module 1's band-level inspection, not assumed from
   filenames.

## Decision

**Module 3 computes NDVI from scratch, using the raw `Forest_Sample`
imagery - not the precomputed `NDVI_2023/2025.tif` files.**

The pipeline's actual processing flow is:

```
Forest_Sample_<year>.tif (raw Sentinel-2 L2A, 26 bands)
    -> Module 3: extract SCL band -> build cloud mask
    -> Module 3: extract B8 (NIR) + B4 (Red) bands
    -> Module 3: apply cloud mask, compute NDVI = (NIR-RED)/(NIR+RED)
    -> Module 3: write ndvi_computed_<year>.tif
    -> Module 3: diff comparison_year - base_year -> ndvi_diff_<years>.tif
    -> Module 4 onward: everything downstream uses ndvi_diff_<years>.tif
```

The precomputed `NDVI_2023/2025.tif` files remain in Module 1's data
catalog (validated, checksummed, tagged with `role: processed_ndvi_output`)
as reference/cross-check data, but are **not read by any pipeline module**
from Module 3 onward.

## Why

Your architecture diagram's Box 3 explicitly lists four sub-steps: Cloud
Masking -> Image Preprocessing -> NDVI Calculation -> NDVI Difference
Analysis. The precomputed NDVI files are already a *finished product* of
some earlier, external process - using them directly would mean Module 3
does none of its own listed work; it would just be a pass-through. Computing
NDVI from the raw imagery means Module 3 actually performs cloud masking
and NDVI calculation as your own system, which is both more defensible in
a viva ("show me your cloud masking step" has a real, inspectable answer)
and more architecturally honest against the diagram as approved.

## Status

This was implemented as the default behavior when Module 3 was first
built, and flagged at the time as a reversible decision pending your
confirmation once you saw real output. That confirmation was never
explicitly given one way or the other; the project proceeded on this
default. Recorded here now so the final report describes one consistent,
correct processing flow rather than leaving it ambiguous.

If you want to switch to using the precomputed NDVI files instead, that
would mean: Module 3's `ndvi.py`/`pipeline.py` would read
`NDVI_2023/2025.tif` directly (skipping cloud-mask/NDVI-calculation code
entirely) and go straight to the diff step. This is a scoped, contained
change if you want it - but changes what Module 3 can honestly claim to
do relative to the architecture diagram.

---

# Other Architecture-Level Decisions (Audit Fixes)

Three additional changes were made following an architecture audit
(comparing the implementation against the approved diagram). Documented
here for the same reason - so the report describes the system as it
actually works, consistently.

## 1. Content-derived IDs (polygon_id, alert_id)

**Before:** `polygon_id` and `alert_id` were assigned by row position
(e.g. `loss_00042`, `ALERT-IN-00042`) at generation time.

**Problem:** positional IDs can silently change identity if the pipeline
is ever rerun and row ordering shifts - `ALERT-IN-00042` could point to a
different real-world location after a rerun than it did before, while old
evidence/blockchain records under that same ID remain on disk.

**After:** `polygon_id` is derived from a SHA-256 hash of the polygon's
centroid coordinates + year pair (`LOSS-<12 hex chars>`). `alert_id` is
derived from the polygon's `polygon_id` + branch (`ALERT-IN-<hash>` /
`ALERT-OUT-<hash>`). Same real-world location + same year comparison
always produces the same ID, regardless of processing order or how many
times the pipeline is rerun.

**Consequence:** this changed ID values for all previously-generated data.
Evidence and blockchain records keyed by the old positional IDs are
orphaned under the new scheme and were regenerated.

## 2. Separating "outside forest" from "unknown / no data coverage"

**Before:** Module 6 classified every polygon as either `inside_forest` or
"everything else" - which silently merged genuinely-classified
`outside_forest` polygons with `out_of_extent` polygons (locations with no
WorldCover data to classify at all) into the same NGO-awareness pathway.

**After:** three explicit buckets - `inside_forest`, `outside_forest`, and
`unknown_classification`. The third is written to its own GeoJSON file,
excluded from both alert pathways, and flagged in the Module 6 manifest as
requiring manual review, rather than being silently treated as a
confirmed "outside forest" result.

## 3. SQLite as the persistent system database

**Before:** the architecture's "Data Stores (System Database)" box was
implemented entirely as flat JSON/JSONL/GeoJSON files, scanned by
directory listing on every dashboard request. `db/eco_sentinel.db` and
`app/models/` existed in the scaffold but were never used, despite SQLite
being in the original tech stack.

**After:** `app/database/` (schema, sync, queries) loads alerts, evidence
records, and blockchain blocks into SQLite, indexed for fast lookups.
The original JSON/GeoJSON files remain the source of truth (unchanged,
still written by every pipeline module, kept for interoperability and
debugging) - the database is a synced, queryable copy built from them via
`python -m app.database.cli sync`. Both dashboards now query SQLite
instead of re-parsing the full JSON/GeoJSON files on every request.

One deliberate exception: blockchain **verification** (the actual
tamper-check) still re-hashes evidence files live from disk, not from the
database - caching a "last known valid" result in SQLite would defeat the
purpose of tamper detection.
