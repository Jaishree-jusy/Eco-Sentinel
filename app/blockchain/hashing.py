"""
Hashing utilities - Module 9.
"""

import hashlib


def compute_file_hash(path, chunk_size=8192):
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def compute_combined_hash(file_paths):
    """Hashes multiple files together as one continuous stream, in the
    order given. Order must be consistent between calls - the caller is
    responsible for that (see EVIDENCE_FILE_ORDER in config.py)."""
    sha256 = hashlib.sha256()
    for path in file_paths:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
    return sha256.hexdigest()
