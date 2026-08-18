"""
Tests for Module 2 - Data Acquisition & Scheduler (live GEE + local fallback).

Local/static datasets are mocked via build_catalog(). The actual GEE
network boundary (app.acquisition.gee_client) is mocked at its three real
entry points - initialize_earth_engine, find_best_image, download_image -
so these tests verify all the REAL logic around GEE (dedup, validation
gating, manifest structure, failure handling) without needing real network
access or real credentials. The actual live network call is never mocked
away silently - it's the one thing these tests deliberately don't and
can't cover; that's verified separately, by hand, with real credentials.
"""

import os
import json
import pytest
import numpy as np
import rasterio
from rasterio.transform import from_origin
from unittest.mock import patch, MagicMock

from app.acquisition.runner import run_acquisition, AcquisitionError
import app.acquisition.runner as runner_module
from app.acquisition import gee_client


def _write_real_raster(path, width=20, height=20, band_names=None):
    """Alignment needs a physically-openable raster for both the newly
    'downloaded' file and the baseline it aligns against - fake byte
    content isn't enough anymore."""
    band_names = band_names or ["B4", "B8", "SCL"]
    transform = from_origin(74.75, 13.0, 0.0001, 0.0001)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=len(band_names),
        dtype="float64", crs="EPSG:4326", transform=transform,
    ) as dst:
        for i, name in enumerate(band_names, start=1):
            dst.write(np.full((height, width), 100.0 * i), i)
            dst.set_band_description(i, name)
    return path


def _fake_valid_catalog(baseline_path=None):
    """A catalog where every LOCAL/static dataset Module 2 needs is valid.
    Note: no ndvi_2023/2025 required anymore - those were always unused
    downstream (documented in DESIGN_DECISIONS.md), only forest_sample_2023
    (baseline) and the static reference datasets are required locally now."""
    keys = ["forest_sample_2023", "worldcover_2021", "gadm_forest_boundary", "fire_archive_1", "fire_archive_2"]
    catalog = {
        "datasets": {
            key: {
                "path": f"/fake/{key}.tif", "type": "raster", "role": "test_role",
                "valid": True, "errors": [], "sha256": "fakehash",
            }
            for key in keys
        }
    }
    if baseline_path is not None:
        catalog["datasets"]["forest_sample_2023"]["path"] = baseline_path
    return catalog


def _fake_catalog_with_invalid(key_to_break):
    catalog = _fake_valid_catalog()
    catalog["datasets"][key_to_break]["valid"] = False
    catalog["datasets"][key_to_break]["errors"] = ["simulated failure"]
    return catalog


def _fake_image_info(image_id="COPERNICUS/S2_SR_HARMONIZED/fake123"):
    metadata = {"gee_image_id": image_id, "acquisition_date": 1735689600000, "cloud_cover_pct": 5.2}
    return metadata, MagicMock()  # (plain metadata, fake ee.Image)


# ---------------------------------------------------------------------
# Local-only fallback path (use_live_gee=False) - preserves old behavior
# ---------------------------------------------------------------------

@patch.object(runner_module, "build_catalog")
def test_run_acquisition_local_fallback_success(mock_build_catalog, tmp_path, monkeypatch):
    catalog = _fake_valid_catalog()
    catalog["datasets"]["forest_sample_2025"] = {
        "path": "/fake/forest_sample_2025.tif", "type": "raster", "role": "test_role",
        "valid": True, "errors": [], "sha256": "fakehash2025",
    }
    mock_build_catalog.return_value = catalog
    monkeypatch.setattr(runner_module, "ACQUISITION_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(runner_module, "RUN_LOG_PATH", str(tmp_path / "run_log.jsonl"))

    manifest = run_acquisition(region_key="region_1", base_year=2023, comparison_year=2025, use_live_gee=False)

    assert manifest["status"] == "success"
    assert manifest["use_live_gee"] is False
    assert "forest_sample_2023" in manifest["datasets"]
    assert "forest_sample_2025" in manifest["datasets"]
    assert os.path.exists(manifest["manifest_path"])


@patch.object(runner_module, "build_catalog")
def test_run_acquisition_fails_on_invalid_baseline(mock_build_catalog, tmp_path, monkeypatch):
    mock_build_catalog.return_value = _fake_catalog_with_invalid("forest_sample_2023")
    monkeypatch.setattr(runner_module, "ACQUISITION_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(runner_module, "RUN_LOG_PATH", str(tmp_path / "run_log.jsonl"))

    with pytest.raises(AcquisitionError):
        run_acquisition(region_key="region_1", base_year=2023, comparison_year=2025, use_live_gee=False)

    with open(str(tmp_path / "run_log.jsonl")) as f:
        lines = f.readlines()
    assert json.loads(lines[0])["status"] == "failed"


@patch.object(runner_module, "build_catalog")
def test_run_acquisition_unknown_region(mock_build_catalog, tmp_path, monkeypatch):
    mock_build_catalog.return_value = _fake_valid_catalog()
    monkeypatch.setattr(runner_module, "ACQUISITION_RUNS_DIR", str(tmp_path))

    with pytest.raises(AcquisitionError):
        run_acquisition(region_key="nonexistent_region", use_live_gee=False)


# ---------------------------------------------------------------------
# Live GEE path (use_live_gee=True, the default / final architecture)
# ---------------------------------------------------------------------

@patch.object(runner_module, "validate_raster")
@patch.object(gee_client, "download_image")
@patch.object(gee_client, "find_best_image")
@patch.object(gee_client, "initialize_earth_engine")
@patch.object(runner_module, "build_catalog")
def test_run_acquisition_live_gee_new_image(
    mock_build_catalog, mock_init, mock_find, mock_download, mock_validate,
    tmp_path, monkeypatch
):
    baseline_path = _write_real_raster(str(tmp_path / "baseline_2023.tif"))
    mock_build_catalog.return_value = _fake_valid_catalog(baseline_path=baseline_path)
    monkeypatch.setattr(runner_module, "ACQUISITION_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(runner_module, "RUN_LOG_PATH", str(tmp_path / "run_log.jsonl"))
    monkeypatch.setattr(runner_module, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.acquisition.gee_registry.REGISTRY_PATH", str(tmp_path / "registry.json"))

    def _fake_download(image, bbox, output_path, scale=10):
        # Same grid as baseline - this test focuses on the acquisition
        # flow itself; mismatched-grid alignment is tested end-to-end
        # separately below.
        _write_real_raster(output_path)
        return output_path

    mock_find.return_value = _fake_image_info()
    mock_download.side_effect = _fake_download
    mock_validate.return_value = {"valid": True, "errors": [], "warnings": [], "metadata": {}}

    manifest = run_acquisition(region_key="region_1", base_year=2023, comparison_year=2025, use_live_gee=True)

    assert manifest["status"] == "success"
    assert manifest["use_live_gee"] is True
    assert manifest["gee_metadata"]["was_new_download"] is True
    assert manifest["datasets"]["forest_sample_2025"]["role"] == "raw_source_imagery_gee"
    mock_init.assert_called_once()
    mock_download.assert_called_once()

    # Regression guard for the exact real-world failure hit in production:
    # the manifest is written via json.dump() by run_acquisition() itself,
    # so if this passed, the file write already succeeded - but assert it
    # explicitly too, since that's the literal failure mode that occurred.
    import json
    json.dumps(manifest["gee_metadata"])  # raises TypeError if anything non-serializable leaked in


@patch.object(runner_module, "validate_raster")
@patch.object(gee_client, "download_image")
@patch.object(gee_client, "find_best_image")
@patch.object(gee_client, "initialize_earth_engine")
@patch.object(runner_module, "build_catalog")
def test_run_acquisition_live_gee_dedup_skips_download(
    mock_build_catalog, mock_init, mock_find, mock_download, mock_validate,
    tmp_path, monkeypatch
):
    """Real duplicate-prevention test: the same GEE image ID, already
    registered -> must NOT re-download, and status must be 'no_new_data'
    so the orchestrator knows to skip the expensive downstream pipeline."""
    mock_build_catalog.return_value = _fake_valid_catalog()
    monkeypatch.setattr(runner_module, "ACQUISITION_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(runner_module, "RUN_LOG_PATH", str(tmp_path / "run_log.jsonl"))
    registry_path = str(tmp_path / "registry.json")
    monkeypatch.setattr("app.acquisition.gee_registry.REGISTRY_PATH", registry_path)

    already_downloaded_path = str(tmp_path / "already_here.tif")
    open(already_downloaded_path, "wb").write(b"already downloaded")

    from app.acquisition import gee_registry
    gee_registry.register_acquisition(
        "COPERNICUS/S2_SR_HARMONIZED/fake123", already_downloaded_path,
        "realhash", "2026-01-01T00:00:00", 5.2, registry_path=registry_path,
    )

    mock_find.return_value = _fake_image_info()  # same image_id as registered above

    manifest = run_acquisition(region_key="region_1", base_year=2023, comparison_year=2025, use_live_gee=True)

    assert manifest["status"] == "no_new_data"
    mock_download.assert_not_called()  # the actual point of this test
    mock_validate.assert_not_called()


@patch.object(gee_client, "find_best_image")
@patch.object(gee_client, "initialize_earth_engine")
@patch.object(runner_module, "build_catalog")
def test_run_acquisition_live_gee_no_imagery_found(
    mock_build_catalog, mock_init, mock_find, tmp_path, monkeypatch
):
    mock_build_catalog.return_value = _fake_valid_catalog()
    monkeypatch.setattr(runner_module, "ACQUISITION_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(runner_module, "RUN_LOG_PATH", str(tmp_path / "run_log.jsonl"))
    mock_find.return_value = (None, None)  # legitimate "nothing matched" result

    with pytest.raises(AcquisitionError, match="No Sentinel-2 imagery found"):
        run_acquisition(region_key="region_1", base_year=2023, comparison_year=2025, use_live_gee=True)


@patch.object(gee_client, "initialize_earth_engine")
@patch.object(runner_module, "build_catalog")
def test_run_acquisition_live_gee_auth_failure(mock_build_catalog, mock_init, tmp_path, monkeypatch):
    mock_build_catalog.return_value = _fake_valid_catalog()
    monkeypatch.setattr(runner_module, "ACQUISITION_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(runner_module, "RUN_LOG_PATH", str(tmp_path / "run_log.jsonl"))
    mock_init.side_effect = gee_client.GEEAuthenticationError("not authenticated, run earthengine authenticate")

    with pytest.raises(AcquisitionError, match="earthengine authenticate"):
        run_acquisition(region_key="region_1", base_year=2023, comparison_year=2025, use_live_gee=True)


@patch.object(runner_module, "validate_raster")
@patch.object(gee_client, "download_image")
@patch.object(gee_client, "find_best_image")
@patch.object(gee_client, "initialize_earth_engine")
@patch.object(runner_module, "build_catalog")
def test_run_acquisition_live_gee_validation_failure(
    mock_build_catalog, mock_init, mock_find, mock_download, mock_validate,
    tmp_path, monkeypatch
):
    """A downloaded GEE image that fails Module 1 validation must abort the
    run, not silently hand a bad file to Module 3."""
    baseline_path = _write_real_raster(str(tmp_path / "baseline_2023.tif"))
    mock_build_catalog.return_value = _fake_valid_catalog(baseline_path=baseline_path)
    monkeypatch.setattr(runner_module, "ACQUISITION_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(runner_module, "RUN_LOG_PATH", str(tmp_path / "run_log.jsonl"))
    monkeypatch.setattr(runner_module, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.acquisition.gee_registry.REGISTRY_PATH", str(tmp_path / "registry.json"))

    def _fake_download(image, bbox, output_path, scale=10):
        # Same grid as baseline, so alignment is skipped and this test
        # stays focused on the validation-failure path specifically.
        _write_real_raster(output_path)
        return output_path

    mock_find.return_value = _fake_image_info()
    mock_download.side_effect = _fake_download
    mock_validate.return_value = {"valid": False, "errors": ["corrupt raster"], "warnings": [], "metadata": {}}

    with pytest.raises(AcquisitionError, match="failed Module 1 validation"):
        run_acquisition(region_key="region_1", base_year=2023, comparison_year=2025, use_live_gee=True)


@patch.object(gee_client, "download_image")
@patch.object(gee_client, "find_best_image")
@patch.object(gee_client, "initialize_earth_engine")
@patch.object(runner_module, "build_catalog")
def test_run_acquisition_force_overrides_no_new_data(
    mock_build_catalog, mock_init, mock_find, mock_download,
    tmp_path, monkeypatch
):
    """Regression test for the exact real scenario hit in production: the
    same image is already registered (would normally be no_new_data), but
    force=True must still report status=success so downstream modules'
    auto-discovery (which only picks up status=='success') can find it -
    without triggering a wasteful re-download."""
    mock_build_catalog.return_value = _fake_valid_catalog()
    monkeypatch.setattr(runner_module, "ACQUISITION_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(runner_module, "RUN_LOG_PATH", str(tmp_path / "run_log.jsonl"))
    registry_path = str(tmp_path / "registry.json")
    monkeypatch.setattr("app.acquisition.gee_registry.REGISTRY_PATH", registry_path)

    already_downloaded_path = str(tmp_path / "already_here.tif")
    open(already_downloaded_path, "wb").write(b"already downloaded")

    from app.acquisition import gee_registry
    gee_registry.register_acquisition(
        "COPERNICUS/S2_SR_HARMONIZED/fake123", already_downloaded_path,
        "realhash", "2026-01-01T00:00:00", 5.2, registry_path=registry_path,
    )
    mock_find.return_value = _fake_image_info()

    manifest = run_acquisition(
        region_key="region_1", base_year=2023, comparison_year=2025,
        use_live_gee=True, force=True,
    )

    assert manifest["status"] == "success"
    assert manifest["forced"] is True
    mock_download.assert_not_called()


@patch.object(runner_module, "validate_raster")
@patch.object(gee_client, "download_image")
@patch.object(gee_client, "find_best_image")
@patch.object(gee_client, "initialize_earth_engine")
@patch.object(runner_module, "build_catalog")
def test_run_acquisition_aligns_mismatched_grid(
    mock_build_catalog, mock_init, mock_find, mock_download, mock_validate,
    tmp_path, monkeypatch
):
    """Regression test for the exact real bug hit in production: the
    live-acquired image has a genuinely different grid than the baseline.
    run_acquisition must resolve this via alignment, producing a final
    file that shares the baseline's exact grid."""
    baseline_path = _write_real_raster(str(tmp_path / "baseline_2023.tif"), width=50, height=50)
    mock_build_catalog.return_value = _fake_valid_catalog(baseline_path=baseline_path)
    monkeypatch.setattr(runner_module, "ACQUISITION_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(runner_module, "RUN_LOG_PATH", str(tmp_path / "run_log.jsonl"))
    monkeypatch.setattr(runner_module, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.acquisition.gee_registry.REGISTRY_PATH", str(tmp_path / "registry.json"))

    def _fake_download_mismatched_grid(image, bbox, output_path, scale=10):
        transform = from_origin(74.7503, 13.0004, 0.00012, 0.00012)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with rasterio.open(
            output_path, "w", driver="GTiff", height=46, width=47, count=3,
            dtype="float64", crs="EPSG:4326", transform=transform,
        ) as dst:
            for i, name in enumerate(["B4", "B8", "SCL"], start=1):
                dst.write(np.full((46, 47), 100.0 * i), i)
                dst.set_band_description(i, name)
        return output_path

    mock_find.return_value = _fake_image_info()
    mock_download.side_effect = _fake_download_mismatched_grid
    mock_validate.return_value = {"valid": True, "errors": [], "warnings": [], "metadata": {}}

    manifest = run_acquisition(region_key="region_1", base_year=2023, comparison_year=2025, use_live_gee=True)

    assert manifest["status"] == "success"
    aligned_path = manifest["datasets"]["forest_sample_2025"]["path"]

    with rasterio.open(baseline_path) as base, rasterio.open(aligned_path) as aligned:
        assert aligned.transform == base.transform
        assert aligned.width == base.width
        assert aligned.height == base.height
