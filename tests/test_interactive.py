from speculum.site import interactive as ix


def test_concentration_ratio_and_floors():
    seats = {f"M{i}": (["HSAP"] if i < 10 else ["HSAG"]) for i in range(40)}
    cidx = {"HSAP": {"n": "Appropriations", "c": "h", "p": None}, "HSAG": {"n": "Agriculture", "c": "h", "p": None}}
    amounts = {f"M{i}": 1000.0 for i in range(10)}          # all to the 10 appropriators
    amounts["M20"] = 300.0
    out = ix.concentration(amounts, seats, cidx)
    assert out[0]["code"] == "HSAP" and out[0]["funded"] == 10
    assert round(out[0]["avg_on"]) == 1000 and round(out[0]["avg_off"]) == 10      # 300 spread over 30
    assert out[0]["name"] == "House Appropriations"
    assert all(c["code"] != "HSAG" or c["funded"] >= 4 for c in out)


def test_committee_names_drop_the():
    c = {"seats": {"A": [{"code": "SSJU", "name": "Senate Committee on the Judiciary"},
                         {"code": "SSJU25", "name": "Senate Committee on the Judiciary: Crime and Counterterrorism"}]}}
    idx = ix.committee_index(c)
    assert idx["SSJU"]["n"] == "Judiciary" and idx["SSJU25"]["n"] == "Judiciary: Crime and Counterterrorism"
    assert idx["SSJU25"]["p"] == "SSJU"


def test_fold():
    assert ix.fold("Peña-Martínez, H.R. 1013") == "pena martinez h r 1013"
