import gzip
import json

from speculum import guard
from speculum.snapshot import Snapshot


def night(root, date, members=535, votes=100, filler=1000):
    d = root / "snapshots" / date
    d.mkdir(parents=True)
    (d / "members.json").write_text(json.dumps([{"bioguide": f"M{i}"} for i in range(members)]))
    vs = {"votes": [{"id": f"v{i}", "congress": 119} for i in range(votes)], "positions": {}}
    (d / "votes.json.gz").write_bytes(gzip.compress(json.dumps(vs).encode(), mtime=0))
    (d / "spend.json").write_text("x" * filler)
    (d / "meta.json").write_text("{}")
    (d / "meta.json").write_text(json.dumps({"files": Snapshot(root / "snapshots", date).index()}))


def test_a_normal_night_passes(tmp_path):
    night(tmp_path, "2026-11-08")
    night(tmp_path, "2026-11-09", votes=104)
    assert guard.check_data(tmp_path / "snapshots") == []


def test_a_shrunken_source_fewer_members_or_votes_fail(tmp_path):
    night(tmp_path, "2026-11-08")
    night(tmp_path, "2026-11-09", members=300, votes=60, filler=500)
    p = " ".join(guard.check_data(tmp_path / "snapshots"))
    assert "spend.json" in p and "300 members" in p and "60 roll calls" in p


def test_an_expected_drop_can_be_allowed_until_a_date(tmp_path):
    night(tmp_path, "2026-11-08")
    night(tmp_path, "2026-11-09", filler=500)
    (tmp_path / "guard.json").write_text(json.dumps({"allow": {"spend.json": "2026-11-10"}}))
    assert guard.check_data(tmp_path / "snapshots") == []
    (tmp_path / "guard.json").write_text(json.dumps({"allow": {"spend.json": "2026-11-08"}}))
    assert guard.check_data(tmp_path / "snapshots")


def site(tmp_path, members=3, body="<p>" + "x" * 60_000 + "</p>"):
    for s in ("preview", "public"):
        (tmp_path / s / "member").mkdir(parents=True)
    (tmp_path / "public" / "index.html").write_text("holding")
    for page in guard.PAGES:
        (tmp_path / "preview" / page).write_text(body)
    for i in range(members):
        (tmp_path / "preview" / "member" / f"M{i}.html").write_text("m")


def test_a_complete_site_passes(tmp_path):
    site(tmp_path)
    assert guard.check_site(tmp_path, 3) == []


def test_missing_pages_empty_pages_and_template_leftovers_fail(tmp_path):
    site(tmp_path, members=2)
    (tmp_path / "preview" / "money.html").unlink()
    (tmp_path / "preview" / "bills.html").write_text("<p>short</p>")
    (tmp_path / "preview" / "chamber.html").write_text("<p>" + "x" * 60_000 + " {{ m.name }}</p>")
    p = " ".join(guard.check_site(tmp_path, 3))
    assert "money.html is missing" in p and "bills.html" in p and "chamber.html: unfilled" in p and "2 member pages" in p


def test_script_text_is_not_junk(tmp_path):
    site(tmp_path, body="<script>if (x === undefined) {}</script><p>" + "x" * 60_000 + "</p>")
    assert guard.check_site(tmp_path, 3) == []
