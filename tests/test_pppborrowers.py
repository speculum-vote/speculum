from speculum.sources import pppborrowers as B


def test_match_by_name_and_state_and_never_a_person():
    lob = {"spend_by_key": {"NATIONAL WIDGET ASSOCIATION": {"name": "National Widget Association", "states": ["VA"],
                                                            "2020": {"own": 1_500_000.0, "firms": 0.0}}},
           "firms_by_key": {"CAPITOL STRATEGIES": {"name": "Capitol Strategies LLC", "states": ["DC"], "2020": 900_000.0}}}
    tg = B.targets(lob)
    row = lambda name, st, bt="Non-Profit Organization", ln="1": {
        "BorrowerName": name, "BorrowerState": st, "BusinessType": bt, "LoanNumber": ln, "CurrentApprovalAmount": "250000",
        "UndisbursedAmount": "0", "ForgivenessAmount": "252000", "DateApproved": "01/20/2021", "ProcessingMethod": "PPS"}
    found = B.match([row("National Widget Association, Inc.", "VA", ln="1"),
                     row("National Widget Association", "TX", ln="2"),                 # other state: not the same
                     row("Capitol Strategies, LLC", "DC", "Limited  Liability Company(LLC)", ln="3"),
                     row("Capitol Strategies", "DC", "Sole Proprietorship", ln="4")], tg)    # a person: never kept
    assert sorted(found) == ["CAPITOL STRATEGIES", "NATIONAL WIDGET ASSOCIATION"]
    w = found["NATIONAL WIDGET ASSOCIATION"]
    assert [l["loan"] for l in w["loans"]] == ["1"] and w["loans"][0]["draw"] == "second"
    assert w["lobbying"]["2020"]["own"] == 1_500_000.0
    assert [l["loan"] for l in found["CAPITOL STRATEGIES"]["loans"]] == ["3"]


def test_case_section_drops_name_twins_and_splits_firms():
    from speculum.cases import ppp_borrowers
    loan = lambda **k: {"loan": "1", "borrower": "X", "city": "Washington", "state": "DC", "approved": "2020-04-10",
                        "amount": 100000.0, "forgiven": 100000.0, "draw": "first", "type": "Corporation", "naics": "541820",
                        "jobs": 10, "lender": "B", **k}
    d = {"matches": {
        "OIL": {"name": "Big Oil, Inc.", "kind": "client", "lobbying": {"2020": {"own": 5e6}}, "loans": [loan(naics="447110", jobs=7)]},
        "ASSN": {"name": "Small Trade Association", "kind": "client", "lobbying": {"2020": {"own": 9e5}},
                 "loans": [loan(naics="813910", jobs=6, type="501(c)6 \\ufffd Non Profit Membership")]},
        "PA": {"name": "Capitol Public Affairs", "kind": "firm", "lobbying": {"2020": {"firm_income": 2e6}}, "loans": [loan()]},
        "LAW": {"name": "Law LLP", "kind": "firm", "lobbying": {"2020": {"firm_income": 1e6}}, "loans": [loan(naics="541110")]},
        "BEH": {"name": "Firm (on behalf of City)", "kind": "client", "lobbying": {}, "loans": [loan()]}}}
    b = ppp_borrowers(d)
    assert sorted(b["dropped"]) == ["Big Oil, Inc.", "Firm (on behalf of City)"]
    assert [x["name"] for x in b["c6"]] == ["Small Trade Association"] and not b["c6_over"]
    assert [x["name"] for x in b["lobby"]] == ["Capitol Public Affairs"] and [x["name"] for x in b["law"]] == ["Law LLP"]
    assert b["lobby_early"] == 1
