from datetime import date

from speculum.sources import ppp


def test_fee_follows_the_sba_schedule():
    early, late = date(2020, 4, 10), date(2021, 2, 1)
    assert ppp.fee(20_000, early) == 1_000                       # 5%
    assert ppp.fee(20_000, late) == 2_500                        # 2021: lesser of 50% and $2,500
    assert ppp.fee(4_000, late) == 2_000                         # 50%
    assert ppp.fee(350_000, early) == 17_500 and ppp.fee(350_001, early) == 0.03 * 350_001
    assert ppp.fee(2_000_000, early) == 20_000                   # 1% from $2 million
    assert ppp.fee(0, early) == 0


def test_aggregate_counts_disbursed_loans_once_per_lender():
    rows = [
        {"LoanNumber": "1", "DateApproved": "04/10/2020", "CurrentApprovalAmount": "100000", "UndisbursedAmount": "0",
         "OriginatingLender": "Bank A", "OriginatingLenderState": "NC", "ProcessingMethod": "PPP", "ForgivenessAmount": "100500"},
        {"LoanNumber": "1", "DateApproved": "04/10/2020", "CurrentApprovalAmount": "100000", "UndisbursedAmount": "0",
         "OriginatingLender": "Bank A", "OriginatingLenderState": "NC", "ProcessingMethod": "PPP"},          # repeated row
        {"LoanNumber": "2", "DateApproved": "02/01/2021", "CurrentApprovalAmount": "20000", "UndisbursedAmount": "0",
         "OriginatingLender": "Bank A", "OriginatingLenderState": "NC", "ProcessingMethod": "PPS"},
        {"LoanNumber": "3", "DateApproved": "05/01/2020", "CurrentApprovalAmount": "50000", "UndisbursedAmount": "50000",
         "OriginatingLender": "Bank B", "OriginatingLenderState": "TX", "ProcessingMethod": "PPP"},          # nothing disbursed
    ]
    a = ppp.aggregate(rows)
    assert a["totals"]["loans"] == 2 and a["totals"]["skipped"] == 1
    L = a["lenders"][0]
    assert L["name"] == "Bank A" and L["fees"] == 7_500 and L["second"] == 1 and L["small"] == 1
