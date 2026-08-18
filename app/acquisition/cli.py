"""
CLI for Module 2 - Data Acquisition & Scheduler.

Usage (from the eco-sentinel/ project root):

    python -m app.acquisition.cli run
        # Module 2 only (acquisition), backward-compatible

    python -m app.acquisition.cli trigger
        # FULL pipeline: acquisition through dashboards

    python -m app.acquisition.cli start-scheduler
        # Register the monthly full-pipeline job
"""

import sys
import argparse
import logging

from app.acquisition.scheduler import (
    trigger_now,
    trigger_now_full_pipeline,
    start_scheduler,
)
from app.acquisition.runner import AcquisitionError
from app.acquisition.config import DEFAULT_REGION, DEFAULT_YEAR_PAIR


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def _print_stage_summary(stage_run_ids):
    for stage, run_id in stage_run_ids.items():
        print(f"    {stage:22} -> {run_id}")


def main():
    parser = argparse.ArgumentParser(
        description="ECO-SENTINEL Module 2 CLI"
    )

    parser.add_argument(
        "command",
        choices=["run", "trigger", "start-scheduler"],
        help=(
            "run: acquisition only (Module 2). "
            "trigger: the FULL pipeline, acquisition through dashboards. "
            "start-scheduler: register the monthly full-pipeline job."
        ),
    )

    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help="Region key to acquire data for",
    )

    parser.add_argument(
        "--base-year",
        type=int,
        default=DEFAULT_YEAR_PAIR["base_year"],
    )

    parser.add_argument(
        "--comparison-year",
        type=int,
        default=DEFAULT_YEAR_PAIR["comparison_year"],
    )

    parser.add_argument(
        "--no-live-gee",
        action="store_true",
        help=(
            "Use local historical files instead of live Earth Engine "
            "acquisition (offline/testing fallback)."
        ),
    )

    parser.add_argument(
        "--evidence-limit",
        type=int,
        default=None,
        help=(
            "Only generate evidence for this many alerts "
            "(trigger command only) - useful for a quick test run."
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Treat an already-acquired (deduplicated) image as ready for "
            "downstream processing anyway, instead of reporting no_new_data. "
            "Does not re-download - reuses the cached file. Useful for "
            "testing the full pipeline against an image you already have."
        ),
    )

    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Module 2 acquisition only
    # ------------------------------------------------------------------
    if args.command == "run":
        try:
            manifest = trigger_now(
                region_key=args.region,
                base_year=args.base_year,
                comparison_year=args.comparison_year,
                use_live_gee=not args.no_live_gee,
                force=args.force,
            )

            print("\nAcquisition run SUCCESS")
            print(f"  run_id:      {manifest['run_id']}")
            print(f"  status:      {manifest['status']}")
            print(f"  region:      {manifest['region']['name']}")
            print(f"  base_year:   {manifest['base_year']}")
            print(f"  comp_year:   {manifest['comparison_year']}")
            print(f"  live GEE:    {manifest['use_live_gee']}")

            if manifest.get("gee_metadata"):
                print(
                    f"  GEE image:   "
                    f"{manifest['gee_metadata'].get('gee_image_id')}"
                )
                print(
                    f"  cloud cover: "
                    f"{manifest['gee_metadata'].get('cloud_cover_pct')}%"
                )

            print(
                f"  datasets:    "
                f"{list(manifest['datasets'].keys())}"
            )
            print(
                f"  manifest:    "
                f"{manifest['manifest_path']}\n"
            )

        except AcquisitionError as e:
            print(f"\nAcquisition run FAILED: {e}\n")
            sys.exit(1)

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------
    elif args.command == "trigger":
        from app.orchestration.pipeline_runner import PipelineRunError

        print(
            "Running the FULL ECO-SENTINEL pipeline: "
            "acquisition -> dashboards..."
        )
        print(
            "This includes live Earth Engine acquisition, satellite "
            "processing, AI scoring,"
        )
        print(
            "evidence generation, and blockchain recording - "
            "expect this to take a while.\n"
        )

        # Helpful visibility: show the requested evidence limit.
        if args.evidence_limit is not None:
            print(
                f"Evidence generation limit: "
                f"{args.evidence_limit} alert(s)\n"
            )

        try:
            result = trigger_now_full_pipeline(
                region_key=args.region,
                base_year=args.base_year,
                comparison_year=args.comparison_year,
                use_live_gee=not args.no_live_gee,
                force=args.force,
                evidence_limit=args.evidence_limit,
            )

            if result["status"] == "no_new_data":
                print("\nPipeline run: NO NEW DATA")
                print(
                    f"  pipeline_run_id: "
                    f"{result['pipeline_run_id']}"
                )
                print(
                    "  No new satellite imagery available - "
                    "previous results preserved, downstream stages skipped.\n"
                )

            else:
                print("\nFull Pipeline SUCCESS")
                print(
                    f"  pipeline_run_id: "
                    f"{result['pipeline_run_id']}"
                )
                print("  stages completed:")
                _print_stage_summary(result["stage_run_ids"])
                print(
                    f"  database sync:   "
                    f"{result['sync_stats']}\n"
                )

        except PipelineRunError as e:
            print(
                f"\nFull Pipeline FAILED at stage "
                f"'{e.stage}': {e.original_error}\n"
            )
            print(
                "Previous valid results have been preserved - "
                "no partial/broken data was committed.\n"
            )
            sys.exit(1)

    # ------------------------------------------------------------------
    # Monthly scheduler
    # ------------------------------------------------------------------
    elif args.command == "start-scheduler":
        scheduler = start_scheduler()

        print(
            "Scheduler started with the monthly FULL-PIPELINE job "
            "registered. Press Ctrl+C to stop."
        )

        try:
            import time

            while True:
                time.sleep(1)

        except KeyboardInterrupt:
            scheduler.shutdown()
            print("Scheduler stopped.")


if __name__ == "__main__":
    main()