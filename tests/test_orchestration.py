"""
Tests for app.orchestration.pipeline_runner.

Mocks each stage's pipeline function (already tested for real in their
own module's test files) to isolate and verify the ORCHESTRATION logic
itself: correct call order, fail-fast on any stage failure, the
no-new-data short-circuit, and pipeline_runs tracking in the database.
"""

import pytest
from unittest.mock import patch

from app.orchestration.pipeline_runner import run_full_pipeline, PipelineRunError
from app.database.schema import get_connection


def _fake_manifest(run_id, **extra):
    return {"run_id": run_id, **extra}


@pytest.fixture
def all_stages_mocked(tmp_path):
    """Patches every stage function this orchestrator calls to succeed
    quickly, returning fake-but-correctly-shaped manifests."""
    db_path = str(tmp_path / "test.db")

    patches = {
        "app.acquisition.runner.run_acquisition": _fake_manifest("acq-1", status="success"),
        "app.gee_processing.pipeline.run_gee_processing": _fake_manifest("gee-1"),
        "app.loss_detection.pipeline.run_loss_detection": _fake_manifest("loss-1"),
        "app.loss_detection.ai_pipeline.run_ai_disturbance_pipeline": _fake_manifest("ai-1"),
        "app.polygon_analysis.pipeline.run_polygon_analysis": _fake_manifest("poly-1"),
        "app.boundary_check.pipeline.run_boundary_check": _fake_manifest("bound-1"),
        "app.boundary_check.legality_pipeline.run_legality_check": _fake_manifest("legal-1"),
        "app.alerts.pipeline.run_alert_generation": _fake_manifest("alert-1"),
        "app.evidence.pipeline.run_evidence_generation": _fake_manifest("evid-1"),
        "app.blockchain.pipeline.run_blockchain_recording": _fake_manifest("block-1"),
    }

    mocks = {}
    active_patches = []
    for target, return_value in patches.items():
        p = patch(target, return_value=return_value)
        mock = p.start()
        active_patches.append(p)
        mocks[target] = mock

    sync_patch = patch("app.database.sync.sync_database", return_value={"alerts_synced": 5})
    mocks["sync"] = sync_patch.start()
    active_patches.append(sync_patch)

    yield db_path, mocks

    for p in active_patches:
        p.stop()


def test_full_pipeline_success_calls_every_stage_in_order(all_stages_mocked):
    db_path, mocks = all_stages_mocked

    result = run_full_pipeline(db_path=db_path, trigger_mode="manual")

    assert result["status"] == "success"
    assert len(result["stage_run_ids"]) == 10

    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM pipeline_runs WHERE pipeline_run_id = ?", (result["pipeline_run_id"],)
    ).fetchone()
    conn.close()

    assert row["overall_status"] == "success"
    assert row["acquisition_run_id"] == "acq-1"
    assert row["blockchain_run_id"] == "block-1"
    assert row["finished_at"] is not None


def test_full_pipeline_stops_on_no_new_data(tmp_path):
    db_path = str(tmp_path / "test.db")

    with patch(
        "app.acquisition.runner.run_acquisition",
        return_value=_fake_manifest("acq-1", status="no_new_data"),
    ), patch("app.gee_processing.pipeline.run_gee_processing") as mock_gee:

        result = run_full_pipeline(db_path=db_path, trigger_mode="scheduled")

        assert result["status"] == "no_new_data"
        mock_gee.assert_not_called()

    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM pipeline_runs WHERE pipeline_run_id = ?", (result["pipeline_run_id"],)
    ).fetchone()
    conn.close()
    assert row["overall_status"] == "no_new_data"


def test_full_pipeline_fails_fast_and_records_which_stage(tmp_path):
    db_path = str(tmp_path / "test.db")
    from app.loss_detection.pipeline import LossDetectionError

    with patch(
        "app.acquisition.runner.run_acquisition",
        return_value=_fake_manifest("acq-1", status="success"),
    ), patch(
        "app.gee_processing.pipeline.run_gee_processing",
        return_value=_fake_manifest("gee-1"),
    ), patch(
        "app.loss_detection.pipeline.run_loss_detection",
        side_effect=LossDetectionError("simulated NDVI diff raster missing"),
    ), patch("app.loss_detection.ai_pipeline.run_ai_disturbance_pipeline") as mock_ai:

        with pytest.raises(PipelineRunError) as exc_info:
            run_full_pipeline(db_path=db_path, trigger_mode="manual")

        assert exc_info.value.stage == "loss_detection"
        mock_ai.assert_not_called()

    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 1").fetchone()
    conn.close()

    assert row["overall_status"] == "failed"
    assert row["failed_stage"] == "loss_detection"
    assert "simulated NDVI diff raster missing" in row["error_message"]
    assert row["acquisition_run_id"] == "acq-1"
    assert row["loss_detection_run_id"] is None
