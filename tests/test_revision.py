import json

from speculum import chains, interpret
from speculum.site.build import public_view

SRC = [{"title": "Final rule", "url": "https://www.federalregister.gov/d/2024-1", "publisher": "Federal Register", "date": "2024-12-23"},
       {"title": "Public Law 119-7", "url": "https://www.govinfo.gov/plaw-119-7.pdf", "publisher": "GPO", "date": "2025-05-09"}]


def _record():
    return {"rule": "Energy Conservation Program", "agency": "Department of Energy", "published": "2024-12-23",
            "required": "Set new efficiency standards for walk-in coolers.", "benefits": "NPV of $2.00 billion to $4.74 billion.",
            "costs": "$99.1 million a year at 7 percent.", "status": "Nullified by Public Law 119-7.",
            "sources": SRC, "field_sources": {"rule": [0], "required": [0], "benefits": [0], "costs": [0], "status": [1]}}


def test_a_record_with_field_sources_is_checked_field_by_field():
    f = chains.record_fields(_record())
    assert set(f) == {"header", "required", "benefits", "costs", "status"}
    assert [s["url"] for s in f["status"]["sources"]] == [SRC[1]["url"]]       # only the sources that field cites
    assert f["required"]["item"] == {"field": "required", "text": "Set new efficiency standards for walk-in coolers.",
                                     "record_of": "Energy Conservation Program"}
    assert chains.record_fields({"items": ["x"], "sources": SRC}) == {}        # arms-sale records stay whole
    claims = chains.all_claims({}, {}, [{"_id": "rules-overturned-119-hjres24", "mechanism": _record(), "outcomes": []}])
    assert {c["kind"] for c in claims} == {"record field"} and len(claims) == 5
    assert claims[0]["label"].startswith("rules-overturned-119-hjres24: ")


def test_a_chain_publishes_when_its_core_fields_pass_and_shows_only_passed_fields():
    mx = _record()
    f = chains.record_fields(mx)
    ok = {"result": "supported"}
    checks = {f["required"]["fp"]: ok, f["status"]["fp"]: ok, f["benefits"]["fp"]: ok,
              f["costs"]["fp"]: {"result": "partly_supported", "note": "7 percent figure is for a different period"}}
    ch = {"mechanism": mx, "outcomes": [], "context": [], "page": {"main": "required", "pair": [["benefits", "b"], ["costs", "c"], "note"]}}
    chains.apply_checks(ch, checks, {})
    assert ch["mechanism_public"] and ch["auto_public"]
    assert ch["held"]["failed"] == 1 and ch["held"]["unchecked"] == 1          # costs failed; header not yet checked
    v = public_view(ch)
    assert "required" in v["mechanism"] and "status" in v["mechanism"]
    assert "benefits" not in v["mechanism"] and "costs" not in v["mechanism"]  # estimates appear in pairs, or not at all
    assert "rule" not in v["mechanism"]                                        # the unchecked identifying details
    checks.pop(f["status"]["fp"])
    ch2 = {**ch, "mechanism": _record()}
    chains.apply_checks(ch2, checks, {})
    assert not ch2["mechanism_public"]                                         # what became of it is a core field


def test_failed_claims_are_revised_once_from_the_checkers_note(tmp_path):
    out = {"grade": "estimated", "claim": "DOE estimated $554.5 million a year in net benefits over 2029-2058.",
           "quote": "net benefits of $554.5 million per year", "source": SRC[0]}
    legacy = {k: v for k, v in _record().items() if k != "field_sources"}
    (tmp_path / "rules-overturned-119-hjres24.json").write_text(json.dumps({"mechanism": legacy, "outcomes": [out]}))
    checks = {chains.claim_fp(out): {"result": "partly_supported", "note": "The source gives 2030-2059 for some equipment."},
              chains.claim_fp(legacy): {"result": "partly_supported", "note": "The costs figure is not in the rule."}}
    calls = []

    def fake(system, item, check):
        calls.append((system == interpret.SPLITTER, check["note"]))
        if system == interpret.SPLITTER:
            return {**{k: v for k, v in item.items() if k != "costs"}, "field_sources": {"rule": [0], "required": [0], "benefits": [0], "status": [1]}}
        return {**item, "claim": "DOE estimated $554.5 million a year in net benefits."}

    done = interpret.revise_failed(tmp_path, checks, call=fake)
    assert len(done) == 2 and calls == [(False, "The source gives 2030-2059 for some equipment."), (True, "The costs figure is not in the rule.")]
    d = json.loads((tmp_path / "rules-overturned-119-hjres24.json").read_text())
    assert d["outcomes"][0]["claim"] == "DOE estimated $554.5 million a year in net benefits." and d["outcomes"][0]["_revised"] == 1
    assert "costs" not in d["mechanism"] and d["mechanism"]["field_sources"]["status"] == [1]
    # The revised outcome fails again: it is not revised a second time.
    checks[chains.claim_fp(d["outcomes"][0])] = {"result": "partly_supported", "note": "still off"}
    assert interpret.revise_failed(tmp_path, checks, call=fake) == []


def test_a_failed_record_field_is_revised_or_dropped(tmp_path):
    mx = _record()
    f = chains.record_fields(mx)
    (tmp_path / "x.json").write_text(json.dumps({"mechanism": mx, "outcomes": []}))
    checks = {f["benefits"]["fp"]: {"result": "not_supported", "note": "No NPV in the cited source."},
              f["required"]["fp"]: {"result": "partly_supported", "note": "Applies to refrigeration systems only."}}
    answers = {"benefits": {"drop": True}, "required": {"field": "required", "text": "Set new efficiency standards for walk-in cooler refrigeration systems."}}
    done = interpret.revise_failed(tmp_path, checks, call=lambda s, item, c: answers[item["field"]])
    d = json.loads((tmp_path / "x.json").read_text())["mechanism"]
    assert sorted(done) == ["x: benefits", "x: required"]
    assert "benefits" not in d and d["required"].endswith("refrigeration systems.")
    assert d["_revised_fields"] == ["benefits", "required"]


def test_first_person_narration_is_rewritten_once_even_when_it_passed(tmp_path):
    mx = _record()
    mx["benefits"] = "The OCC did not publish a dollar estimate; I found none in the preamble."
    f = chains.record_fields(mx)
    out = {"grade": "estimated", "claim": 'Sponsors said "we must stop this rule" in a release.', "source": SRC[0]}
    (tmp_path / "x.json").write_text(json.dumps({"mechanism": mx, "outcomes": [out]}))
    checks = {f["benefits"]["fp"]: {"result": "supported"}}
    seen = []

    def fake(system, item, check):
        seen.append(check["note"])
        return {**item, "text": "The OCC did not publish a dollar estimate of benefits."}
    done = interpret.revise_failed(tmp_path, checks, call=fake)
    assert done == ["x: benefits"]                                  # the quoted "we" in the outcome is left alone
    assert "third person" in seen[0]
    d = json.loads((tmp_path / "x.json").read_text())["mechanism"]
    assert "I found" not in d["benefits"] and d["_voiced_fields"] == ["benefits"]
    assert interpret.revise_failed(tmp_path, checks, call=fake) == []
