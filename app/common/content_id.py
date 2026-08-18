"""
Stable, content-derived ID generation.

Used by Module 5 (polygon_id) and Module 7 (alert_id) so that rerunning
the pipeline against the same underlying data always produces the same
IDs - never IDs that depend on array/GeoDataFrame row order, which can
silently shift between runs even when nothing meaningful changed.

This is intentionally the ONLY place this logic lives, so both modules
stay consistent with each other by construction.
"""

import hashlib


def stable_id(*parts, prefix="", length=12):
    """Deterministic ID derived from the given parts' content.

    Same parts -> same ID, always, regardless of when or how many times
    this is called, or what order other items were processed in.
    Different parts -> (for all practical purposes) a different ID.
    """
    joined = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}{digest}" if prefix else digest
