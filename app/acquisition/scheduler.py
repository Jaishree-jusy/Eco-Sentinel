"""
Scheduler wrapper for Module 2.

The scheduler checks for NEW live Sentinel-2 imagery automatically.

Historical acquisition remains available through the normal acquisition
functions. The scheduler is specifically for ongoing live monitoring.

Behavior:

    Daily scheduler check
            ↓
    Search recent GEE imagery
            ↓
    Already registered?
       YES → no_new_data
       NO  → acquire + run full pipeline
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.acquisition.config import (
    DEFAULT_REGION,
    DEFAULT_YEAR_PAIR,
)


logger = logging.getLogger("eco_sentinel.scheduler")


def _scheduled_job():
    """
    APScheduler's daily live-monitoring job.

    Checks Google Earth Engine for a new suitable Sentinel-2 image.
    The acquisition layer handles duplicate detection.

    A new image causes the complete downstream pipeline to run.

    If no new image exists, nothing downstream is executed.
    """

    from app.orchestration.pipeline_runner import (
        run_full_pipeline,
        PipelineRunError,
    )

    try:
        logger.info(
            "Scheduled live-monitoring check started."
        )

        result = run_full_pipeline(
            region_key=DEFAULT_REGION,
            base_year=DEFAULT_YEAR_PAIR["base_year"],
            comparison_year=DEFAULT_YEAR_PAIR["comparison_year"],
            trigger_mode="scheduled",
            use_live_gee=True,
        )

        if result["status"] == "no_new_data":

            logger.info(
                "Scheduled live-monitoring check: "
                "no new Sentinel-2 imagery available. "
                "Previous results preserved."
            )

        else:

            logger.info(
                "Scheduled live-monitoring pipeline succeeded: "
                f"{result['pipeline_run_id']}"
            )

    except PipelineRunError as e:

        logger.error(
            "Scheduled live-monitoring pipeline FAILED at "
            f"stage '{e.stage}': {e.original_error}"
        )


def trigger_now_full_pipeline(
    region_key=DEFAULT_REGION,
    base_year=None,
    comparison_year=None,
    use_live_gee=True,
    force=False,
    evidence_limit=None,
):
    """
    Manually fire one complete pipeline run.

    evidence_limit is optional and is passed through to the
    orchestration layer.
    """

    from app.orchestration.pipeline_runner import run_full_pipeline

    base_year = (
        base_year
        if base_year is not None
        else DEFAULT_YEAR_PAIR["base_year"]
    )

    comparison_year = (
        comparison_year
        if comparison_year is not None
        else DEFAULT_YEAR_PAIR["comparison_year"]
    )

    return run_full_pipeline(
        region_key=region_key,
        base_year=base_year,
        comparison_year=comparison_year,
        trigger_mode="manual",
        use_live_gee=use_live_gee,
        force=force,
        evidence_limit=evidence_limit,
    )


def trigger_now(
    region_key=DEFAULT_REGION,
    base_year=None,
    comparison_year=None,
    use_live_gee=True,
    force=False,
):
    """
    Acquisition-only manual trigger.

    Kept for backward compatibility and local testing.
    """

    from app.acquisition.runner import run_acquisition

    base_year = (
        base_year
        if base_year is not None
        else DEFAULT_YEAR_PAIR["base_year"]
    )

    comparison_year = (
        comparison_year
        if comparison_year is not None
        else DEFAULT_YEAR_PAIR["comparison_year"]
    )

    return run_acquisition(
        region_key=region_key,
        base_year=base_year,
        comparison_year=comparison_year,
        trigger_mode="manual",
        use_live_gee=use_live_gee,
        force=force,
    )


def start_scheduler():
    """
    Start the automatic live-monitoring scheduler.

    The scheduler checks once every day.

    It does NOT download an image every day.

    The acquisition registry determines whether the newest GEE
    image has already been processed. Only a genuinely new image
    proceeds through the full pipeline.
    """

    scheduler = BackgroundScheduler()

    scheduler.add_job(
        _scheduled_job,
        trigger=CronTrigger(
            hour=0,
            minute=0,
        ),
        id="daily_live_monitoring_job",
        name=(
            "Daily ECO-SENTINEL live Sentinel-2 monitoring"
        ),
        replace_existing=True,
    )

    scheduler.start()

    logger.info(
        "Live-monitoring scheduler started. "
        "GEE will be checked daily at 00:00."
    )

    return scheduler