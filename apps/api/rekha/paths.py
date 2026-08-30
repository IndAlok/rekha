from pathlib import Path


def _find_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "packages" / "policy").is_dir():
            return parent
    return here.parents[3]


REPO_ROOT = _find_root()
POLICY_DIR = REPO_ROOT / "packages" / "policy"
FIXTURES_DIR = REPO_ROOT / "packages" / "fixtures"
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
