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
