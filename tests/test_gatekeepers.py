from speculum import gatekeepers


def test_committee_vs_rest_with_control():
    members = [{"bioguide": b, "name": b, "chamber": "house", "party": "D"} for b in "ABCD"]
    committees = {"seats": {"A": [{"code": "HSBA", "name": "Financial Services", "title": "Chair"}],
                            "B": [{"code": "HSBA", "name": "Financial Services"}]}}
    spend = {"quarters": {"2025-Q1": {"orgs": {"BANK": ["Bank", "banks", "1"], "FARM": ["Farm", "agriculture", "2"]}}}}
    g = lambda rid, a: {"registrant_id": rid, "amount": a}
    lobbying = {"years_label": "2025–2026", "registrants": {"3": {"name": "Firm LLC", "description": "lobbying firm"}},
                "by_member": {"A": [g("1", 300), g("2", 10)], "B": [g("1", 100), g("2", 10)],
                              "C": [g("1", 50), g("2", 10), g("3", 40)], "D": [g("2", 10)]}}
    out = gatekeepers.build(members, lobbying, spend, committees)
    r = out["lead"]
    assert (r["n_on"], r["n_all"]) == (2, 4)
    assert r["money_share"] == 400 / 450
    assert r["ratio"] == 200 / 25
    assert r["other_ratio"] == 10 / 30          # the firm's gifts count only as other money
    assert r["top"][0]["title"] == "Chair"


def test_unknown_registrant_falls_back_to_description():
    s = gatekeepers.registrant_sectors({"quarters": {}}, {"9": {"name": "Acme", "description": "community bank holding company"}})
    assert s["9"] == "banks"
