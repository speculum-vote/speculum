from speculum.sources import billcheck


def test_pattern_matches_forms_and_not_longer_numbers():
    p = billcheck.pattern("HR1013")
    for s in ["H.R. 1013", "HR 1013", "H.R.1013", "H. R. 1013,", "H.R. #1013"]:
        assert p.search(s), s
    for s in ["H.R. 10130", "H.R. 21013", "S. 1013", "THR 1013x"]:
        assert not p.search(s), s


def test_report_list_merges_quarters():
    spend = {"quarters": {"2025-Q1": {"bill_filings": {"HR1013": {"A": ["u1"]}}},
                          "2025-Q2": {"bill_filings": {"HR1013": {"A": ["u2"], "B": ["u3"]}}}}}
    assert billcheck.report_list(spend, "HR1013") == {"A": [("2025-Q1", "u1"), ("2025-Q2", "u2")], "B": [("2025-Q2", "u3")]}
