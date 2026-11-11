from speculum.sources.lobbyspend import bills_in


def test_old_congress_mentions_left_out():
    vg = "Issues related to VA benefits claims. H.R. 1139/S. 740 - GUARD VA Benefits Act and H.R. 1822/S. 1789 - PLUS for Veterans Act of 2023."
    assert bills_in(vg) == ["HR1139", "S740"]           # the 2023 pair goes; the unnamed-year pair can't be told apart
    assert bills_in("the STOP CSAM Act (S.1199/H.R.7949 in the 118th Congress)") == []
    assert bills_in("H.R. 1822/S. 838, Access to Credit for our Rural Economy (ACRE) Act of 2025") == ["HR1822", "S838"]
    assert bills_in("H.R. 4582, to amend the Family and Medical Leave Act of 1993") == ["HR4582"]
    assert bills_in("H.R. 5494: the Essential Workers Act. 118th Congress: H.R. 3734: the Essential Workers Act.") == ["HR5494"]
    assert bills_in("P.L. 118-42 (H.R. 4366 (118th Congress)): Consolidated Appropriations Act, 2024") == []
    assert bills_in("H.R. 1, One Big Beautiful Bill Act; S. 2296") == ["HR1", "S2296"]


def test_backfill_replaces_bill_fields_once_under_a_newer_rule():
    from speculum.sources.lobbyspend import apply_backfill
    q = {"bills": {"HR1822": {"orgs": ["VG"]}}, "orgs": {"VG": ["VG", "other", ""]}}
    bf = {"_rule": 2, "_replace": ["bills", "orgs"], "bills": {"2025-Q1": {}}, "orgs": {"2025-Q1": {}},
          "bill_filings": {"2025-Q1": {}}}
    q2 = apply_backfill(q, "2025-Q1", bf)
    assert q2["bills"] == {} and q2["bills_rule"] == 2 and "bill_filings" in q2
    q2["bills"] = {"KEEP": {}}
    assert apply_backfill(q2, "2025-Q1", bf)["bills"] == {"KEEP": {}}     # already under rule 2: left alone
