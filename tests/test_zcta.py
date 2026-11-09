from speculum.sources import zcta

HEAD = ("OID_CD119_20|GEOID_CD119_20|NAMELSAD_CD119_20|AREALAND_CD119_20|AREAWATER_CD119_20|MTFCC_CD119_20|FUNCSTAT_CD119_20|"
        "OID_ZCTA5_20|GEOID_ZCTA5_20|NAMELSAD_ZCTA5_20|AREALAND_ZCTA5_20|AREAWATER_ZCTA5_20|MTFCC_ZCTA5_20|CLASSFP_ZCTA5_20|"
        "FUNCSTAT_ZCTA5_20|AREALAND_PART|AREAWATER_PART")


def row(cd, z, land):
    return f"1|{cd}|x|0|0|G5200|N|2|{z}|ZCTA5 {z}|0|0|G6350|B5|S|{land}|0"


def test_a_zip_split_between_districts_lists_both_largest_first():
    text = "\n".join([HEAD, row("3704", "27513", 100), row("3702", "27513", 900), row("1000", "19901", 50),
                      row("1198", "20001", 10), row("37ZZ", "27999", 5), row("", "00601", 3)])
    got = zcta.parse(text)
    assert got["27513"] == [["NC", 2, 0.9], ["NC", 4, 0.1]]
    assert got["19901"] == [["DE", 0, 1.0]] and got["20001"] == [["DC", 0, 1.0]]
    assert "27999" not in got and "00601" not in got
