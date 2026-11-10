from speculum import bills, lobbysectors
from speculum.sources import lobbyspend


def test_bill_numbers_are_read_from_descriptions():
    assert lobbyspend.bills_in("H.R. 1, the reconciliation bill; S. 2296 NDAA; H. Res. 5") == ["HR1", "S2296", "HRES5"]
    assert lobbyspend.bills_in("U.S. 2025 trade; Section 232; S 12") == []


def test_sectors_follow_the_published_order():
    s = lobbysectors.sector
    assert s("Federally insured depository institution", "BETHPAGE FEDERAL CREDIT UNION") == "banks"
    assert s("labor union representing nurses") == "labor"
    assert s("trade association representing SEC registered investment adviser firms") == "investment"
    assert s("Digital Payments") == "finance"
    assert s("window manufacturer") == "industry"
    assert s("", "TOWN OF X", government=True) == "government"


def _q(bills_, orgs):
    return {"bills": bills_, "orgs": orgs, "people": {"7": ["Pat Doe", "Chief of Staff, Rep. Pat Smith"]}}


def test_mentions_before_a_bill_was_introduced_are_left_out():
    spend = {"quarters": {
        "2025-Q1": _q({"HR9": {"orgs": ["a"], "reports": 1, "former": []}}, {"a": ["A Corp", "industry", ""]}),
        "2025-Q3": _q({"HR9": {"orgs": ["b"], "reports": 1, "former": ["7"]}}, {"b": ["B Union", "labor", "55"]}),
    }}
    info = {"bills": {"119-HR9": {"introduced": "2025-05-01"}}}
    c = bills.collect(spend, info)[(119, "HR9")]
    assert list(c["orgs"]) == ["b"] and c["quarters"] == ["2025-Q3"] and "7" in c["former"]
    assert list(bills.collect(spend)[(119, "HR9")]["orgs"]) == ["a", "b"]


def test_a_former_post_must_name_a_government_office():
    from speculum.sources.lobbyspend import is_post
    for t in ["Chief of Staff, Rep. Pat Smith", "Professional Staff, Senate Appropriations Committee", "Aide to Sens. Inhofe and Tillis",
              "Deputy CoS - USDOT", "Special Assistant to the President", "LegCorr.SenLautenberg"]:
        assert is_post(t), t
    for t in ["None", "N/A", "Director of Government Relations", "Lobbyist", "Vice President of Federal Government Affairs",
              "Legislative Director", "President", "Represented clients"]:
        assert not is_post(t), t


def test_nonprofits_and_mission_groups_are_not_read_as_their_subject():
    s = lobbysectors.sector
    assert s("Non-profit focused on education on financial products and lending practices") == "advocacy"
    assert s("Working toward social justice in financial marketplaces on behalf of responsible lending") == "advocacy"
    assert s("", "CENTER FOR RESPONSIBLE LENDING A SUPPORTING CORP OF CTR FOR COMMUNITY SELF-HELP") == "advocacy"
    assert s("", "NATIONAL TAXPAYERS UNION") == "advocacy" and s("", "AMERICANS FOR TAX REFORM") == "advocacy"
    assert s("Non-profit trade association representing community banks") == "banks"   # an industry's association
    assert s("", "AMERICAN BANKERS ASSOCIATION") == "banks"
