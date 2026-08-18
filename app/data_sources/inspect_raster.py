"""
Raster inspector for Module 1.

Purpose: when a dataset's role isn't obvious from its filename alone (like
Forest_Sample_2023/2025 - 26 bands, float64, ~750MB), this pulls real
metadata instead of guessing: band count, per-band descriptions/tags,
CRS, resolution, extent, dtype, and an approximate value range per band
(computed from a downsampled read, so it stays fast even on large files).

This is read-only and does not modify or move any file. It does not
assign the dataset to a pipeline module - that decision is made by a
human (you) after reading the report.

Usage:
    python -m app.data_sources.inspect_raster <path_to_tif>
"""

import os
import sys
import json
import numpy as np
import rasterio


def _approx_band_stats(src, band_index, window_size=400, num_windows=3):
    """Read a few small windows (not the whole band) to compute approximate
    min/max/mean/std quickly, regardless of how large the raster is.

    This avoids rasterio/GDAL having to decode the entire full-resolution
    band just to downsample it (which is what made the original
    out_shape+resampling approach slow on large files without overviews).
    """
    import rasterio.windows as rio_windows

    w = min(window_size, src.width)
    h = min(window_size, src.height)

    # Sample a few fixed spots: center, and two offset points.
    candidate_origins = [
        (max(0, src.width // 2 - w // 2), max(0, src.height // 2 - h // 2)),
        (max(0, src.width // 4 - w // 2), max(0, src.height // 4 - h // 2)),
        (max(0, 3 * src.width // 4 - w // 2), max(0, 3 * src.height // 4 - h // 2)),
    ][:num_windows]

    chunks = []
    for col_off, row_off in candidate_origins:
        window = rio_windows.Window(col_off, row_off, w, h)
        chunk = src.read(band_index, window=window)
        chunks.append(chunk)

    data = np.concatenate([c.ravel() for c in chunks])

    nodata = src.nodata
    if nodata is not None:
        data = data[data != nodata]

    valid = data[np.isfinite(data)]
    if valid.size == 0:
        return {"min": None, "max": None, "mean": None, "std": None, "note": "no valid pixels sampled"}

    return {
        "min": float(np.min(valid)),
        "max": float(np.max(valid)),
        "mean": float(np.mean(valid)),
        "std": float(np.std(valid)),
        "sampled_pixels": int(valid.size),
    }


def _classify_band_guess(stats):
    """Heuristic only - flags a likely category based on value range.
    This is a suggestion for a human to confirm, not a final answer."""
    if stats["min"] is None:
        return "unknown (no valid data sampled)"

    lo, hi = stats["min"], stats["max"]

    if -1.05 <= lo <= 1.05 and -1.05 <= hi <= 1.05:
        return "possible vegetation index (e.g. NDVI-like, range ~[-1, 1])"
    if lo >= 0 and hi <= 1.0:
        return "possible normalized index or reflectance (range [0, 1])"
    if lo >= 0 and hi <= 255 and float(lo).is_integer() and float(hi).is_integer():
        return "possible raw digital number / classification label (integer-like, [0, 255])"
    if lo >= 0 and hi > 1000:
        return "possible raw Sentinel-2 surface reflectance (scaled digital numbers)"

    return "unclear from value range alone"


def inspect_raster(path, window_size=400):
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    report = {
        "path": path,
        "file_size_bytes": os.path.getsize(path),
    }

    with rasterio.open(path) as src:
        report["crs"] = str(src.crs) if src.crs else None
        report["width"] = src.width
        report["height"] = src.height
        report["band_count"] = src.count
        report["resolution"] = {"x": src.res[0], "y": src.res[1]}
        report["bounds"] = {
            "left": src.bounds.left,
            "bottom": src.bounds.bottom,
            "right": src.bounds.right,
            "top": src.bounds.top,
        }
        report["dataset_tags"] = src.tags()  # file-level metadata tags, if any

        band_reports = []
        for i in range(1, src.count + 1):
            band_info = {
                "band_index": i,
                "description": src.descriptions[i - 1],  # None if not set
                "dtype": src.dtypes[i - 1],
                "tags": src.tags(i),  # band-level tags, if any
            }
            stats = _approx_band_stats(src, i, window_size=window_size)
            band_info["approx_stats"] = stats
            band_info["heuristic_guess"] = _classify_band_guess(stats)
            band_reports.append(band_info)

        report["bands"] = band_reports

    return report


def print_report(report):
    print("\nRaster Inspection Report")
    print("=" * 60)
    print(f"File:       {report['path']}")
    print(f"Size:       {report['file_size_bytes'] / (1024**2):.1f} MB")
    print(f"CRS:        {report['crs']}")
    print(f"Dimensions: {report['width']} x {report['height']}")
    print(f"Resolution: {report['resolution']['x']}, {report['resolution']['y']}")
    print(f"Bounds:     {report['bounds']}")
    print(f"Band count: {report['band_count']}")
    if report["dataset_tags"]:
        print(f"File-level tags: {report['dataset_tags']}")
    print("-" * 60)

    for b in report["bands"]:
        desc = b["description"] or "(no description set)"
        print(f"Band {b['band_index']:2}: {desc}  dtype={b['dtype']}")
        if b["tags"]:
            print(f"          tags: {b['tags']}")
        s = b["approx_stats"]
        if s["min"] is not None:
            print(f"          approx range: [{s['min']:.4f}, {s['max']:.4f}]  "
                  f"mean={s['mean']:.4f}  std={s['std']:.4f}")
        print(f"          heuristic guess: {b['heuristic_guess']}")

    print("=" * 60)
    print("NOTE: heuristic guesses are based on value ranges only.")
    print("Please review band descriptions/tags above and confirm manually.\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m app.data_sources.inspect_raster <path_to_tif>")
        sys.exit(1)

    path = sys.argv[1]
    report = inspect_raster(path)
    print_report(report)

    out_path = os.path.splitext(path)[0] + "_inspection.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Full report saved to: {out_path}")
