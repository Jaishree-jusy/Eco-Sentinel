"""
CLI for Module 1 - Data Sources & Ingestion.

Usage (from the eco-sentinel/ project root):

    python -m app.data_sources.cli validate

This validates every dataset in the registry against the real files you've
placed under data/raw_images/, writes data/data_catalog.json, and prints a
pass/fail summary to the console.
"""

import sys
import argparse

from app.data_sources.catalog import build_catalog, save_catalog


def _print_summary(catalog):
    print("\nECO-SENTINEL - Module 1: Data Source Validation")
    print("=" * 55)

    for key, record in catalog["datasets"].items():
        status = "OK" if record["valid"] else "FAIL"
        print(f"[{status:4}] {key:22} -> {record['filename']}")
        if not record["exists"]:
            print(f"         Not found at: {record['path']}")
        for err in record["errors"]:
            print(f"         ERROR: {err}")
        for warn in record["warnings"]:
            print(f"         WARNING: {warn}")

    print("-" * 55)
    crs_check = catalog["raster_crs_consistency"]
    if crs_check["consistent"]:
        print("Raster CRS consistency: OK (all rasters share one CRS)")
    else:
        print("Raster CRS consistency: WARNING - mismatched CRS values:")
        for k, crs in crs_check["crs_by_dataset"].items():
            print(f"    {k}: {crs}")

    s = catalog["summary"]
    print("-" * 55)
    print(f"Total datasets: {s['total_datasets']}  "
          f"Valid: {s['valid']}  Invalid: {s['invalid']}  Missing: {s['missing']}")
    print("=" * 55 + "\n")


def main():
    parser = argparse.ArgumentParser(description="ECO-SENTINEL Module 1 CLI")
    parser.add_argument(
        "command",
        choices=["validate"],
        help="validate: check all datasets and (re)generate data_catalog.json",
    )
    args = parser.parse_args()

    if args.command == "validate":
        catalog = build_catalog()
        _print_summary(catalog)
        path = save_catalog(catalog)
        print(f"Catalog written to: {path}")

        if catalog["summary"]["invalid"] > 0 or catalog["summary"]["missing"] > 0:
            sys.exit(1)  # non-zero exit so CI / scripts can detect failure


if __name__ == "__main__":
    main()
