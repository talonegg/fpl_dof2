"""football-data.co.uk inputs for A+odds: the frozen odds history, fetched and hash-verified.

The raw season CSVs are **not** redistributed in this repository. CI downloads them from the
publisher and accepts them only if they are byte-identical to what the model was frozen with (the
manifest's hashes). A changed or unreachable file makes A+odds unavailable; it never substitutes.
The live ``fixtures.csv`` is fetched by the frozen harness itself at decision time.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from fpl_dof.prospective.bundle import sha256_bytes, sha256_file

BASE = "https://www.football-data.co.uk/mmz4281"
#: Bundle-relative path -> source URL. Finished seasons, so the bytes should never change.
HISTORY: dict[str, str] = {
    "backtest/fdcouk/E0_2324.csv": f"{BASE}/2324/E0.csv",
    "backtest/fdcouk/E0_2425.csv": f"{BASE}/2425/E0.csv",
    "backtest/fdcouk/E0_2526.csv": f"{BASE}/2526/E0.csv",
}

Getter = Callable[[str], bytes]


def fetch_history(
    frozen_root: Path, expected: Mapping[str, str], get: Getter
) -> dict[str, str | None]:
    """Place each history CSV under ``frozen_root``; return path -> problem (None when ok).

    A file already present with the frozen hash (e.g. restored from the Actions cache) is not
    re-downloaded — one polite request per file per cache miss, at most.
    """
    out: dict[str, str | None] = {}
    for rel, url in HISTORY.items():
        want = expected.get(rel)
        if want is None:
            out[rel] = "no frozen hash recorded"
            continue
        dest = frozen_root / rel
        if sha256_file(dest) == want:
            out[rel] = None
            continue
        try:
            data = get(url)
        except Exception as exc:
            out[rel] = f"download failed ({type(exc).__name__})"
            continue
        if sha256_bytes(data) != want:
            out[rel] = "upstream file differs from the frozen copy"
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        out[rel] = None
    return out
