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


def initialize_earth_engine():
    """Initialize Earth Engine using locally stored credentials."""

    if ee is None:
        raise GEEAuthenticationError(
            "earthengine-api is not installed. "
            "Run: pip install earthengine-api"
        )

    try:
        ee.Initialize()
    except Exception as e:
        raise GEEAuthenticationError(
            "Earth Engine is not authenticated on this machine. "
            "Run:\n\n"
            "    earthengine authenticate\n\n"
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
    Find the NEWEST suitable Sentinel-2 image.

    The search is restricted to:
      - the supplied AOI
      - the supplied date window
      - the supplied maximum cloud-cover threshold

    Among qualifying images, the newest acquisition is selected.

    Returns:
        (metadata, ee_image)

    metadata is JSON serializable.
    ee_image is the actual Earth Engine object and must never be
    written into a manifest.
    """

    region = _bbox_to_ee_geometry(bbox)

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
        # IMPORTANT:
        # Newest acquisition first.
        .sort("system:time_start", False)
    )

    count = collection.size().getInfo()

    if count == 0:
        return None, None

    image = collection.first()

    info = image.getInfo()

    metadata = {
        "gee_image_id": info["id"],
        "acquisition_date": info["properties"].get(
            "system:time_start"
        ),
        "cloud_cover_pct": info["properties"].get(
            CLOUD_PROPERTY
        ),
    }

    return metadata, image


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