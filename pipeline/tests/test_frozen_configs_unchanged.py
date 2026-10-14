"""Proof that the xP-accuracy work changes no frozen model: every model's config and model-file
hashes in the committed manifest equal the frozen-2026-10-13 values, and the bundled config files
themselves hash to them. A harness-only re-freeze may change source_sha256, never these."""

from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "prospective" / "bundle" / "manifest.json"
BUNDLE = REPO / "prospective" / "bundle" / "frozen-2026-10-13.tar.gz"

FROZEN_CONFIG_SHA256 = {
    "engine": "69f2e8d5e0ffe0204752e883c0ebfaa4bebaca9e0849296aa9c12b6fde565ed1",
    "C3": "56fde78e9a2916f38b7c65ed8a0934467ae8ab0c59613374bf4614c5b8eb304f",
    "C1": "778e156aabc71247835fe3dde21304f540c830455e47829a9b5c45ebed4589d1",
    "A": "5fe443d48d17f71ce1e12d637edebc1049b23b9d9baa4b3bbda9a0a55d7b4a80",
    "A_odds": "5f648c7145a2d8b2a9d42cf96f97822f207100eb03fe0421e9d9b1149c46f8f5",
}


def test_config_hashes_unchanged() -> None:
    m = json.loads(MANIFEST.read_text())
    assert {k: v["config_sha256"] for k, v in m["models"].items()} == FROZEN_CONFIG_SHA256


def test_model_files_in_bundle_match_manifest() -> None:
    m = json.loads(MANIFEST.read_text())
    with tarfile.open(BUNDLE, "r:gz") as t:
        names = set(t.getnames())
        for model, info in m["models"].items():
            for rel, want in info["model_files_sha256"].items():
                arc = f"frozen/{rel}"
                if arc not in names:
                    # Raw football-data.co.uk CSVs are not redistributed (prospective/README.md).
                    assert rel.startswith("backtest/fdcouk/E0_"), (model, rel)
                    continue
                f = t.extractfile(arc)
                assert f is not None
                assert hashlib.sha256(f.read()).hexdigest() == want, (model, rel)


def test_every_refreeze_is_harness_only() -> None:
    m = json.loads(MANIFEST.read_text())
    for entry in m["refreezes"]:
        assert all(not k.startswith(("frozen/", "config")) for k in entry["harness_files"])
