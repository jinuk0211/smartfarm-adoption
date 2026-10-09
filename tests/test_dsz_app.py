"""The onsite demo must never appear as actual private-data model validation."""

import hashlib
import json
from unittest.mock import MagicMock

import pytest

import app


@pytest.mark.parametrize("damage", [None, "actual_data", "failed", "changed_code", "changed_bundle"])
def test_only_matching_synthetic_offline_verification_is_shown(tmp_path, monkeypatch, damage):
    packages = tmp_path / "artifacts" / "dsz_packages"
    packages.mkdir(parents=True)
    archive = packages / "source.zip"
    archive.write_bytes(b"test fixture archive")
    code = tmp_path / "model.py"
    code.write_bytes(b"test source")
    proof = {
        "status": "passed", "data_kind": "synthetic_schema_fixture",
        "verified_files": {"model.py": hashlib.sha256(code.read_bytes()).hexdigest()},
        "source_bundle": "artifacts/dsz_packages/source.zip",
        "source_bundle_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }
    if damage == "actual_data":
        proof["data_kind"] = "onsite_private_unverified"
    elif damage == "failed":
        proof["status"] = "failed"
    elif damage == "changed_code":
        code.write_bytes(b"new source")
    elif damage == "changed_bundle":
        archive.write_bytes(b"other archive")
    (tmp_path / "artifacts" / "dsz_verification.json").write_text(json.dumps(proof), encoding="utf-8")
    ui = MagicMock()
    monkeypatch.setattr(app, "PROJECT", tmp_path)
    monkeypatch.setattr(app, "st", ui)
    app.render_dsz_preparation()
    assert ui.info.call_count == int(damage is None)
    assert ui.download_button.call_count == int(damage is None)
    assert "합성 자료" in ui.caption.call_args_list[0].args[0]
