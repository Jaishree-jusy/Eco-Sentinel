"""
End-to-end pipeline orchestration.

Chains every module's EXISTING pipeline function, in-process (no
subprocess calls), in the order approved:

    GEE acquisition (Module 2)
        -> Module 1 validation happens INSIDE acquisition already
    -> Module 3 (preprocessing + NDVI)
    -> Module 4 (NDVI threshold, unchanged baseline)
    -> Module 4B (AI disturbance detection)
    -> Module 5 (polygon analysis, now AI-aware)
    -> Module 6 (forest boundary)
    -> Module 6B (legality check)
    -> Module 7 (alerts, now AI/legality-aware)
    -> Module 8 (evidence)
    -> Module 9 (blockchain)
    -> SQLite sync

Never marks a run successful if any required stage failed. If acquisition
finds no new imagery, the run stops right there (status="no_new_data")
and none of the expensive downstream stages run - previous results are
left untouched.
"""

import uuid
from datetime import datetime, timezone

from app.database.schema import get_connection, init_db


class PipelineRunError(Exception):
    def __init__(self, stage, original_error):
        self.stage = stage
        self.original_error = original_error
        super().__init__(f"Pipeline failed at stage '{stage}': {original_error}")


def _record_run_start(pipeline_run_id, trigger_mode, db_path=None):
    conn = get_connection(db_path)
    conn.execute(
        """INSERT INTO pipeline_runs (pipeline_run_id, started_at, trigger_mode, overall_status)
           VALUES (?, ?, ?, 'running')""",
        (pipeline_run_id, datetime.now(timezone.utc).isoformat(), trigger_mode),
    )
    conn.commit()
    conn.close()


def _record_run_result(pipeline_run_id, status, stage_run_ids, failed_stage=None, error_message=None, db_path=None):
    conn = get_connection(db_path)
    conn.execute(
        """UPDATE pipeline_runs SET
           finished_at = ?, overall_status = ?, failed_stage = ?, error_message = ?,
           acquisition_run_id = ?, gee_processing_run_id = ?, loss_detection_run_id = ?,
           ai_disturbance_run_id = ?, polygon_analysis_run_id = ?, boundary_check_run_id = ?,
           legality_check_run_id = ?, alert_generation_run_id = ?, evidence_generation_run_id = ?,
           blockchain_run_id = ?
           WHERE pipeline_run_id = ?""",
        (
            datetime.now(timezone.utc).isoformat(), status, failed_stage, error_message,
            stage_run_ids.get("acquisition"), stage_run_ids.get("gee_processing"),
            stage_run_ids.get("loss_detection"), stage_run_ids.get("ai_disturbance"),
            stage_run_ids.get("polygon_analysis"), stage_run_ids.get("boundary_check"),
            stage_run_ids.get("legality_check"), stage_run_ids.get("alert_generation"),
            stage_run_ids.get("evidence_generation"), stage_run_ids.get("blockchain"),
            pipeline_run_id,
        ),
    )
    conn.commit()
    conn.close()


def run_full_pipeline(
    region_key=None, base_year=None, comparison_year=None, trigger_mode="manual",
    use_live_gee=True, db_path=None, evidence_limit=None, force=False,
):
    """Runs the complete pipeline end to end. Returns a summary dict.
    Raises PipelineRunError (with .stage telling you exactly where it
    failed) on any real failure - never silently continues past a broken
    stage, and never marks a run successful if any required stage failed."""
    from app.acquisition.runner import run_acquisition, AcquisitionError
    from app.acquisition.config import DEFAULT_REGION, DEFAULT_YEAR_PAIR
    from app.gee_processing.pipeline import run_gee_processing, GeeProcessingError
    from app.loss_detection.pipeline import run_loss_detection, LossDetectionError
    from app.loss_detection.ai_pipeline import run_ai_disturbance_pipeline, AiDisturbanceError
    from app.polygon_analysis.pipeline import run_polygon_analysis, PolygonAnalysisError
    from app.boundary_check.pipeline import run_boundary_check, BoundaryPipelineError
    from app.boundary_check.legality_pipeline import run_legality_check, LegalityCheckError
    from app.alerts.pipeline import run_alert_generation, AlertGenerationError
    from app.evidence.pipeline import run_evidence_generation, EvidenceGenerationError
    from app.blockchain.pipeline import run_blockchain_recording, BlockchainError
    from app.database.sync import sync_database

    region_key = region_key or DEFAULT_REGION
    base_year = base_year or DEFAULT_YEAR_PAIR["base_year"]
    comparison_year = comparison_year or DEFAULT_YEAR_PAIR["comparison_year"]

    pipeline_run_id = str(uuid.uuid4())
    init_db(db_path)
    _record_run_start(pipeline_run_id, trigger_mode, db_path)

    stage_run_ids = {}

    try:
        try:
            acq_manifest = run_acquisition(
                region_key=region_key, base_year=base_year, comparison_year=comparison_year,
                trigger_mode=trigger_mode, use_live_gee=use_live_gee, force=force,
            )
        except AcquisitionError as e:
            raise PipelineRunError("acquisition", e)
        stage_run_ids["acquisition"] = acq_manifest["run_id"]

        if acq_manifest["status"] == "no_new_data":
            _record_run_result(pipeline_run_id, "no_new_data", stage_run_ids, db_path=db_path)
            return {
                "pipeline_run_id": pipeline_run_id, "status": "no_new_data",
                "message": "No new satellite imagery available - downstream pipeline not rerun, previous results preserved.",
                "stage_run_ids": stage_run_ids,
                "gee_metadata": acq_manifest.get("gee_metadata"),
                "acquisition_manifest": acq_manifest,
            }

        try:
            gee_manifest = run_gee_processing(acq_manifest)
        except GeeProcessingError as e:
            raise PipelineRunError("gee_processing", e)
        stage_run_ids["gee_processing"] = gee_manifest["run_id"]

        try:
            loss_manifest = run_loss_detection(gee_manifest)
        except LossDetectionError as e:
            raise PipelineRunError("loss_detection", e)
        stage_run_ids["loss_detection"] = loss_manifest["run_id"]

        try:
            ai_manifest = run_ai_disturbance_pipeline(acq_manifest)
        except AiDisturbanceError as e:
            raise PipelineRunError("ai_disturbance", e)
        stage_run_ids["ai_disturbance"] = ai_manifest["run_id"]

        try:
            polygon_manifest = run_polygon_analysis(loss_manifest)
        except PolygonAnalysisError as e:
            raise PipelineRunError("polygon_analysis", e)
        stage_run_ids["polygon_analysis"] = polygon_manifest["run_id"]

        try:
            boundary_manifest = run_boundary_check(polygon_manifest, acq_manifest)
        except BoundaryPipelineError as e:
            raise PipelineRunError("boundary_check", e)
        stage_run_ids["boundary_check"] = boundary_manifest["run_id"]

        try:
            legality_manifest = run_legality_check(boundary_manifest)
        except LegalityCheckError as e:
            raise PipelineRunError("legality_check", e)
        stage_run_ids["legality_check"] = legality_manifest["run_id"]

        try:
            alert_manifest = run_alert_generation(boundary_manifest, acq_manifest)
        except AlertGenerationError as e:
            raise PipelineRunError("alert_generation", e)
        stage_run_ids["alert_generation"] = alert_manifest["run_id"]

        try:
            evidence_manifest = run_evidence_generation(alert_manifest, boundary_manifest, acq_manifest, limit=evidence_limit)
        except EvidenceGenerationError as e:
            raise PipelineRunError("evidence_generation", e)
        stage_run_ids["evidence_generation"] = evidence_manifest["run_id"]

        try:
            blockchain_manifest = run_blockchain_recording(evidence_manifest)
        except BlockchainError as e:
            raise PipelineRunError("blockchain", e)
        stage_run_ids["blockchain"] = blockchain_manifest["run_id"]

        try:
            sync_stats = sync_database(db_path=db_path)
        except Exception as e:
            raise PipelineRunError("database_sync", e)

        _record_run_result(pipeline_run_id, "success", stage_run_ids, db_path=db_path)
        return {
            "pipeline_run_id": pipeline_run_id, "status": "success",
            "stage_run_ids": stage_run_ids, "sync_stats": sync_stats,
            "gee_metadata": acq_manifest.get("gee_metadata"),
            "acquisition_manifest": acq_manifest,
        }

    except PipelineRunError as e:
        _record_run_result(
            pipeline_run_id, "failed", stage_run_ids,
            failed_stage=e.stage, error_message=str(e.original_error), db_path=db_path,
        )
        raise
