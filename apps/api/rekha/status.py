from __future__ import annotations

from rekha.paths import ARTIFACTS_DIR


def eval_artifact_path():
    return ARTIFACTS_DIR / "eval" / "latest.json"
