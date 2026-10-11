
from pathlib import Path
import json
import uuid
from datetime import datetime, timezone

import geopandas as gpd

from app.acquisition.config import ACQUISITION_RUNS_DIR
from app.boundary_check.pipeline import run_boundary_check

ROOT = Path("data/supervised/live_runs")
INPUT = ROOT / "deforestation_polygons_live.geojson"


def latest_successful_acquisition():
    manifests = []
    for path in Path(ACQUISITION_RUNS_DIR).glob("run_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("status") == "success":
                manifests.append((data.get("triggered_at", ""), data))
        except (OSError, json.JSONDecodeError):
            continue

    if not manifests:
        raise RuntimeError("No successful acquisition manifest found.")

    return max(manifests, key=lambda item: item[0])[1]


def main():
    if not INPUT.exists():
        raise FileNotFoundError(f"Missing input: {INPUT}")

    gdf = gpd.read_file(INPUT)
    if gdf.empty or gdf.crs is None:
        raise RuntimeError("Input polygons are empty or have no CRS.")

    required = {"deforestation_probability", "area_ha"}
    missing = required - set(gdf.columns)
    if missing:
        raise RuntimeError(f"Missing fields: {sorted(missing)}")

    # Isolated software test using only 10 polygons.
    sample = gdf.head(10).copy()
    run_tag = uuid.uuid4().hex[:8]

    sample["polygon_id"] = [
        f"SUP-RFTEST-{run_tag}-{i:03d}"
        for i in range(1, len(sample) + 1)
    ]
    sample["prediction"] = "deforestation"

    # Calculate centroids in a projected CRS.
    metric = sample.to_crs("EPSG:32643")
    centroids = metric.geometry.centroid.to_crs("EPSG:4326")
    sample["centroid_lon"] = centroids.x
    sample["centroid_lat"] = centroids.y

    acquisition = latest_successful_acquisition()
    base_year = acquisition["base_year"]
    comparison_year = acquisition["comparison_year"]

    ROOT.mkdir(parents=True, exist_ok=True)
    boundary_input = ROOT / f"rf_test_input_{run_tag}.geojson"

    sample[
        [
            "polygon_id",
            "prediction",
            "deforestation_probability",
            "area_ha",
            "centroid_lon",
            "centroid_lat",
            "geometry",
        ]
    ].to_file(boundary_input, driver="GeoJSON")

    polygon_manifest = {
        "run_id": run_tag,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "source": "supervised_random_forest_isolated_test",
        "base_year": base_year,
        "comparison_year": comparison_year,
        "geojson_path": str(boundary_input.resolve()),
    }

    print(f"Testing {len(sample)} polygons; run tag: {run_tag}")

    result = run_boundary_check(
        polygon_manifest=polygon_manifest,
        acquisition_manifest=acquisition,
        output_suffix=f"rf-test-{run_tag}",
    )

    print("\nISOLATED MODULE 6 TEST COMPLETE")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
