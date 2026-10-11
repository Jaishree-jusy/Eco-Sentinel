"""
Module 9 pipeline orchestration.
"""

import os
import json
import glob
import uuid
from datetime import datetime, timezone

from app.config import EVIDENCE_STORE_DIR, BLOCKCHAIN_DIR
from app.blockchain.config import LEDGER_PATH, EVIDENCE_FILE_ORDER
from app.blockchain.contract import SmartContractSimulator
from app.blockchain.hashing import compute_combined_hash


class BlockchainError(Exception):
    pass


def _find_latest_evidence_manifest():
    pattern = os.path.join(
        EVIDENCE_STORE_DIR,
        "evidence_generation_*.json"
    )

    candidates = []

    for path in glob.glob(pattern):
        try:
            with open(path) as f:
                data = json.load(f)

            candidates.append(
                (data["generated_at"], path, data)
            )

        except (json.JSONDecodeError, KeyError):
            continue

    if not candidates:
        raise BlockchainError(
            "No Module 8 evidence-generation manifest found. Run Module 8 "
            "(python -m app.evidence.cli generate) first."
        )

    candidates.sort(key=lambda x: x[0])

    return candidates[-1][2]


def _evidence_file_lookup_from_manifest(evidence_manifest):
    """Build {alert_id: [evidence file paths]} from a Module 8 manifest.

    Uses the manifest paths when they exist. If a manifest contains stale
    absolute paths from an older project location, resolve each file against
    the current evidence-store directory.
    """
    lookup = {}

    for record in evidence_manifest["evidence_records"]:
        alert_id = record["alert_id"]
        file_paths = []

        for key in EVIDENCE_FILE_ORDER:
            path = record[key]

            if os.path.exists(path):
                file_paths.append(path)
            else:
                fallback_path = os.path.join(
                    EVIDENCE_STORE_DIR,
                    alert_id,
                    os.path.basename(path),
                )
                file_paths.append(fallback_path)

        lookup[alert_id] = file_paths

    return lookup


def run_blockchain_recording(evidence_manifest=None):
    if evidence_manifest is None:
        evidence_manifest = _find_latest_evidence_manifest()

    file_lookup = _evidence_file_lookup_from_manifest(evidence_manifest)

    if not file_lookup:
        raise BlockchainError(
            "Evidence manifest has no evidence records to record."
        )

    contract = SmartContractSimulator(LEDGER_PATH)

    # Idempotency guard: once an alert has a block in the chain, never add
    # another one automatically. Without this, running `record` more than
    # once (e.g. after a resumed/rerun evidence-generation pass) silently
    # creates duplicate blocks for the same alert - and since verify_chain
    # checks every block against today's files, an old duplicate recorded
    # against an earlier file state will fail verification forever, even
    # though the alert's current evidence is perfectly fine.
    already_recorded_alert_ids = {
        block["alert_id"] for block in contract.chain
    }

    run_id = str(uuid.uuid4())
    recorded_blocks = []
    skipped_already_recorded = 0

    for alert_id, file_paths in file_lookup.items():

        if alert_id in already_recorded_alert_ids:
            skipped_already_recorded += 1
            continue

        if not all(os.path.exists(p) for p in file_paths):
            raise BlockchainError(
                f"Missing evidence file(s) for {alert_id}: {file_paths}"
            )

        content_hash = compute_combined_hash(file_paths)

        block = contract.add_block(
            alert_id,
            content_hash
        )

        recorded_blocks.append({
            "alert_id": alert_id,
            "block_index": block["block_index"],
            "transaction_hash": block["block_hash"],
            "content_hash": content_hash,
        })

    os.makedirs(
        BLOCKCHAIN_DIR,
        exist_ok=True
    )

    manifest = {
        "run_id": run_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source_evidence_run_id": evidence_manifest.get("run_id"),
        "ledger_path": LEDGER_PATH,
        "chain_length": len(contract.chain),
        "blocks_recorded_this_run": len(recorded_blocks),
        "skipped_already_recorded": skipped_already_recorded,
        "records": recorded_blocks,
    }

    manifest_path = os.path.join(
        BLOCKCHAIN_DIR,
        f"blockchain_recording_{run_id}.json"
    )

    with open(manifest_path, "w") as f:
        json.dump(
            manifest,
            f,
            indent=2
        )

    manifest["manifest_path"] = manifest_path

    return manifest


def run_blockchain_verification(evidence_manifest=None):
    if evidence_manifest is None:
        evidence_manifest = _find_latest_evidence_manifest()

    file_lookup = _evidence_file_lookup_from_manifest(
        evidence_manifest
    )

    contract = SmartContractSimulator(LEDGER_PATH)

    issues = contract.verify_chain(
        evidence_file_lookup=file_lookup
    )

    return {
        "chain_length": len(contract.chain),
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "valid": len(issues) == 0,
        "issues": issues,
    }