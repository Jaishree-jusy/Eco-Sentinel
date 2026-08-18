"""
Band-name resolution - reads a raster's own band descriptions to find
which index a named band lives at, instead of trusting a fixed global
config constant.

Required because historical Forest_Sample files (26 bands, full Sentinel-2
order) and live GEE-acquired files (fewer bands, only what the pipeline
actually needs) have different band layouts. Both set real band
descriptions (historical: from the original product; live: stamped by
gee_client.py after download), so resolving by name works for either.
"""


class BandNotFoundError(Exception):
    pass


def resolve_band_indices(src, band_names, required=True):
    """src: an open rasterio dataset. band_names: list of band name strings
    to look up (e.g. ["B8", "B4", "SCL"]).

    Returns {band_name: 1-based_index}. If required=True, raises
    BandNotFoundError listing what's missing rather than returning a
    partial/ambiguous result silently.
    """
    descriptions = src.descriptions  # tuple, 0-indexed, may contain None
    name_to_index = {}
    for i, desc in enumerate(descriptions, start=1):
        if desc:
            name_to_index[desc] = i

    result = {}
    missing = []
    for name in band_names:
        if name in name_to_index:
            result[name] = name_to_index[name]
        else:
            missing.append(name)

    if missing and required:
        raise BandNotFoundError(
            f"Band(s) {missing} not found in {src.name}. "
            f"Available bands: {list(name_to_index.keys())}"
        )

    return result


def resolve_band_index_with_fallback(src, candidates):
    """Tries each name in candidates in order, returns the first one found.
    Used where a band might be named differently depending on the file's
    source (e.g. TCI_R on historical files vs B4 on live GEE files, both
    being 'red' for true-color purposes)."""
    descriptions = src.descriptions
    name_to_index = {desc: i for i, desc in enumerate(descriptions, start=1) if desc}
    for name in candidates:
        if name in name_to_index:
            return name, name_to_index[name]
    raise BandNotFoundError(
        f"None of {candidates} found in {src.name}. Available: {list(name_to_index.keys())}"
    )
