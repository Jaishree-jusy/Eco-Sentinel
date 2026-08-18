"""
Tests for Module 9 - Blockchain Integrity Layer.
"""

import os
import json
from app.blockchain.hashing import compute_file_hash, compute_combined_hash
from app.blockchain.contract import SmartContractSimulator
from app.blockchain.config import GENESIS_HASH


def _make_files(tmp_path, contents_list):
    paths = []
    for i, content in enumerate(contents_list):
        path = os.path.join(tmp_path, f"file_{i}.txt")
        with open(path, "w") as f:
            f.write(content)
        paths.append(path)
    return paths


def test_compute_combined_hash_deterministic(tmp_path):
    paths = _make_files(tmp_path, ["hello", "world"])
    hash1 = compute_combined_hash(paths)
    hash2 = compute_combined_hash(paths)
    assert hash1 == hash2
    assert len(hash1) == 64  # sha256 hex digest length


def test_combined_hash_order_matters(tmp_path):
    paths_a = _make_files(tmp_path, ["hello", "world"])
    paths_b = list(reversed(paths_a))
    assert compute_combined_hash(paths_a) != compute_combined_hash(paths_b)


def test_first_block_links_to_genesis(tmp_path):
    ledger_path = os.path.join(tmp_path, "ledger.jsonl")
    contract = SmartContractSimulator(ledger_path)

    block = contract.add_block("ALERT-IN-00001", "somehash")
    assert block["block_index"] == 0
    assert block["previous_block_hash"] == GENESIS_HASH


def test_chain_links_correctly(tmp_path):
    ledger_path = os.path.join(tmp_path, "ledger.jsonl")
    contract = SmartContractSimulator(ledger_path)

    block1 = contract.add_block("ALERT-IN-00001", "hash1")
    block2 = contract.add_block("ALERT-IN-00002", "hash2")

    assert block2["previous_block_hash"] == block1["block_hash"]
    assert block2["block_index"] == 1


def test_ledger_persists_across_instances(tmp_path):
    ledger_path = os.path.join(tmp_path, "ledger.jsonl")

    contract1 = SmartContractSimulator(ledger_path)
    contract1.add_block("ALERT-IN-00001", "hash1")

    # New instance should load the existing chain from disk
    contract2 = SmartContractSimulator(ledger_path)
    assert len(contract2.chain) == 1
    assert contract2.chain[0]["alert_id"] == "ALERT-IN-00001"


def test_verify_chain_valid_when_untampered(tmp_path):
    ledger_path = os.path.join(tmp_path, "ledger.jsonl")
    contract = SmartContractSimulator(ledger_path)

    paths = _make_files(tmp_path, ["evidence content A"])
    content_hash = compute_combined_hash(paths)
    contract.add_block("ALERT-IN-00001", content_hash)

    issues = contract.verify_chain(evidence_file_lookup={"ALERT-IN-00001": paths})
    assert issues == []


def test_verify_chain_detects_tampered_evidence_file(tmp_path):
    """This is the actual point of Module 9 - proving tampering is detectable."""
    ledger_path = os.path.join(tmp_path, "ledger.jsonl")
    contract = SmartContractSimulator(ledger_path)

    paths = _make_files(tmp_path, ["original evidence content"])
    content_hash = compute_combined_hash(paths)
    contract.add_block("ALERT-IN-00001", content_hash)

    # Simulate tampering: someone edits the evidence file after recording
    with open(paths[0], "w") as f:
        f.write("TAMPERED CONTENT")

    issues = contract.verify_chain(evidence_file_lookup={"ALERT-IN-00001": paths})
    assert len(issues) == 1
    assert issues[0]["issue"] == "content_hash mismatch - evidence files were modified since recording"


def test_verify_chain_detects_tampered_ledger_record(tmp_path):
    """Proves editing the ledger file itself (not just evidence) is also detectable."""
    ledger_path = os.path.join(tmp_path, "ledger.jsonl")
    contract = SmartContractSimulator(ledger_path)
    contract.add_block("ALERT-IN-00001", "originalhash")

    # Simulate someone directly editing the ledger file
    with open(ledger_path) as f:
        lines = f.readlines()
    tampered_block = json.loads(lines[0])
    tampered_block["content_hash"] = "maliciously_changed_hash"
    with open(ledger_path, "w") as f:
        f.write(json.dumps(tampered_block) + "\n")

    # Fresh instance reloads the tampered ledger from disk
    contract2 = SmartContractSimulator(ledger_path)
    issues = contract2.verify_chain()
    assert any(i["issue"] == "block_hash mismatch - block record was tampered with" for i in issues)


def test_run_blockchain_recording_is_idempotent(tmp_path, monkeypatch):
    """Regression test for the real bug hit in production: running `record`
    twice on the same evidence must NOT create duplicate blocks. Duplicate
    blocks from an earlier file state cause verify_chain to fail forever,
    even when the current evidence is completely fine."""
    import app.blockchain.pipeline as pipeline_module

    ledger_path = os.path.join(tmp_path, "ledger.jsonl")
    blockchain_dir = os.path.join(tmp_path, "blockchain")
    monkeypatch.setattr(pipeline_module, "LEDGER_PATH", ledger_path)
    monkeypatch.setattr(pipeline_module, "BLOCKCHAIN_DIR", blockchain_dir)

    paths = _make_files(tmp_path, ["evidence content A"])
    evidence_manifest = {
        "run_id": "fake-run",
        "generated_at": "2026-08-06T00:00:00",
        "evidence_records": [
            {"alert_id": "ALERT-IN-00000",
             "map_snapshot": paths[0], "geojson": paths[0],
             "pdf_report": paths[0], "metadata": paths[0]},
        ],
    }
    # EVIDENCE_FILE_ORDER expects 4 keys - point them all at the same file
    # for simplicity, since only dedup behavior is under test here.
    monkeypatch.setattr(pipeline_module, "EVIDENCE_FILE_ORDER",
                         ["map_snapshot", "geojson", "pdf_report", "metadata"])

    manifest1 = pipeline_module.run_blockchain_recording(evidence_manifest)
    assert manifest1["blocks_recorded_this_run"] == 1
    assert manifest1["chain_length"] == 1

    # Run it again against the SAME unchanged evidence - must skip, not duplicate
    manifest2 = pipeline_module.run_blockchain_recording(evidence_manifest)
    assert manifest2["blocks_recorded_this_run"] == 0
    assert manifest2["skipped_already_recorded"] == 1
    assert manifest2["chain_length"] == 1  # still just 1 block, not 2

    # Verification should be clean - no stale duplicate blocks to fail against
    result = pipeline_module.run_blockchain_verification(evidence_manifest)
    assert result["valid"] is True
