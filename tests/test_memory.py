from calyb.runtime.memory import Memory


def test_recall_similar_ranks_by_token_overlap():
    m = Memory()
    m.remember("run-1", "Onboard Bob as a data analyst on the data team", "SUCCEEDED", "onboarded")
    m.remember("run-2", "Investigate why Carol can't access the data warehouse", "SUCCEEDED", "resolved")
    m.remember("run-3", "Grant Dave access to billing", "FAILED", "denied")

    results = m.recall_similar("Onboard Erin as a data analyst on the data team")
    assert results
    assert results[0]["run_id"] == "run-1"


def test_recall_similar_returns_empty_when_nothing_overlaps():
    m = Memory()
    m.remember("run-1", "Grant Dave access to billing", "FAILED", "denied")
    assert m.recall_similar("zzz qqq nonsense") == []
