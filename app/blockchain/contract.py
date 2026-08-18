"""
Simulated Smart Contract - Module 9.

Simulates blockchain behavior (append-only, chained, tamper-evident)
using a local JSONL ledger, per your tech stack decision (Python
simulation now, real Ethereum optionally later - swapping the storage
backend wouldn't change this class's public interface).
"""

import os
import json
import hashlib
from datetime import datetime, timezone

from app.blockchain.config import GENESIS_HASH
from app.blockchain.hashing import compute_combined_hash


class SmartContractSimulator:
    def __init__(self, ledger_path):
        self.ledger_path = ledger_path
        self.chain = self._load_chain()

    def _load_chain(self):
        if not os.path.exists(self.ledger_path):
            return []
        chain = []
        with open(self.ledger_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    chain.append(json.loads(line))
        return chain

    def _compute_block_hash(self, block_index, alert_id, content_hash, previous_block_hash, timestamp):
        payload = {
            "block_index": block_index,
            "alert_id": alert_id,
            "content_hash": content_hash,
            "previous_block_hash": previous_block_hash,
            "timestamp": timestamp,
        }
        serialized = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(serialized.encode()).hexdigest()

    def add_block(self, alert_id, content_hash):
        """Appends a new block to the chain and persists it immediately -
        this IS the 'immutable record' step. Existing lines in the ledger
        file are never rewritten, only appended to."""
        block_index = len(self.chain)
        previous_block_hash = self.chain[-1]["block_hash"] if self.chain else GENESIS_HASH
        timestamp = datetime.now(timezone.utc).isoformat()

        block_hash = self._compute_block_hash(
            block_index, alert_id, content_hash, previous_block_hash, timestamp
        )

        block = {
            "block_index": block_index,
            "alert_id": alert_id,
            "content_hash": content_hash,
            "previous_block_hash": previous_block_hash,
            "timestamp": timestamp,
            "block_hash": block_hash,  # this is the "transaction hash"
        }

        self.chain.append(block)
        os.makedirs(os.path.dirname(self.ledger_path), exist_ok=True)
        with open(self.ledger_path, "a") as f:
            f.write(json.dumps(block) + "\n")

        return block

    def verify_chain(self, evidence_file_lookup=None):
        """Walks the entire chain and checks:
        1. Each block's previous_block_hash correctly links to the prior block.
        2. Each block's own block_hash is still correct (wasn't edited).
        3. (If evidence_file_lookup given) each alert's evidence files on
           disk, right now, still hash to the same content_hash recorded
           at the time - this is what actually detects tampered evidence.

        Returns a list of issues found. Empty list = fully valid chain.
        """
        issues = []

        for i, block in enumerate(self.chain):
            expected_prev = self.chain[i - 1]["block_hash"] if i > 0 else GENESIS_HASH
            if block["previous_block_hash"] != expected_prev:
                issues.append({
                    "block_index": i, "alert_id": block["alert_id"],
                    "issue": "previous_block_hash mismatch - chain link broken",
                })

            recomputed_block_hash = self._compute_block_hash(
                block["block_index"], block["alert_id"], block["content_hash"],
                block["previous_block_hash"], block["timestamp"],
            )
            if recomputed_block_hash != block["block_hash"]:
                issues.append({
                    "block_index": i, "alert_id": block["alert_id"],
                    "issue": "block_hash mismatch - block record was tampered with",
                })

            if evidence_file_lookup and block["alert_id"] in evidence_file_lookup:
                file_paths = evidence_file_lookup[block["alert_id"]]
                if all(os.path.exists(p) for p in file_paths):
                    recomputed_content_hash = compute_combined_hash(file_paths)
                    if recomputed_content_hash != block["content_hash"]:
                        issues.append({
                            "block_index": i, "alert_id": block["alert_id"],
                            "issue": "content_hash mismatch - evidence files were modified since recording",
                        })
                else:
                    issues.append({
                        "block_index": i, "alert_id": block["alert_id"],
                        "issue": "one or more evidence files are missing from disk",
                    })

        return issues
