"""
CLI for Module 4 - Vegetation Loss Detection.

Usage (from the eco-sentinel/ project root):

    python -m app.loss_detection.cli detect
"""

import sys
from app.loss_detection.pipeline import run_loss_detection, LossDetectionError


def main():
    try:
        manifest = run_loss_detection()

        print("\nVegetation Loss Detection SUCCESS")
        print(f"  run_id:          {manifest['run_id']}")
        print(f"  base_year:       {manifest['base_year']}")
        print(f"  comparison_year: {manifest['comparison_year']}")
        print(f"  threshold used:  {manifest['stats']['threshold_used']}")
        print(f"  loss pixels:     {manifest['stats']['loss_pixels']} "
              f"({manifest['stats']['loss_pct_of_valid']}% of valid area)")
        print(f"  loss mask:       {manifest['loss_mask_path']}")
        print(f"  manifest:        {manifest['manifest_path']}\n")

    except LossDetectionError as e:
        print(f"\nVegetation Loss Detection FAILED: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
