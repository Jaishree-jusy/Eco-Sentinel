"""
CLI for Module 6 - Forest Boundary Check.

Usage (from the eco-sentinel/ project root):

    python -m app.boundary_check.cli check
"""

import sys
from app.boundary_check.pipeline import run_boundary_check, BoundaryPipelineError


def main():
    try:
        print("Running Module 6 - Forest Boundary Check...")
        manifest = run_boundary_check()

        print("\nBoundary Check SUCCESS")
        print(f"  run_id:               {manifest['run_id']}")
        print(f"  region column used:   {manifest['region_column_used']}")
        print(f"  INSIDE FOREST:        {manifest['inside_forest']['count']} polygons, "
              f"{manifest['inside_forest']['total_area_ha']} ha")
        print(f"    -> {manifest['inside_forest']['path']}")
        print(f"  OUTSIDE FOREST:       {manifest['outside_forest']['count']} polygons, "
              f"{manifest['outside_forest']['total_area_ha']} ha")
        print(f"    -> {manifest['outside_forest']['path']}")
        if manifest["unknown_classification"]["count"] > 0:
            u = manifest["unknown_classification"]
            print(f"  UNKNOWN (needs review): {u['count']} polygons, {u['total_area_ha']} ha")
            print(f"    -> {u['path']}")
            print(f"    ({u['note']})")
        print(f"  manifest:             {manifest['manifest_path']}\n")

    except BoundaryPipelineError as e:
        print(f"\nBoundary Check FAILED: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
