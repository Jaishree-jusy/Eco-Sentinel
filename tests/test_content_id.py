"""
Tests for app.common.content_id - the stable, content-derived ID utility
used by both Module 5 (polygon_id) and Module 7 (alert_id).
"""

from app.common.content_id import stable_id


def test_stable_id_deterministic():
    id1 = stable_id(74.9, 12.85, 2023, 2025)
    id2 = stable_id(74.9, 12.85, 2023, 2025)
    assert id1 == id2


def test_stable_id_differs_for_different_input():
    id1 = stable_id(74.9, 12.85, 2023, 2025)
    id2 = stable_id(74.9, 12.86, 2023, 2025)  # tiny lat difference
    assert id1 != id2


def test_stable_id_prefix_applied():
    result = stable_id("x", prefix="LOSS-")
    assert result.startswith("LOSS-")


def test_stable_id_length_respected():
    result = stable_id("x", length=8)
    assert len(result) == 8
