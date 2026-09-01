from rekha.audit import GENESIS, AuditChain, verify_rows


def test_chain_verifies():
    chain = AuditChain()
    chain.append({"actor": "t", "case_id": "c1", "action": "diagnose"})
    chain.append({"actor": "t", "case_id": "c1", "action": "policy"})
    ok, msg = verify_rows(chain.rows)
    assert ok, msg
    assert chain.rows[0]["prev_hash"] == GENESIS


def test_tamper_breaks_chain():
    chain = AuditChain()
    for i in range(5):
        chain.append({"actor": "t", "case_id": "c", "action": f"a{i}"})
    rows = [dict(r) for r in chain.rows]
    rows[2]["action"] = "TAMPERED"
    ok, msg = verify_rows(rows)
    assert not ok
    assert "entry_hash_mismatch" in msg or "prev_hash_mismatch" in msg
