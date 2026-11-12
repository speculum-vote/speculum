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


def test_company_never_advocacy():
    from speculum.lobbysectors import sector
    assert sector("Service that guides Veterans through the disability claims process.", "JOSHCO GROUP, LLC D/B/A VETERAN BENEFITS GUIDE") != "advocacy"
    assert sector("government relations", "Capitol Advocacy, LLC") != "advocacy"
    assert sector(None, "Capitol Advocacy, LLC") == "professional"
    assert sector("veterans service organization", "Disabled American Veterans") == "advocacy"


def test_own_amount_counts_reports_without_issues():
    from speculum.sources.lobbyspend import aggregate
    f = lambda uuid, exp, acts: {"filing_uuid": uuid, "filing_type": "Q1", "dt_posted": "2026-04-20", "expenses": exp, "income": None,
                                 "registrant": {"id": 7, "name": "VFW"}, "client": {"id": 8, "name": "VFW", "client_self_select": True},
                                 "lobbying_activities": acts}
    a = aggregate([f("a", "40000.00", [])])
    assert a["registrants"]["7"]["own_amount"] == 40000.0 and a["registrants"]["7"]["issues"] == {}


def test_case_headlines():
    from speculum.cases import headline
    h = headline({"ppp": {"totals": {"fees": 38.01e9}, "history": {"n_orgs": 744, "fee_orgs": [1, 2]}}})
    assert h["figure"] == "$38B" and "two named those fees" in h["line"]
    v = headline({"compare": {"focus_total": 4.56e6, "others_total": 4.34e6, "others": [0] * 7}})
    assert v["fmt"] == "money" and "seven major" in v["line"]
    assert headline({"compare": {"focus_total": 1, "others_total": 2, "others": []}}) is None
    assert headline({"measure": {"n_funders": 12, "n_both": 12}})["figure"] == "12 of 12"
