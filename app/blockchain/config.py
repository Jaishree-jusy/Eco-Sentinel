"""
Configuration for Module 9 - Blockchain Integrity Layer.
"""

import os
from app.config import BLOCKCHAIN_DIR

LEDGER_PATH = os.path.join(BLOCKCHAIN_DIR, "ledger.jsonl")

GENESIS_HASH = "0" * 64

# Fixed order in which evidence files are combined into the content hash.
# Must stay consistent between recording and verification, or hashes
# will never match even for unmodified files.
EVIDENCE_FILE_ORDER = ["pdf_report", "geojson", "map_snapshot", "metadata"]
