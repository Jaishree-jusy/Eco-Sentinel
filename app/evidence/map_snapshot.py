"""
Map Snapshot generation - Module 8.

Crops a true-color image around each alert's polygon using the TCI (True
Color Image) bands from the raw Sentinel-2 imagery, overlays the polygon
outline, and saves it as a PNG. This uses windowed reads, so it stays fast
regardless of the source file's overall size.
"""

import numpy as np
import rasterio
import rasterio.windows
from rasterio.transform import array_bounds
import matplotlib
matplotlib.use("Agg")  # no display needed - just saving files
import matplotlib.pyplot as plt

from app.evidence.config import MIN_SNAPSHOT_PIXELS, BASE_BUFFER_DEG
from app.gee_processing.band_resolver import resolve_band_index_with_fallback

# Historical Forest_Sample files have pre-rendered true-color TCI bands.
# Live GEE-acquired files don't (TCI is a visualization product, not a
# native band) - B4/B3/B2 (Red/Green/Blue) are the real true-color
# equivalent, so each channel tries its TCI name first, falls back to the
# raw band.
RED_CANDIDATES = ["TCI_R", "B4"]
GREEN_CANDIDATES = ["TCI_G", "B3"]
BLUE_CANDIDATES = ["TCI_B", "B2"]


def _compute_adaptive_buffer(geometry, pixel_size, base_buffer=BASE_BUFFER_DEG, min_pixels=MIN_SNAPSHOT_PIXELS):
    """Ensures the snapshot window is at least min_pixels wide/tall, even
    for a tiny polygon, by growing the buffer as needed."""
    minx, miny, maxx, maxy = geometry.bounds
    width_deg = maxx - minx
    height_deg = maxy - miny

    min_size_deg = min_pixels * pixel_size

    buffer_x = max(base_buffer, (min_size_deg - width_deg) / 2)
    buffer_y = max(base_buffer, (min_size_deg - height_deg) / 2)

    return buffer_x, buffer_y


def generate_map_snapshot(src, geometry, output_path):
    """src: an already-open rasterio dataset (caller manages open/close -
    avoids reopening a large file for every single alert)."""
    pixel_size = src.res[0]
    buffer_x, buffer_y = _compute_adaptive_buffer(geometry, pixel_size)

    minx, miny, maxx, maxy = geometry.bounds
    minx -= buffer_x
    maxx += buffer_x
    miny -= buffer_y
    maxy += buffer_y

    window = rasterio.windows.from_bounds(minx, miny, maxx, maxy, transform=src.transform)
    window = window.round_offsets().round_lengths()

    red_name, red_idx = resolve_band_index_with_fallback(src, RED_CANDIDATES)
    green_name, green_idx = resolve_band_index_with_fallback(src, GREEN_CANDIDATES)
    blue_name, blue_idx = resolve_band_index_with_fallback(src, BLUE_CANDIDATES)

    r = src.read(red_idx, window=window)
    g = src.read(green_idx, window=window)
    b = src.read(blue_idx, window=window)

    rgb = np.stack([r, g, b], axis=-1).astype("float64")
    rgb = np.nan_to_num(rgb, nan=0.0)

    if red_name == "TCI_R":
        # TCI bands are pre-rendered for display, already roughly 0-255.
        pass
    else:
        # Raw B4/B3/B2 surface reflectance is typically in the low
        # thousands (Sentinel-2's 10000 = reflectance 1.0 convention), not
        # 0-255 - needs a visualization stretch, or the image would just
        # come out solid white after a naive clip.
        rgb = (rgb / 3000.0) * 255.0

    rgb = np.clip(rgb, 0, 255).astype("uint8")

    win_transform = src.window_transform(window)
    left, bottom, right, top = array_bounds(rgb.shape[0], rgb.shape[1], win_transform)

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.imshow(rgb, extent=(left, right, bottom, top), origin="upper")

    # Overlay the polygon outline so the exact loss boundary is visible
    if geometry.geom_type == "Polygon":
        exteriors = [geometry.exterior]
    else:  # MultiPolygon
        exteriors = [g.exterior for g in geometry.geoms]
    for ext in exteriors:
        xs, ys = ext.xy
        ax.plot(xs, ys, color="red", linewidth=1.5)

    ax.set_xlim(left, right)
    ax.set_ylim(bottom, top)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("Vegetation Loss Area - Satellite Snapshot", fontsize=9)

    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return output_path
