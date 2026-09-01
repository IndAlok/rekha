from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from rekha import api as api_module
    from rekha.config import settings
    from rekha.db import session as db_session
    from rekha.runtime import FLAGS

    db_file = tmp_path / "rekha_test.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite+pysqlite:///{db_file}")
    monkeypatch.setattr(settings, "rekha_env", "dev")
    monkeypatch.setattr(settings, "ops_token", "")
    db_session.reset_engine()
    from rekha.db.session import init_db

    init_db()

    FLAGS.kill_switch = False
    FLAGS.complaints = []

    from rekha import policy as policy_mod

    policy_mod._ENGINE = None

    api_module.STATE["engine"] = None
    api_module.STATE["inbox"] = None
    api_module.STATE["audit"] = api_module.AuditChain()
    api_module.STATE["latest"] = None
    api_module.STATE["mtime"] = None

    yield

    db_session.reset_engine()
