from speculum.sources import ppplobby as P


def test_what_counts_as_lobbying_on_ppp():
    yes = ["Paycheck Protection Program loan forgiveness", "Small Business Administration's obligations under PPP program",
           "COVID-19 issues, PPP loan, CARES Act", "H.R. 7010, Paycheck Protection Program Flexibility Act"]
    no = ["Oppose Paycheck Protection Act (H.R. 2174)", "S. 135: Wildland Firefighter Paycheck Protection Act of 2025",
          "Highway funding and PPP (public-private partnerships) for bridges", ""]
    assert all(P.mentions_ppp(t) for t in yes) and not any(P.mentions_ppp(t) for t in no)


def test_hr266_name_alone_does_not_count():
    law = "P.L. 116-139, Paycheck Protection Program and Health Care Enhancement Act; H.R. 6800, HEROES Act"
    assert not P.mentions_ppp(law) and P.law_only(law)
    both = law + "; Paycheck Protection Program loan forgiveness for nonprofits"
    assert P.mentions_ppp(both) and not P.law_only(both)
    assert "forgiveness" in P._windows(both, 60)[0] and "Enhancement" not in P._windows(both, 20)[0]


def test_fee_must_be_near_the_program():
    assert P.fee_near("Paycheck Protection Program lender processing fees")
    far = "Paycheck Protection Program loans. " + "x " * 200 + "Reasonable fees for payment card transactions"
    assert not P.fee_near(far)


def test_scan_counts_law_only_reports_without_listing_them():
    f = lambda d, n: {"lobbying_activities": [{"description": d}], "client": {"name": n}, "registrant": {}, "filing_uuid": n}
    orgs = {}
    n, hits, law = P.scan([f("Paycheck Protection Program and Health Care Enhancement Act", "HOSP"),
                           f("PPP loan forgiveness", "BANK")], orgs, "2020-Q2")
    assert (n, hits, law) == (2, 1, 1) and list(orgs) == ["BANK"] and orgs["BANK"]["reports"][0]["said"]


def test_amendment_counted_once_and_latest_amount_kept():
    def f(uuid, dt, amt, d="PPP loan forgiveness"):
        return {"filing_uuid": uuid, "dt_posted": dt, "filing_type": "Q2", "expenses": amt,
                "registrant": {"id": 1, "name": "Bank"}, "client": {"id": 2, "name": "Bank", "client_self_select": True},
                "lobbying_activities": [{"description": d}]}
    orgs, state = {}, {}
    n, hits, law = P.scan([f("a", "2020-07-20", "100000"), f("b", "2020-08-01", "120000")], orgs, "2020-Q2", state)
    assert hits == 1 and orgs["BANK"]["n_reports"] == 1
    spend = {}
    P.fold_spend(spend, state["spend"], 2020)
    assert spend["BANK"]["2020"] == {"own": 120000.0, "firms": 0.0}


def test_firm_income_kept():
    f = {"filing_uuid": "x", "dt_posted": "2020-07-20", "filing_type": "Q2", "income": "30000",
         "registrant": {"id": 9, "name": "Capitol Firm LLC", "state": "DC"}, "client": {"id": 3, "name": "Acme Corp", "state": "OH"},
         "lobbying_activities": [{"description": "Taxes"}]}
    state, spend, firms = {}, {}, {}
    P.scan([f], {}, "2020-Q2", state)
    P.fold_spend(spend, state["spend"], 2020, firms)
    assert spend["ACME"]["2020"]["firms"] == 30000.0 and list(firms.values())[0]["2020"] == 30000.0
    assert spend["ACME"]["states"] == ["OH"] and list(firms.values())[0]["states"] == ["DC"]
