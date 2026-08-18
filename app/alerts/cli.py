"""
CLI for Module 7 / 7A - Alert Generation.

Usage (from the eco-sentinel/ project root):

    python -m app.alerts.cli generate
"""

import sys
from app.alerts.pipeline import run_alert_generation, AlertGenerationError


def main():
    try:
        print("Running Module 7 / 7A - Alert Generation...")
        manifest = run_alert_generation()

        print("\nAlert Generation SUCCESS")
        print(f"  run_id:                {manifest['run_id']}")
        print(f"  INSIDE FOREST alerts:  {manifest['inside_forest_alerts']['count']}")
        print(f"    -> {manifest['inside_forest_alerts']['path']}")
        print(f"  OUTSIDE FOREST alerts: {manifest['outside_forest_alerts']['count']}")
        print(f"    -> {manifest['outside_forest_alerts']['path']}")
        print(f"  manifest:              {manifest['manifest_path']}\n")

    except AlertGenerationError as e:
        print(f"\nAlert Generation FAILED: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
