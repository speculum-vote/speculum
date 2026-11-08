from speculum import saiddone as sd


def roll(id, chamber, date, question, number=1):
    return {"id": id, "chamber": chamber, "date": date, "question": question, "number": str(number), "result": "Passed"}


def test_decision_is_last_deciding_roll_call_per_chamber():
    rolls = [roll("h1", "house", "2025-05-22", "On Passage"),
             roll("h2", "house", "2025-07-03", "On Ordering the Previous Question"),
             roll("h3", "house", "2025-07-03", "On Motion to Concur in the Senate Amendment", 2),
             roll("s1", "senate", "2025-06-30", "On the Motion to Proceed"),
             roll("s2", "senate", "2025-07-01", "On Passage of the Bill"),
             roll("s3", "senate", "2025-07-01", "On the Amendment", 5)]
    assert [v["id"] for v in sd.decisions(rolls)] == ["h3", "s2"]
    assert sd.decisions([roll("x", "senate", "2025-01-01", "On the Cloture Motion")]) == []


def test_lobbyists_own_contributions_are_not_the_organizations():
    assert sd._personal({"contributor": "Self", "reported_by": "Jane Roe (Acme Corp)"})
    assert sd._personal({"contributor": "Jane Roe", "reported_by": "Jane Roe (Acme Corp)"})
    assert not sd._personal({"contributor": "Acme Corp PAC", "reported_by": "Jane Roe (Acme Corp)"})
    assert not sd._personal({"contributor": "Acme Corp PAC", "reported_by": "Acme Corp"})


def _data():
    rolls = [roll("h9", "house", "2025-03-01", "On Passage"), roll("s9", "senate", "2025-03-02", "On Passage of the Bill")]
    positions = {"h9": {"A": "Yea", "B": "Nay", "C": "Not Voting"}, "s9": {"S": "Nay"}}
    entry = {"orgs": {"x": ("Org X", "tech", "1"), "y": ("Org Y", "tech", "2"), "z": ("Firm Z", "tech", None),
                      "w": ("Org W", "tech", "4")}, "quarters": ["2025-Q1"]}
    c = lambda amt, by="Org X": {"type": "FECA", "amount": amt, "contributor": "PAC", "reported_by": by, "url": f"u{amt}"}
    giving = {"1": {"A": [c(100)], "S": [c(50)]},        # both sides (House yes, Senate no)
              "2": {"A": [c(10)], "C": [c(5)]},          # only yes (C did not vote)
              "4": {"Q": [c(7)]}}                         # funded no one who voted
    return rolls, positions, entry, giving


def test_both_sides_counts():
    rolls, positions, entry, giving = _data()
    m = sd.measure((119, "HR9"), entry, rolls, positions, giving, {"A": "R", "B": "D", "S": "D"})
    assert m["n_lobbied"] == 4 and m["n_lobbied_own"] == 3        # the firm (no registrant of its own) is left out
    assert m["n_funders"] == 2 and m["n_both"] == 1 and m["n_yes_only"] == 1 and m["n_no_only"] == 0
    x = m["orgs"][0]
    assert x["name"] == "Org X" and x["both"] and x["yes"]["amount"] == 100 and x["no"]["amount"] == 50
    assert x["no"]["party"] == {"D": 1}
    assert m["money"] == {"yes": 110, "no": 50}


def test_rounds_open_first_bill_then_count():
    bills = [{"slug": s, "n_lobbied": n} for s, n in [("119-hr1", 900), ("119-a", 500), ("119-b", 400), ("119-c", 300)]]
    data = {"bills": bills, "by_slug": {b["slug"]: b for b in bills}}
    st = sd.advance({}, data, "2026-11-08")
    assert [o["slug"] for o in st["opened"]] == ["119-hr1"]
    assert st["round"]["candidates"] == ["119-a", "119-b", "119-c"] and st["round"]["closes"] == "2026-11-14"
    assert sd.advance(st, data, "2026-11-14", lambda r: {"119-b": 9}) == st          # still open on its last day
    st2 = sd.advance(st, data, "2026-11-15", lambda r: {"119-b": 2, "119-c": 2, "119-hr1": 50})
    assert st2["closed"][0]["winner"] == "119-b"                                     # tie: more organizations lobbied
    assert st2["closed"][0]["counts"] == {"119-a": 0, "119-b": 2, "119-c": 2}        # votes for bills off the ballot ignored
    assert [o["slug"] for o in st2["opened"]] == ["119-hr1", "119-b"]
    assert st2["round"]["candidates"] == ["119-a", "119-c"] and st2["round"]["id"] == "2026-11-15"
    st3 = sd.advance(st2, data, "2026-11-22", lambda r: {})
    assert st3["closed"][-1]["winner"] is None and len(st3["opened"]) == 2          # no votes, nothing opens
