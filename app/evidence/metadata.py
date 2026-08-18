"""
JSON Metadata generation - Module 8.
"""

import json
from datetime import datetime, timezone


def build_and_write_metadata(alert, evidence_paths, output_path):
    metadata = {
        **alert,
        "evidence_generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_files": evidence_paths,
    }
    with open(output_path, "w") as f:
        json.dump(metadata, f, indent=2)
    return output_path
