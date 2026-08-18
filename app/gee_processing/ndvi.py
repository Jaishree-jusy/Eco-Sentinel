"""
NDVI calculation - Module 3, steps 1-3 combined (cloud masking feeds
directly into NDVI calculation, since a cloud-masked pixel shouldn't
produce a false NDVI value).
"""

import numpy as np
import rasterio

from app.gee_processing.config import NIR_BAND, RED_BAND, SCL_BAND, NDVI_NODATA
from app.gee_processing.band_resolver import resolve_band_indices
from app.gee_processing.cloud_mask import build_cloud_mask


def compute_ndvi_array(nir, red, cloud_mask, nodata_value=NDVI_NODATA):
    """Computes NDVI = (NIR - RED) / (NIR + RED), masking cloud pixels and
    guarding against divide-by-zero. Returns a float32 array."""
    nir = nir.astype("float64")
    red = red.astype("float64")

    denominator = nir + red
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = np.where(denominator != 0, (nir - red) / denominator, nodata_value)

    ndvi = ndvi.astype("float32")
    ndvi[cloud_mask] = nodata_value
    # Guard against any NaN/inf that slipped through
    ndvi[~np.isfinite(ndvi)] = nodata_value

    return ndvi


def compute_ndvi_from_raw(raw_path, output_path):
    """Reads NIR, RED, and SCL bands from a raw Sentinel-2 L2A multiband
    GeoTIFF, applies cloud masking, computes NDVI, and writes a single-band
    float32 GeoTIFF to output_path.

    Returns a dict of stats about this computation (for the run manifest).
    """
    with rasterio.open(raw_path) as src:
        band_idx = resolve_band_indices(src, [NIR_BAND, RED_BAND, SCL_BAND])
        nir = src.read(band_idx[NIR_BAND])
        red = src.read(band_idx[RED_BAND])
        scl = src.read(band_idx[SCL_BAND])

        cloud_mask = build_cloud_mask(scl)
        ndvi = compute_ndvi_array(nir, red, cloud_mask)

        profile = src.profile.copy()
        profile.update(count=1, dtype="float32", nodata=NDVI_NODATA)

        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(ndvi, 1)

    valid = ndvi[ndvi != NDVI_NODATA]
    total_pixels = ndvi.size
    cloud_masked_pixels = int(np.sum(cloud_mask))

    stats = {
        "output_path": output_path,
        "total_pixels": int(total_pixels),
        "cloud_masked_pixels": cloud_masked_pixels,
        "cloud_masked_pct": round(100 * cloud_masked_pixels / total_pixels, 2),
        "valid_pixel_count": int(valid.size),
        "ndvi_min": float(np.min(valid)) if valid.size else None,
        "ndvi_max": float(np.max(valid)) if valid.size else None,
        "ndvi_mean": float(np.mean(valid)) if valid.size else None,
    }
    return stats
