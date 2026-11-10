from speculum.sources import ppplobby as P


def test_what_counts_as_lobbying_on_ppp():
    yes = ["Paycheck Protection Program loan forgiveness", "Small Business Administration's obligations under PPP program",
           "COVID-19 issues, PPP loan, CARES Act", "H.R. 7010, Paycheck Protection Program Flexibility Act"]
    no = ["Oppose Paycheck Protection Act (H.R. 2174)", "S. 135: Wildland Firefighter Paycheck Protection Act of 2025",
          "Highway funding and PPP (public-private partnerships) for bridges", ""]
    assert all(P.mentions_ppp(t) for t in yes) and not any(P.mentions_ppp(t) for t in no)
