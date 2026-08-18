"""
CLI for Module 3 - Google Earth Engine Processing.

Usage (from the eco-sentinel/ project root):

    python -m app.gee_processing.cli process

Automatically uses the latest successful Module 2 acquisition run.
Expect this to take longer than Modules 1/2 - it reads full-resolution
band data (not samples) to actually compute NDVI.
"""

import sys
from app.gee_processing.pipeline import run_gee_processing, GeeProcessingError


def main():
    try:
        print("Running Module 3 - GEE Processing (this reads full-resolution imagery, may take a few minutes)...")
        manifest = run_gee_processing()

        print("\nGEE Processing SUCCESS")
        print(f"  run_id:            {manifest['run_id']}")
        print(f"  base_year:         {manifest['base_year']}")
        print(f"  comparison_year:   {manifest['comparison_year']}")
        print(f"  NDVI base:         {manifest['ndvi_base']['path']}")
        print(f"    cloud masked:    {manifest['ndvi_base']['cloud_masked_pct']}%")
        print(f"    NDVI range:      [{manifest['ndvi_base']['ndvi_min']:.4f}, {manifest['ndvi_base']['ndvi_max']:.4f}]")
        print(f"  NDVI comparison:   {manifest['ndvi_comparison']['path']}")
        print(f"    cloud masked:    {manifest['ndvi_comparison']['cloud_masked_pct']}%")
        print(f"    NDVI range:      [{manifest['ndvi_comparison']['ndvi_min']:.4f}, {manifest['ndvi_comparison']['ndvi_max']:.4f}]")
        print(f"  NDVI diff:         {manifest['ndvi_diff']['path']}")
        print(f"    diff range:      [{manifest['ndvi_diff']['diff_min']:.4f}, {manifest['ndvi_diff']['diff_max']:.4f}]")
        print(f"  manifest:          {manifest['manifest_path']}\n")

    except GeeProcessingError as e:
        print(f"\nGEE Processing FAILED: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
