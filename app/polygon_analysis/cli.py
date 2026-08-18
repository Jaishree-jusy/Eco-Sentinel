"""
CLI for Module 5 - Polygon Generation & Analysis.

Usage (from the eco-sentinel/ project root):

    python -m app.polygon_analysis.cli analyze
"""

import sys
from app.polygon_analysis.pipeline import run_polygon_analysis, PolygonAnalysisError


def main():
    try:
        print("Running Module 5 - Polygon Generation & Analysis...")
        manifest = run_polygon_analysis()

        print("\nPolygon Analysis SUCCESS")
        print(f"  run_id:              {manifest['run_id']}")
        print(f"  base_year:           {manifest['base_year']}")
        print(f"  comparison_year:     {manifest['comparison_year']}")
        s = manifest["stats"]
        print(f"  raw polygons:        {s['raw_polygon_count']}")
        print(f"  after min-area filter ({s['min_area_ha_filter']} ha): {s['filtered_polygon_count']}")
        print(f"  total loss area:     {s['total_loss_area_ha']} ha")
        print(f"  severity breakdown:  {s['severity_counts']}")
        print(f"  geojson:             {manifest['geojson_path']}")
        print(f"  manifest:            {manifest['manifest_path']}\n")

    except PolygonAnalysisError as e:
        print(f"\nPolygon Analysis FAILED: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
