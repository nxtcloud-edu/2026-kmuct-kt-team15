"""T16: the operator queue (SPEC 8.5). Temp DB, FastAPI TestClient."""

import json

import pytest
from fastapi.testclient import TestClient

from app import db

TODAY = "2026-03-16"
PASSWORD = "sesame"
AUTH = ("admin", PASSWORD)
QUOTE = "직전 학기 12학점 이상 이수한 재학생"
BODY = f"2026학년도 1학기 교내 근로 장학생을 모집합니다. {QUOTE}이 신청할 수 있습니다."
GPA_COND = {
    "id": "c1", "type": "gpa", "label": "평균 학점", "need": "3.0 이상",
    "params": {"min": 3.0, "scope": "cumulative"}, "source_id": 1,
    "quote": "2026학년도 1학기 교내 근로 장학생을 모집합니다.",
}
CREDITS_FIX = {
    "type": "credits", "label": "직전 학기 이수 학점", "need": "12학점 이상",
    "params": {"min": 12, "scope": "last"}, "source_id": 1, "quote": QUOTE,
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = str(tmp_path / "admin.db")
    monkeypatch.setenv("DB_PATH", path)
    monkeypatch.setenv("DEMO_TODAY", TODAY)
    monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init(path)
    from app import main

    with TestClient(main.app) as c:
        c.db_path = path
        yield c


def unresolved(cid="c1", reason="열람 불가"):
    return {"id": cid, "type": "unresolved", "label": "지원 자격", "need": "확인 중",
            "params": {"reason": reason}, "source_id": 1, "quote": ""}


def add_card(path, key="hq:1", conditions=(), apply_end="2026-03-20", hidden=0, text=BODY):
    conn = db.connect(path)
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO notice (key, source_id, source_name, url, title,"
            " posted_date, department, body_text, attachments, body_hash, crawled_at)"
            " VALUES (?, 'hq', '게시판', ?, '공지', '2026-03-01', NULL, ?, '[]', ?, '2026-03-01')",
            (key, "https://example/" + key, text, db.body_hash("공지", text)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO card (notice_key, title, sub, dept, category, apply_start,"
            " apply_end, conditions, fields, trace, linked_to, check_ok, hidden, demo_new,"
            " interpreted_by) VALUES (?, '교내 근로 장학생', '', '학생지원팀', '장학',"
            " '2026-03-01', ?, ?, '[]', '[]', NULL, 1, ?, 0, 'claude-prep')",
            (key, apply_end, json.dumps(list(conditions), ensure_ascii=False), hidden),
        )
        conn.execute(
            "INSERT OR REPLACE INTO raw_source (id, notice_key, ord, kind, label, url, text,"
            " confidence) VALUES (1, ?, 1, 'body', '본문', ?, ?, NULL)",
            (key, "https://example/" + key, text),
        )
    conn.close()


def add_review(path, key="hq:1", condition_id="c1", reason="열람 불가"):
    conn = db.connect(path)
    with conn:
        cur = conn.execute(
            "INSERT INTO review (notice_key, condition_id, reason, note, resolved)"
            " VALUES (?, ?, ?, '', 0)",
            (key, condition_id, reason),
        )
    conn.close()
    return cur.lastrowid


def add_student(path, student_id, profile):
    conn = db.connect(path)
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO student (id, profile, revealed_new, is_seed, created_at)"
            " VALUES (?, ?, 0, 0, '2026-03-16')",
            (student_id, json.dumps(profile, ensure_ascii=False)),
        )
    conn.close()


def add_task(path, key, due, title="신청서 제출"):
    conn = db.connect(path)
    with conn:
        conn.execute(
            "INSERT INTO task_template (notice_key, ord, title, due) VALUES (?, 1, ?, ?)",
            (key, title, due),
        )
    conn.close()


def card_row(path, key="hq:1"):
    conn = db.connect(path)
    row = conn.execute("SELECT * FROM card WHERE notice_key = ?", (key,)).fetchone()
    conn.close()
    return row


def review_row(path, review_id):
    conn = db.connect(path)
    row = conn.execute("SELECT * FROM review WHERE id = ?", (review_id,)).fetchone()
    conn.close()
    return row


# --- the password (SPEC 8.5) ---


@pytest.mark.parametrize(
    "method, path",
    [
        ("get", "/admin"),
        ("get", "/admin/api/reviews"),
        ("get", "/admin/api/notices/hq:1/raw"),
        ("put", "/admin/api/reviews/1"),
    ],
)
def test_admin_needs_the_password(client, method, path):
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, auth=("admin", "nope")).status_code == 401


def test_an_empty_password_locks_everyone_out(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "")
    assert client.get("/admin/api/reviews", auth=AUTH).status_code == 401
    assert client.get("/admin/api/reviews", auth=("admin", "")).status_code == 401


def test_the_page_is_served_behind_the_password(client):
    res = client.get("/admin", auth=AUTH)
    assert res.status_code == 200
    assert "검토 대기열" in res.text


# --- the queue and the raw sources ---


def test_the_queue_lists_unresolved_reviews_in_id_order(client):
    add_card(client.db_path, conditions=[unresolved()])
    add_card(client.db_path, key="hq:2", conditions=[unresolved()])
    first = add_review(client.db_path)
    second = add_review(client.db_path, key="hq:2", reason="못 찾음")
    conn = db.connect(client.db_path)
    with conn:
        conn.execute("UPDATE review SET resolved = 1 WHERE id = ?", (second,))
    conn.close()

    body = client.get("/admin/api/reviews", auth=AUTH).json()
    assert [r["id"] for r in body] == [first]
    assert body[0]["notice_key"] == "hq:1"
    assert body[0]["title"] == "교내 근로 장학생"
    assert body[0]["apply_end"] == "2026-03-20"
    assert body[0]["hidden"] is False
    assert body[0]["conditions"][0]["type"] == "unresolved"
    assert body[0]["url"] == "https://example/hq:1"
    assert body[0]["reason"] == "열람 불가"


def test_raw_sources_come_with_highlights_even_for_a_hidden_card(client):
    add_card(client.db_path, conditions=[GPA_COND], hidden=1)
    body = client.get("/admin/api/notices/hq:1/raw", auth=AUTH).json()
    assert [s["id"] for s in body] == [1]
    assert body[0]["label"] == "본문"
    start, end = body[0]["highlights"][0]
    assert body[0]["text"][start:end] == GPA_COND["quote"]


def test_raw_sources_of_an_unknown_notice_are_404(client):
    assert client.get("/admin/api/notices/none:1/raw", auth=AUTH).status_code == 404


# --- correcting one review (SPEC 8.5) ---


def test_a_correction_rejudges_every_student_who_entered_something(client):
    add_card(client.db_path, conditions=[unresolved()])
    review_id = add_review(client.db_path)
    add_student(client.db_path, "s1", {"credits_last": 15})   # false -> true
    add_student(client.db_path, "s2", {"credits_last": 9})    # stays false
    add_student(client.db_path, "s3", {})                     # not counted

    res = client.put(f"/admin/api/reviews/{review_id}", auth=AUTH,
                     json={"condition": dict(CREDITS_FIX, id="ignored")})
    assert res.status_code == 200
    assert res.json() == {"resolved": True, "rejudged": 2, "newly_eligible": 1}

    conditions = json.loads(card_row(client.db_path)["conditions"])
    assert conditions == [dict(CREDITS_FIX, id="c1")]  # keeps the id it replaced
    assert review_row(client.db_path, review_id)["resolved"] == 1


def test_a_card_wide_review_stays_until_the_last_unresolved_condition_is_gone(client):
    add_card(client.db_path, conditions=[unresolved("c1"), unresolved("c2")])
    review_id = add_review(client.db_path, condition_id=None)

    first = client.put(f"/admin/api/reviews/{review_id}", auth=AUTH,
                       json={"condition": CREDITS_FIX}).json()
    assert first["resolved"] is False
    conditions = json.loads(card_row(client.db_path)["conditions"])
    assert [c["id"] for c in conditions] == ["c1", "c2"]
    assert conditions[0]["type"] == "credits"

    second = client.put(f"/admin/api/reviews/{review_id}", auth=AUTH,
                        json={"condition": CREDITS_FIX}).json()
    assert second["resolved"] is True
    assert review_row(client.db_path, review_id)["resolved"] == 1


def test_hiding_or_moving_the_deadline_leaves_the_review_in_the_queue(client):
    add_card(client.db_path, conditions=[unresolved()])
    review_id = add_review(client.db_path)

    res = client.put(f"/admin/api/reviews/{review_id}", auth=AUTH,
                     json={"hidden": True, "apply_end": "2026-04-01"})
    assert res.json() == {"resolved": False, "rejudged": 0, "newly_eligible": 0}
    row = card_row(client.db_path)
    assert row["hidden"] == 1 and row["apply_end"] == "2026-04-01"
    assert review_row(client.db_path, review_id)["resolved"] == 0
    assert [r["id"] for r in client.get("/admin/api/reviews", auth=AUTH).json()] == [review_id]


def test_keys_left_out_stay_as_they_were(client):
    add_card(client.db_path, conditions=[unresolved()], apply_end="2026-03-20")
    review_id = add_review(client.db_path)
    client.put(f"/admin/api/reviews/{review_id}", auth=AUTH, json={"hidden": True})
    row = card_row(client.db_path)
    assert row["apply_end"] == "2026-03-20"
    assert json.loads(row["conditions"])[0]["type"] == "unresolved"


@pytest.mark.parametrize(
    "body, why",
    [
        ({"note": "x"}, "an unknown key"),
        ({"condition": dict(CREDITS_FIX, type="unresolved", params={"reason": "x"})},
         "a corrected condition may not be unresolved"),
        ({"condition": dict(CREDITS_FIX, label="")}, "an empty label"),
        ({"condition": dict(CREDITS_FIX, need=" ")}, "an empty need"),
        ({"condition": dict(CREDITS_FIX, quote="")}, "an empty quote"),
        ({"condition": dict(CREDITS_FIX, quote="원문에 없는 문장")}, "a quote that is not there"),
        ({"condition": dict(CREDITS_FIX, source_id=999)}, "a quote from another source"),
        ({"condition": dict(CREDITS_FIX, params={"min": 12})}, "params keys off the 6.2 table"),
        ({"condition": dict(CREDITS_FIX, params={"min": "12", "scope": "last"})},
         "a params value of the wrong shape"),
        ({"condition": dict(CREDITS_FIX, type="없는type")}, "a type off the 6.2 table"),
        ({"apply_end": "2026/04/01"}, "a date that is not YYYY-MM-DD"),
        ({"apply_end": 20260401}, "a date that is not a string"),
        ({"hidden": "yes"}, "a hidden that is not a bool"),
    ],
)
def test_a_correction_that_breaks_the_rules_is_422(client, body, why):
    add_card(client.db_path, conditions=[unresolved()])
    review_id = add_review(client.db_path)
    assert client.put(f"/admin/api/reviews/{review_id}", auth=AUTH, json=body).status_code == 422, why


def test_a_deadline_before_a_task_due_is_422(client):
    add_card(client.db_path, conditions=[unresolved()])
    add_task(client.db_path, "hq:1", "2026-03-18")
    review_id = add_review(client.db_path)
    assert client.put(f"/admin/api/reviews/{review_id}", auth=AUTH,
                      json={"apply_end": "2026-03-17"}).status_code == 422
    assert client.put(f"/admin/api/reviews/{review_id}", auth=AUTH,
                      json={"apply_end": None}).status_code == 422
    assert client.put(f"/admin/api/reviews/{review_id}", auth=AUTH,
                      json={"apply_end": "2026-03-18"}).status_code == 200


def test_a_card_without_readable_text_can_only_be_hidden_or_moved(client):
    add_card(client.db_path, conditions=[unresolved()], text="")
    review_id = add_review(client.db_path)
    assert client.put(f"/admin/api/reviews/{review_id}", auth=AUTH,
                      json={"condition": CREDITS_FIX}).status_code == 422
    assert client.put(f"/admin/api/reviews/{review_id}", auth=AUTH,
                      json={"hidden": True}).status_code == 200


def test_a_condition_sent_to_a_review_that_covers_none_is_422(client):
    add_card(client.db_path, conditions=[GPA_COND])
    review_id = add_review(client.db_path)
    assert client.put(f"/admin/api/reviews/{review_id}", auth=AUTH,
                      json={"condition": CREDITS_FIX}).status_code == 422


def test_an_unknown_or_resolved_review_is_404(client):
    add_card(client.db_path, conditions=[unresolved()])
    review_id = add_review(client.db_path)
    assert client.put("/admin/api/reviews/999", auth=AUTH, json={"hidden": True}).status_code == 404
    client.put(f"/admin/api/reviews/{review_id}", auth=AUTH, json={"condition": CREDITS_FIX})
    assert client.put(f"/admin/api/reviews/{review_id}", auth=AUTH,
                      json={"hidden": True}).status_code == 404


def test_a_review_whose_card_is_gone_is_404(client):
    review_id = add_review(client.db_path, key="hq:9")
    conn = db.connect(client.db_path)
    with conn:
        conn.execute(
            "INSERT INTO notice (key, source_id, source_name, url, title, posted_date,"
            " body_text, attachments, body_hash, crawled_at)"
            " VALUES ('hq:9', 'hq', '게시판', 'u', '공지', '2026-03-01', '', '[]', 'h', 'c')"
        )
    conn.close()
    assert client.put(f"/admin/api/reviews/{review_id}", auth=AUTH,
                      json={"hidden": True}).status_code == 404
