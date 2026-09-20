"""T02: the prepared kmu.db keeps the spec (SPEC 6.1, 6.2, 6.3, 10).

Skipped when DB_PATH has no file or no cards, so a fresh checkout still runs green.
"""

import json
import os

import pytest

from app import db

CATEGORIES = {
    "장학", "인턴·현장실습", "국제교류", "교내활동", "학사·전공",
    "한국어·문화", "창업", "공모전·경진대회", "자격증·어학",
}

LANG_TESTS = {"TOEIC", "TOEFL iBT", "IELTS", "TOEIC Speaking", "OPIc"}
OPIC_GRADES = ["NL", "NM", "NH", "IL", "IM1", "IM2", "IM3", "IH", "AL"]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# SPEC 6.2: exact params keys and the value shape each type takes.
PARAM_RULES = {
    "semesters": ({"min"}, lambda p: _is_int(p["min"])),
    "grade": ({"min", "max"}, lambda p: _is_int(p["min"]) and _is_int(p["max"])),
    "status": ({"allowed"}, lambda p: isinstance(p["allowed"], list) and p["allowed"]
               and all(isinstance(x, str) for x in p["allowed"])),
    "gpa": ({"min", "scope"}, lambda p: _is_num(p["min"]) and p["scope"] in ("cumulative", "last")),
    "credits": ({"min", "scope"}, lambda p: _is_int(p["min"]) and p["scope"] in ("last", "total")),
    "lang": ({"any_of"}, lambda p: isinstance(p["any_of"], dict) and p["any_of"]
             and all(k in LANG_TESTS for k in p["any_of"])
             and all(_is_num(v) or (k == "OPIc" and v in OPIC_GRADES)
                     for k, v in p["any_of"].items())),
    "topik": ({"min"}, lambda p: _is_int(p["min"]) and 0 <= p["min"] <= 6),
    "major": ({"majors"}, lambda p: isinstance(p["majors"], list) and p["majors"]
              and all(isinstance(x, str) for x in p["majors"])),
    "income": ({"max"}, lambda p: _is_int(p["max"])),
    "admission_year": ({"min", "max"}, lambda p: all(v is None or _is_int(v)
                                                     for v in (p["min"], p["max"]))),
    "history": ({"flag", "must"}, lambda p: isinstance(p["flag"], str) and isinstance(p["must"], bool)),
    "none": (set(), lambda p: True),
    "unresolved": ({"reason"}, lambda p: isinstance(p["reason"], str)),
}


@pytest.fixture(scope="module")
def conn():
    path = os.environ.get("DB_PATH", "data/kmu.db")
    if not os.path.exists(path):
        pytest.skip("no DB at DB_PATH: {}".format(path))
    c = db.connect(path)
    if c.execute("SELECT COUNT(*) FROM card").fetchone()[0] == 0:
        c.close()
        pytest.skip("no cards in {}".format(path))
    yield c
    c.close()


def _cards(conn):
    return conn.execute("SELECT * FROM card").fetchall()


def test_every_quote_is_in_its_own_raw_source(conn):
    texts = {}
    owner = {}
    for r in conn.execute("SELECT id, notice_key, text FROM raw_source"):
        texts[r["id"]] = r["text"]
        owner[r["id"]] = r["notice_key"]
    bad = []
    for card in _cards(conn):
        for cond in json.loads(card["conditions"]):
            quote = cond.get("quote", "")
            if cond["type"] == "unresolved" and not quote:
                continue
            sid = cond.get("source_id")
            if sid not in texts:
                bad.append((card["notice_key"], cond["id"], "unknown source_id {}".format(sid)))
                continue
            if owner[sid] != card["notice_key"]:
                bad.append((card["notice_key"], cond["id"], "source_id of another notice"))
                continue
            if quote not in texts[sid]:
                bad.append((card["notice_key"], cond["id"], "quote not in raw_source"))
    assert bad == []


def test_condition_types_and_params_match_the_table(conn):
    bad = []
    for card in _cards(conn):
        for cond in json.loads(card["conditions"]):
            rule = PARAM_RULES.get(cond["type"])
            if rule is None:
                bad.append((card["notice_key"], cond["type"], "unknown type"))
                continue
            keys, ok = rule
            params = cond.get("params", {})
            if set(params) != keys:
                bad.append((card["notice_key"], cond["type"], "params keys {}".format(sorted(params))))
            elif not ok(params):
                bad.append((card["notice_key"], cond["type"], "params values {}".format(params)))
    assert bad == []


def test_categories_are_the_nine(conn):
    bad = [(c["notice_key"], c["category"]) for c in _cards(conn) if c["category"] not in CATEGORIES]
    assert bad == []


def test_unresolved_conditions_have_an_open_review(conn):
    reviews = {}
    for r in conn.execute("SELECT notice_key, condition_id FROM review WHERE resolved = 0"):
        reviews.setdefault(r["notice_key"], set()).add(r["condition_id"])
    bad = []
    for card in _cards(conn):
        for cond in json.loads(card["conditions"]):
            if cond["type"] != "unresolved":
                continue
            ids = reviews.get(card["notice_key"], set())
            if cond["id"] not in ids and None not in ids:
                bad.append((card["notice_key"], cond["id"]))
    assert bad == []


def test_linked_to_points_at_a_representative(conn):
    heads = {c["notice_key"] for c in _cards(conn) if c["linked_to"] is None}
    bad = [(c["notice_key"], c["linked_to"]) for c in _cards(conn)
           if c["linked_to"] is not None and c["linked_to"] not in heads]
    assert bad == []


def test_task_due_is_not_after_apply_end(conn):
    ends = {c["notice_key"]: c["apply_end"] for c in _cards(conn)}
    bad = []
    for t in conn.execute("SELECT notice_key, title, due FROM task_template"):
        end = ends.get(t["notice_key"])
        if end is None:
            bad.append((t["notice_key"], "task on a card with no apply_end"))
        elif t["due"] > end:
            bad.append((t["notice_key"], "due {} > apply_end {}".format(t["due"], end)))
    assert bad == []


def test_exactly_one_demo_new_card(conn):
    assert conn.execute("SELECT COUNT(*) FROM card WHERE demo_new = 1").fetchone()[0] == 1


# --- demo readiness (SPEC 10). Fails before the team check, so it is opt-in. ---

release = pytest.mark.skipif(
    os.environ.get("KMU_RELEASE") != "1",
    reason="set KMU_RELEASE=1 to run the demo readiness checks",
)


@release
def test_every_visible_card_was_checked(conn):
    n = conn.execute("SELECT COUNT(*) FROM card WHERE hidden = 0 AND check_ok IS NULL").fetchone()[0]
    assert n == 0, "{} cards still need the team check".format(n)


@release
def test_the_list_is_not_empty_on_demo_today(conn):
    today = os.environ.get("DEMO_TODAY", "2026-03-16")
    n = conn.execute(
        "SELECT COUNT(*) FROM card c JOIN notice n ON n.key = c.notice_key"
        " WHERE c.check_ok = 1 AND c.hidden = 0 AND c.linked_to IS NULL AND c.demo_new = 0"
        " AND c.apply_end >= ? AND (c.apply_start IS NULL OR c.apply_start <= ?)"
        " AND n.posted_date <= ?",
        (today, today, today),
    ).fetchone()[0]
    assert n >= 1


@release
def test_the_demo_new_card_is_checked_and_open(conn):
    today = os.environ.get("DEMO_TODAY", "2026-03-16")
    row = conn.execute("SELECT * FROM card WHERE demo_new = 1").fetchone()
    assert row["check_ok"] == 1
    assert row["hidden"] == 0
    assert row["apply_end"] is not None and row["apply_end"] >= today
