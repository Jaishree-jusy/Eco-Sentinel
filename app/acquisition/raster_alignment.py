"""
Raster grid alignment - Module 2.

Live GEE-acquired imagery is downloaded/mosaicked through a different
process than the historical baseline files, so there's no guarantee the
two share an exact pixel grid even when they cover the same nominal AOI.
Every downstream module assumes pixel-perfect alignment between base and
comparison rasters - true by construction for the two original historical
files, never actually enforced for anything else.

Reprojects a source raster onto a reference raster's EXACT grid (same
transform, width, height, CRS), band by band, preserving band
descriptions so downstream name-based band lookup keeps working.
"""

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling


def needs_alignment(src_path, reference_path):
    """True if src and reference don't already share an identical grid -
    lets the caller skip a real but unnecessary reprojection pass when
    the two files already line up exactly."""
    with rasterio.open(src_path) as src, rasterio.open(reference_path) as ref:
        return (
            src.transform != ref.transform
            or src.width != ref.width
            or src.height != ref.height
            or src.crs != ref.crs
        )


def align_to_reference(src_path, reference_path, output_path, resampling=Resampling.bilinear):
    """Reprojects src_path onto reference_path's exact grid. SCL (a
    categorical band) is always nearest-neighbor resampled regardless of
    the resampling arg - interpolating class codes would corrupt them
    into meaningless fractional values."""
    with rasterio.open(reference_path) as ref_src:
        ref_transform = ref_src.transform
        ref_crs = ref_src.crs
        ref_width = ref_src.width
        ref_height = ref_src.height

    with rasterio.open(src_path) as src:
        band_count = src.count
        band_descriptions = src.descriptions
        dst_profile = src.profile.copy()
        dst_profile.update(transform=ref_transform, crs=ref_crs, width=ref_width, height=ref_height)

        with rasterio.open(output_path, "w", **dst_profile) as dst:
            for band_idx in range(1, band_count + 1):
                source_band = src.read(band_idx)
                dest_band = np.zeros((ref_height, ref_width), dtype=source_band.dtype)

                band_name = band_descriptions[band_idx - 1] if band_idx - 1 < len(band_descriptions) else None
                band_resampling = Resampling.nearest if band_name == "SCL" else resampling

                reproject(
                    source=source_band, destination=dest_band,
                    src_transform=src.transform, src_crs=src.crs,
                    dst_transform=ref_transform, dst_crs=ref_crs,
                    resampling=band_resampling,
                )

                dst.write(dest_band, band_idx)
                if band_name:
                    dst.set_band_description(band_idx, band_name)

    return output_path
