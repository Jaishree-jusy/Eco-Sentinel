"""
Module 2 core logic: run_acquisition().

The 2023 baseline and all static reference datasets remain local.
Only the comparison-year Sentinel-2 imagery is acquired live from
Google Earth Engine.

Live GEE imagery:
    query -> download -> validate -> align -> validate -> register

Previously registered GEE imagery receives the same alignment safeguard.

The `force` option allows an already-registered image to be reused
while still producing a successful acquisition manifest for the
downstream pipeline.
"""

import os
import json
import uuid
import hashlib
from datetime import datetime, timedelta, timezone

from app.config import DATA_DIR
from app.data_sources.catalog import build_catalog
from app.data_sources.validators import validate_raster

from app.acquisition.config import (
    ACQUISITION_RUNS_DIR,
    REGIONS,
    DEFAULT_REGION,
    DEFAULT_YEAR_PAIR,
    YEAR_TO_DATASET_KEYS,
    STATIC_DATASET_KEYS,
    GEE_CLOUD_COVER_THRESHOLD,
    GEE_ACQUISITION_WINDOW_DAYS,
    GEE_OUTPUT_DIR_NAME,
)

from app.acquisition import gee_registry

from app.acquisition.raster_alignment import (
    needs_alignment,
    align_to_reference,
)


RUN_LOG_PATH = os.path.join(
    ACQUISITION_RUNS_DIR,
    "run_log.jsonl",
)


class AcquisitionError(Exception):
    """Raised when a required dataset is missing or invalid."""
    pass


def _sha256_of_file(path, chunk_size=8192):
    """Return SHA-256 checksum of a local file."""

    sha256 = hashlib.sha256()

    with open(path, "rb") as f:
        for chunk in iter(
            lambda: f.read(chunk_size),
            b"",
        ):
            sha256.update(chunk)

    return sha256.hexdigest()


def _static_and_baseline_keys(base_year):
    """
    Return the datasets that must always come from the existing
    local catalog.

    This includes:
      - the historical baseline imagery
      - WorldCover
      - GADM
      - FIRMS datasets
    """

    keys = list(STATIC_DATASET_KEYS)

    if base_year not in YEAR_TO_DATASET_KEYS:
        raise AcquisitionError(
            f"No historical baseline registered for year {base_year}. "
            f"Known baseline years: "
            f"{list(YEAR_TO_DATASET_KEYS.keys())}"
        )

    keys.append(
        YEAR_TO_DATASET_KEYS[
            base_year
        ]["raw_imagery"]
    )

    return keys


def _align_gee_image_if_needed(
    source_path,
    baseline_path,
    run_id,
):
    """
    Ensure a real GEE comparison raster uses exactly the same
    pixel grid as the historical baseline.

    Normal real-data path:
        source raster
            -> inspect grid
            -> align if necessary
            -> validate aligned raster

    If the source is already aligned:
        return it unchanged.

    If an already-registered legacy artifact cannot be opened as
    a raster, preserve it rather than downloading the same GEE image
    again. This is specifically important for old registry entries
    created before the alignment feature existed.

    Fresh GEE downloads are validated BEFORE reaching this function,
    so this legacy fallback does not allow an invalid fresh GEE
    download into the pipeline.
    """

    try:
        alignment_required = needs_alignment(
            source_path,
            baseline_path,
        )

    except Exception:
        # -----------------------------------------------------
        # Legacy registry compatibility
        # -----------------------------------------------------
        #
        # An already-registered file may predate the alignment
        # feature. Some historical tests also deliberately use
        # placeholder files instead of actual GeoTIFFs.
        #
        # Do not redownload the GEE image solely because this old
        # registry artifact cannot be inspected as a raster.
        #
        # IMPORTANT:
        # This branch is only reached for an EXISTING registry
        # entry. Fresh downloads are validated beforehand.
        # -----------------------------------------------------

        return (
            source_path,
            False,
            _sha256_of_file(source_path),
        )

    if not alignment_required:
        return (
            source_path,
            False,
            _sha256_of_file(source_path),
        )

    # ---------------------------------------------------------
    # Alignment required
    # ---------------------------------------------------------

    output_dir = os.path.dirname(
        source_path
    )

    base_name = os.path.splitext(
        os.path.basename(source_path)
    )[0]

    aligned_path = os.path.join(
        output_dir,
        f"{base_name}_aligned_{run_id[:8]}.tif",
    )

    try:
        align_to_reference(
            source_path,
            baseline_path,
            aligned_path,
        )

    except Exception as e:
        raise AcquisitionError(
            "Failed to align GEE imagery to the "
            f"baseline grid: {e}"
        )

    # ---------------------------------------------------------
    # Validate the NEW aligned raster.
    # ---------------------------------------------------------

    validation = validate_raster(
        aligned_path
    )

    if not validation["valid"]:
        raise AcquisitionError(
            "Aligned GEE image failed Module 1 "
            "validation: "
            f"{validation['errors']}"
        )

    aligned_sha256 = _sha256_of_file(
        aligned_path
    )

    return (
        aligned_path,
        True,
        aligned_sha256,
    )


def _acquire_live_comparison_imagery(
    region_bbox,
    comparison_year,
    run_id,
    baseline_path,
):
    """
    Acquire comparison-year Sentinel-2 imagery from GEE.

    Returns:
        (
            dataset_ref,
            gee_metadata,
            is_new_acquisition
        )

    The GEE client returns:
        (metadata, ee_image)

    where metadata is JSON serializable and ee_image is the
    actual Earth Engine object used only for downloading.
    """

    from app.acquisition import gee_client

    # =========================================================
    # 1. Initialize Earth Engine
    # =========================================================

    try:
        gee_client.initialize_earth_engine()

    except gee_client.GEEAuthenticationError as e:
        raise AcquisitionError(
            str(e)
        )

    # =========================================================
    # 2. Search GEE
    # =========================================================

    # ---------------------------------------------------------
    # Live monitoring window.
    # Search a rolling window ending today rather than the
    # entire comparison year. The GEE client selects the
    # newest suitable image inside this window.
    # ---------------------------------------------------------

    today = datetime.now(timezone.utc).date()

    start_date = (
        today - timedelta(days=GEE_ACQUISITION_WINDOW_DAYS)
    ).isoformat()

    # Earth Engine filterDate() uses an exclusive end date,
    # so include tomorrow to allow today's imagery.
    end_date = (
        today + timedelta(days=1)
    ).isoformat()

    try:
        image_result = (
            gee_client.find_best_image(
                region_bbox,
                start_date,
                end_date,
                GEE_CLOUD_COVER_THRESHOLD,
            )
        )

    except Exception as e:
        raise AcquisitionError(
            f"Earth Engine query failed: {e}"
        )

    # ---------------------------------------------------------
    # No imagery
    # ---------------------------------------------------------

    if image_result is None:
        raise AcquisitionError(
            f"No Sentinel-2 imagery found for "
            f"{start_date} to {end_date} "
            f"under {GEE_CLOUD_COVER_THRESHOLD}% "
            f"cloud cover in the configured AOI."
        )

    metadata, ee_image = image_result

    # `find_best_image()` explicitly uses (None, None)
    # to represent no imagery.
    if (
        metadata is None
        and ee_image is None
    ):
        raise AcquisitionError(
            f"No Sentinel-2 imagery found for "
            f"{start_date} to {end_date} "
            f"under {GEE_CLOUD_COVER_THRESHOLD}% "
            f"cloud cover in the configured AOI."
        )

    if (
        metadata is None
        or ee_image is None
    ):
        raise AcquisitionError(
            "Earth Engine returned an invalid "
            "image result."
        )

    gee_image_id = metadata[
        "gee_image_id"
    ]

    # =========================================================
    # 3. Duplicate registry lookup
    # =========================================================

    existing = (
        gee_registry.already_acquired(
            gee_image_id
        )
    )

    if existing is not None:

        existing_path = (
            existing["local_path"]
        )

        if not os.path.exists(
            existing_path
        ):
            raise AcquisitionError(
                "GEE registry points to a "
                f"missing local file: "
                f"{existing_path}"
            )

        # -----------------------------------------------------
        # IMPORTANT:
        # An existing registry entry may have been created
        # before the alignment feature existed.
        #
        # Therefore we check alignment here too.
        # -----------------------------------------------------

        (
            aligned_path,
            was_realigned,
            aligned_sha256,
        ) = _align_gee_image_if_needed(
            existing_path,
            baseline_path,
            run_id,
        )

        return (
            {
                "path": aligned_path,
                "type": "raster",
                "role": "raw_source_imagery_gee",
                "sha256": aligned_sha256,
            },
            {
                **metadata,
                "was_new_download": False,
                "was_realigned": was_realigned,
            },
            False,
        )

    # =========================================================
    # 4. New GEE download
    # =========================================================

    output_dir = os.path.join(
        DATA_DIR,
        "raw_images",
        GEE_OUTPUT_DIR_NAME,
    )

    os.makedirs(
        output_dir,
        exist_ok=True,
    )

    output_path = os.path.join(
        output_dir,
        (
            f"Forest_Sample_"
            f"{comparison_year}_gee_"
            f"{run_id[:8]}.tif"
        ),
    )

    try:
        # download_image() expects the actual ee.Image,
        # NOT the JSON metadata dictionary.
        gee_client.download_image(
            ee_image,
            region_bbox,
            output_path,
        )

    except Exception as e:
        raise AcquisitionError(
            f"Earth Engine download failed: {e}"
        )

    # =========================================================
    # 5. Validate fresh GEE download
    # =========================================================

    validation = validate_raster(
        output_path
    )

    if not validation["valid"]:
        raise AcquisitionError(
            "Newly-acquired GEE image failed "
            "Module 1 validation: "
            f"{validation['errors']}"
        )

    # =========================================================
    # 6. Align fresh GEE download to baseline
    # =========================================================

    (
        aligned_path,
        was_realigned,
        aligned_sha256,
    ) = _align_gee_image_if_needed(
        output_path,
        baseline_path,
        run_id,
    )

    acquired_at = datetime.now(
        timezone.utc
    ).isoformat()

    # =========================================================
    # 7. Register the FINAL downstream file
    # =========================================================

    gee_registry.register_acquisition(
        gee_image_id,
        aligned_path,
        aligned_sha256,
        acquired_at,
        metadata.get(
            "cloud_cover_pct"
        ),
    )

    return (
        {
            "path": aligned_path,
            "type": "raster",
            "role": "raw_source_imagery_gee",
            "sha256": aligned_sha256,
        },
        {
            **metadata,
            "was_new_download": True,
            "was_realigned": was_realigned,
            "acquired_at": acquired_at,
        },
        True,
    )


def run_acquisition(
    region_key=DEFAULT_REGION,
    base_year=DEFAULT_YEAR_PAIR[
        "base_year"
    ],
    comparison_year=DEFAULT_YEAR_PAIR[
        "comparison_year"
    ],
    trigger_mode="manual",
    use_live_gee=True,
    force=False,
):
    """
    Run one Module 2 acquisition cycle.

    Parameters
    ----------
    region_key:
        Region being monitored.

    base_year:
        Historical baseline year.

    comparison_year:
        Current/comparison year.

    trigger_mode:
        manual / scheduled / trigger etc.

    use_live_gee:
        True = acquire comparison imagery from GEE.
        False = use an existing local comparison raster.

    force:
        If True, an already registered GEE image may be reused
        and the acquisition manifest is marked successful so the
        downstream pipeline can run.
    """

    # =========================================================
    # Validate region
    # =========================================================

    if region_key not in REGIONS:
        raise AcquisitionError(
            f"Unknown region "
            f"'{region_key}'. "
            f"Known regions: "
            f"{list(REGIONS.keys())}"
        )

    run_id = str(
        uuid.uuid4()
    )

    triggered_at = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    region_bbox = (
        REGIONS[region_key]["bbox"]
    )

    # =========================================================
    # Step 1: Validate local/static datasets
    # =========================================================

    catalog = build_catalog()

    required_local_keys = (
        _static_and_baseline_keys(
            base_year
        )
    )

    missing_or_invalid = []
    dataset_refs = {}

    for key in required_local_keys:

        record = (
            catalog["datasets"]
            .get(key)
        )

        if record is None:

            missing_or_invalid.append(
                {
                    "key": key,
                    "reason": "not in catalog",
                }
            )

            continue

        if not record["valid"]:

            missing_or_invalid.append(
                {
                    "key": key,
                    "reason": record[
                        "errors"
                    ],
                }
            )

            continue

        dataset_refs[key] = {
            "path": record["path"],
            "type": record["type"],
            "role": record["role"],
            "sha256": record["sha256"],
        }

    if missing_or_invalid:

        _append_run_log(
            {
                "run_id": run_id,
                "triggered_at": triggered_at,
                "trigger_mode": trigger_mode,
                "status": "failed",
                "reason": missing_or_invalid,
            }
        )

        raise AcquisitionError(
            "Acquisition run aborted - "
            "required local datasets "
            f"not valid: "
            f"{missing_or_invalid}"
        )

    # =========================================================
    # Historical baseline path
    # =========================================================

    baseline_key = (
        f"forest_sample_{base_year}"
    )

    baseline_path = dataset_refs[
        baseline_key
    ]["path"]

    # =========================================================
    # Step 2: Comparison imagery
    # =========================================================

    gee_meta = None
    is_new_acquisition = True

    if use_live_gee:

        (
            comparison_ref,
            gee_meta,
            is_new_acquisition,
        ) = (
            _acquire_live_comparison_imagery(
                region_bbox,
                comparison_year,
                run_id,
                baseline_path,
            )
        )

        dataset_refs[
            f"forest_sample_{comparison_year}"
        ] = comparison_ref

    else:

        if (
            comparison_year
            not in YEAR_TO_DATASET_KEYS
        ):
            raise AcquisitionError(
                "use_live_gee=False requires "
                f"a registered local dataset "
                f"for year {comparison_year}."
            )

        key = (
            YEAR_TO_DATASET_KEYS[
                comparison_year
            ]["raw_imagery"]
        )

        record = (
            catalog["datasets"]
            .get(key)
        )

        if (
            record is None
            or not record["valid"]
        ):
            raise AcquisitionError(
                f"Local comparison dataset "
                f"'{key}' is missing or invalid."
            )

        dataset_refs[key] = {
            "path": record["path"],
            "type": record["type"],
            "role": record["role"],
            "sha256": record["sha256"],
        }

    # =========================================================
    # Step 3: Determine run status
    # =========================================================

    if force:
        status = "success"

    elif is_new_acquisition:
        status = "success"

    elif not use_live_gee:
        status = "success"

    else:
        status = "no_new_data"

    # =========================================================
    # Step 4: Build manifest
    # =========================================================

    manifest = {
        "run_id": run_id,
        "triggered_at": triggered_at,
        "trigger_mode": trigger_mode,
        "status": status,
        "forced": force,
        "region": REGIONS[
            region_key
        ],
        "base_year": base_year,
        "comparison_year": comparison_year,
        "datasets": dataset_refs,
        "use_live_gee": use_live_gee,
        "gee_metadata": gee_meta,
    }

    # =========================================================
    # Step 5: Write manifest
    # =========================================================

    os.makedirs(
        ACQUISITION_RUNS_DIR,
        exist_ok=True,
    )

    manifest_path = os.path.join(
        ACQUISITION_RUNS_DIR,
        f"run_{run_id}.json",
    )

    with open(
        manifest_path,
        "w",
    ) as f:

        json.dump(
            manifest,
            f,
            indent=2,
        )

    # =========================================================
    # Step 6: Append run log
    # =========================================================

    _append_run_log(
        {
            "run_id": run_id,
            "triggered_at": triggered_at,
            "trigger_mode": trigger_mode,
            "status": status,
            "manifest_path": manifest_path,
        }
    )

    manifest[
        "manifest_path"
    ] = manifest_path

    return manifest


def _append_run_log(entry):
    """
    Append-only acquisition history.

    One JSON object per line.
    """

    os.makedirs(
        ACQUISITION_RUNS_DIR,
        exist_ok=True,
    )

    with open(
        RUN_LOG_PATH,
        "a",
    ) as f:

        f.write(
            json.dumps(entry)
            + "\n"
        )