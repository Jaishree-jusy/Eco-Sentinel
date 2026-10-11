"""
Real Google Earth Engine acquisition client - Module 2.

Uses COPERNICUS/S2_SR_HARMONIZED.

Authentication:
    earthengine authenticate

The project only downloads the bands required by the downstream
pipeline.

Because Earth Engine getDownloadURL() has a hard per-request size
limit, the AOI is divided into tiles and mosaicked locally.
"""

import os
import requests

try:
    import ee
except ImportError:
    ee = None


COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"

BAND_SET = [
    "B1",
    "B2",
    "B3",
    "B4",
    "B5",
    "B6",
    "B7",
    "B8",
    "B8A",
    "B9",
    "B11",
    "B12",
    "SCL",
]

CLOUD_PROPERTY = "CLOUDY_PIXEL_PERCENTAGE"

# Six columns × six rows = 36 requests.
DOWNLOAD_TILE_GRID = (6, 6)


class GEEAuthenticationError(Exception):
    pass


class GEEAcquisitionError(Exception):
    pass

def initialize_earth_engine(project=None):
    """Initialize Earth Engine using locally stored credentials.

    Args:
        project: GEE project ID string. If None, uses the GEE_PROJECT_ID
                 from acquisition config. Explicitly pass a different project
                 for isolated tests.
    """

    if ee is None:
        raise GEEAuthenticationError(
            "earthengine-api is not installed. "
            "Run: pip install earthengine-api"
        )

    from app.acquisition.config import GEE_PROJECT_ID
    resolved_project = project or GEE_PROJECT_ID

    try:
        ee.Initialize(project=resolved_project)
    except Exception as e:
        raise GEEAuthenticationError(
            "Earth Engine initialization failed. "
            f"Project: {resolved_project!r}. "
            "Ensure credentials are valid (run: earthengine authenticate) "
            "and the project ID in app/acquisition/config.py is correct.\n\n"
            f"(Original error: {e})"
        )


def _bbox_to_ee_geometry(bbox):
    return ee.Geometry.Rectangle(
        [
            bbox["left"],
            bbox["bottom"],
            bbox["right"],
            bbox["top"],
        ]
    )


def find_best_image(
    bbox,
    start_date,
    end_date,
    max_cloud_cover_pct,
):
    """
    Find the NEWEST, best-covering suitable Sentinel-2 image.

    Selection strategy (in priority order):
      1. Restrict to the supplied AOI, date window, and max cloud threshold.
      2. Among qualifying images, identify the newest acquisition timestamp
         (newest by system:time_start milliseconds, descending).
      3. Among all images sharing that newest timestamp (same overpass,
         different MGRS granules), select the one with the highest
         AOI coverage fraction.

    This avoids selecting a small adjacent granule (e.g. T43PDP, ~15% of
    the AOI) when a co-temporal granule covers it much better (e.g.
    T43PDQ, ~97%).

    Returns:
        (metadata, ee_image)

    metadata is JSON serializable and includes:
        - gee_image_id
        - acquisition_date (ms since epoch)
        - cloud_cover_pct
        - aoi_coverage_pct  (fraction of the AOI covered by this granule, 0–100)
        - selection_reason  (human-readable explanation of why this was chosen)

    ee_image is the actual Earth Engine object (use for downloads only).

    Returns (None, None) if no qualifying image is found.
    """

    region = _bbox_to_ee_geometry(bbox)
    region_area = region.area(1).getInfo()

    collection = (
        ee.ImageCollection(COLLECTION)
        .filterBounds(region)
        .filterDate(start_date, end_date)
        .filter(
            ee.Filter.lte(
                CLOUD_PROPERTY,
                max_cloud_cover_pct,
            )
        )
        # Newest acquisition first.
        .sort("system:time_start", False)
    )

    count = collection.size().getInfo()

    if count == 0:
        return None, None

    if count == 1:
        # Fast path: only one candidate.
        image = collection.first()
        info = image.getInfo()
        props = info["properties"]

        img_geom = image.geometry()
        inter_area = region.intersection(img_geom, 1).area(1).getInfo()
        coverage_pct = (inter_area / region_area * 100) if region_area > 0 else 0.0

        metadata = {
            "gee_image_id": info["id"],
            "acquisition_date": props.get("system:time_start"),
            "cloud_cover_pct": props.get(CLOUD_PROPERTY),
            "aoi_coverage_pct": round(coverage_pct, 2),
            "selection_reason": "only qualifying image in window",
        }
        return metadata, image

    # -------------------------------------------------------------------
    # Multiple candidates: find the newest timestamp, then pick the
    # granule with the highest AOI coverage among same-timestamp images.
    # -------------------------------------------------------------------

    # Fetch the first image to get the newest timestamp.
    newest_image = collection.first()
    newest_info = newest_image.getInfo()
    newest_ts = newest_info["properties"].get("system:time_start")

    # Fetch all images sharing the same timestamp (same overpass).
    img_list = collection.toList(50)
    list_size = img_list.size().getInfo()

    best_image = None
    best_coverage_pct = -1.0
    best_info = None

    for i in range(list_size):
        img = ee.Image(img_list.get(i))
        info = img.getInfo()
        ts = info["properties"].get("system:time_start")

        # Stop when we move past the newest timestamp group.
        if ts != newest_ts:
            break

        img_geom = img.geometry()
        inter_area = region.intersection(img_geom, 1).area(1).getInfo()
        coverage_pct = (inter_area / region_area * 100) if region_area > 0 else 0.0

        if coverage_pct > best_coverage_pct:
            best_coverage_pct = coverage_pct
            best_image = img
            best_info = info

    if best_image is None:
        # Fallback: return the newest image without coverage filter.
        best_image = newest_image
        best_info = newest_info
        best_coverage_pct = 0.0

    props = best_info["properties"]

    metadata = {
        "gee_image_id": best_info["id"],
        "acquisition_date": props.get("system:time_start"),
        "cloud_cover_pct": props.get(CLOUD_PROPERTY),
        "aoi_coverage_pct": round(best_coverage_pct, 2),
        "selection_reason": (
            "highest AOI coverage among co-temporal granules"
            if list_size > 1
            else "only qualifying image in window"
        ),
    }

    return metadata, best_image



def _compute_tile_bboxes(
    bbox,
    grid=DOWNLOAD_TILE_GRID,
):
    """Split the AOI into non-overlapping tiles."""

    cols, rows = grid

    left = bbox["left"]
    bottom = bbox["bottom"]
    right = bbox["right"]
    top = bbox["top"]

    width = (right - left) / cols
    height = (top - bottom) / rows

    tiles = []

    for row in range(rows):
        for col in range(cols):
            tile_left = left + col * width
            tile_right = tile_left + width

            tile_bottom = bottom + row * height
            tile_top = tile_bottom + height

            tiles.append(
                {
                    "left": tile_left,
                    "bottom": tile_bottom,
                    "right": tile_right,
                    "top": tile_top,
                }
            )

    return tiles


def _download_single_tile(
    image,
    tile_bbox,
    scale,
    session,
):
    """Download one small GEE tile."""

    region = _bbox_to_ee_geometry(tile_bbox)

    url = image.getDownloadURL(
        {
            "region": region,
            "scale": scale,
            "format": "GEO_TIFF",
        }
    )

    response = session.get(
        url,
        timeout=300,
    )

    if response.status_code != 200:
        raise GEEAcquisitionError(
            "Earth Engine tile download failed "
            f"(HTTP {response.status_code}): "
            f"{response.text[:300]}"
        )

    return response.content


def download_image(
    image,
    bbox,
    output_path,
    scale=10,
    tile_grid=DOWNLOAD_TILE_GRID,
):
    """
    Download the selected Sentinel-2 bands.

    The AOI is divided into smaller requests and then mosaicked
    locally into one GeoTIFF.

    The normal production caller passes the raw ee.Image.

    For backward compatibility with existing tests, this function
    also accepts:
        {"_ee_image": image}
    """

    import tempfile

    import rasterio

    from rasterio.merge import merge

    # ---------------------------------------------------------
    # Compatibility with the older test/helper interface.
    # ---------------------------------------------------------

    if isinstance(image, dict) and "_ee_image" in image:
        image = image["_ee_image"]

    # ---------------------------------------------------------
    # Select only required bands.
    # ---------------------------------------------------------

    image = image.select(BAND_SET)

    tile_bboxes = _compute_tile_bboxes(
        bbox,
        tile_grid,
    )

    os.makedirs(
        os.path.dirname(output_path),
        exist_ok=True,
    )

    with tempfile.TemporaryDirectory() as tmp_dir:

        tile_paths = []

        with requests.Session() as session:

            for i, tile_bbox in enumerate(tile_bboxes):

                tile_bytes = _download_single_tile(
                    image,
                    tile_bbox,
                    scale,
                    session,
                )

                tile_path = os.path.join(
                    tmp_dir,
                    f"tile_{i:03d}.tif",
                )

                with open(tile_path, "wb") as f:
                    f.write(tile_bytes)

                tile_paths.append(tile_path)

        # -----------------------------------------------------
        # Mosaic tiles locally.
        # -----------------------------------------------------

        tile_datasets = [
            rasterio.open(path)
            for path in tile_paths
        ]

        try:
            mosaic, mosaic_transform = merge(
                tile_datasets
            )

            profile = (
                tile_datasets[0]
                .profile
                .copy()
            )

        finally:
            for dataset in tile_datasets:
                dataset.close()

        profile.update(
            height=mosaic.shape[1],
            width=mosaic.shape[2],
            transform=mosaic_transform,
            count=mosaic.shape[0],
        )

        # -----------------------------------------------------
        # Write final mosaic.
        # -----------------------------------------------------

        with rasterio.open(
            output_path,
            "w",
            **profile,
        ) as dst:

            dst.write(mosaic)

            for i, band_name in enumerate(
                BAND_SET,
                start=1,
            ):
                dst.set_band_description(
                    i,
                    band_name,
                )

    return output_path