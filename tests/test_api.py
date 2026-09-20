"""API tests (SPEC 7, 10). Temp DB, FastAPI TestClient."""

import json
import os

import pytest
from fastapi.testclient import TestClient

from app import db

TODAY = "2026-03-16"


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = str(tmp_path / "api.db")
    monkeypatch.setenv("DB_PATH", path)
    monkeypatch.setenv("DEMO_TODAY", TODAY)
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init(path)
    from app import main

    monkeypatch.setattr(main, "STATIC", main.STATIC)
    with TestClient(main.app) as c:
        c.db_path = path
        yield c


def add_notice(path, key, posted="2026-03-01", title="공지", source="hq"):
    conn = db.connect(path)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO notice (key, source_id, source_name, url, title, posted_date,"
            " department, body_text, attachments, body_hash, crawled_at)"
            " VALUES (?, ?, ?, ?, ?, ?, NULL, '', '[]', ?, '2026-03-01')",
            (key, source, "게시판", "https://example/" + key, title, posted, db.body_hash(title, "")),
        )
    conn.close()


def add_card(path, key, conditions=(), category="장학", apply_start="2026-03-01",
             apply_end="2026-03-20", posted="2026-03-01", title="공지", check_ok=1,
             hidden=0, demo_new=0, linked_to=None, fields=(), sub="부제"):
    """A notice plus its card. Defaults land the card in the 3/16 list (SPEC 7)."""
    add_notice(path, key, posted=posted, title=title)
    conn = db.connect(path)
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO card (notice_key, title, sub, dept, category, apply_start,"
            " apply_end, conditions, fields, trace, linked_to, check_ok, hidden, demo_new,"
            " interpreted_by) VALUES (?, ?, ?, '학생지원팀', ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?,"
            " 'claude-prep')",
            (key, title, sub, category, apply_start, apply_end,
             json.dumps(list(conditions), ensure_ascii=False),
             json.dumps([list(f) for f in fields], ensure_ascii=False),
             linked_to, check_ok, hidden, demo_new),
        )
    conn.close()


def add_task(path, key, title, due, ord_=1):
    conn = db.connect(path)
    with conn:
        cur = conn.execute(
            "INSERT INTO task_template (notice_key, ord, title, due) VALUES (?, ?, ?, ?)",
            (key, ord_, title, due),
        )
        task_id = cur.lastrowid
    conn.close()
    return task_id


def gpa_cond(minimum=3.0):
    return {"id": "c1", "type": "gpa", "label": "평균 학점", "need": f"{minimum} 이상",
            "params": {"min": minimum, "scope": "cumulative"}, "source_id": 1,
            "quote": "평점평균 이상인 자"}


def major_cond(majors=("소프트웨어학부",)):
    return {"id": "c1", "type": "major", "label": "전공", "need": "소프트웨어학부",
            "params": {"majors": list(majors)}, "source_id": 1, "quote": "소프트웨어학부"}


def last_gpa_cond(minimum=3.5):
    return {"id": "c1", "type": "gpa", "label": "직전 학기 평점", "need": f"{minimum} 이상",
            "params": {"min": minimum, "scope": "last"}, "source_id": 1, "quote": "직전 학기"}


def none_cond():
    return {"id": "c1", "type": "none", "label": "지원 자격", "need": "재학생 누구나",
            "params": {}, "source_id": 1, "quote": "재학생 누구나"}


def new_student(client):
    student_id = client.post("/api/students").json()["id"]
    client.headers["X-Student-Id"] = student_id
    return student_id


def test_index_is_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "UniQ" in res.text


def test_config(client):
    add_notice(client.db_path, "a:1", source="a")
    add_notice(client.db_path, "b:1", source="b")
    conn = db.connect(client.db_path)
    with conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('suggested_questions', ?)",
            (json.dumps(["학점 2.8이어도 돼?"], ensure_ascii=False),),
        )
    conn.close()
    body = client.get("/api/config").json()
    assert body == {"today": TODAY, "sources": 2, "suggested_questions": ["학점 2.8이어도 돼?"]}


def test_config_without_meta_gives_an_empty_list(client):
    body = client.get("/api/config").json()
    assert body["suggested_questions"] == []
    assert body["sources"] == 0


# --- students and X-Student-Id (SPEC 7) ---------------------------------------


@pytest.mark.parametrize("path", ["/api/me", "/api/notices", "/api/notices/hq:1"])
def test_student_routes_need_a_known_id(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"X-Student-Id": "nope"}).status_code == 401


def test_new_student_starts_empty(client):
    student_id = new_student(client)
    assert student_id
    body = client.get("/api/me").json()
    assert body == {"profile": {}, "eligible_count": 0}


def test_two_students_get_different_ids(client):
    assert client.post("/api/students").json()["id"] != client.post("/api/students").json()["id"]


# --- profile: PUT and PATCH (SPEC 7, 10.1 A2, A3, A12) ------------------------


def test_put_me_saves_the_whole_profile(client):
    new_student(client)
    profile = {"status": "재학", "semesters": 4, "major": "소프트웨어학부", "gpa": 3.52,
               "langs": {"TOEIC": "850"}, "interests": ["장학"],
               "history": {"외국인 유학생": False}}
    assert client.put("/api/me", json=profile).json()["profile"] == profile
    assert client.get("/api/me").json()["profile"] == profile


def test_put_replaces_and_drops_a_missing_key(client):
    # SPEC 10.1 A3
    new_student(client)
    client.put("/api/me", json={"status": "재학", "gpa_last": 3.4})
    body = client.put("/api/me", json={"status": "재학"}).json()
    assert "gpa_last" not in body["profile"]


def test_patch_merges_history_flag_by_flag(client):
    # SPEC 10.1 A2
    new_student(client)
    client.patch("/api/me", json={"history": {"교내장학 수혜": True}})
    body = client.patch("/api/me", json={"history": {"징계 이력": False}}).json()
    assert body["profile"]["history"] == {"교내장학 수혜": True, "징계 이력": False}
    assert client.patch("/api/me", json={"history:교내장학 수혜": True}).status_code == 422


def test_patch_replaces_langs_whole(client):
    # SPEC 10.1 A12
    new_student(client)
    client.put("/api/me", json={"langs": {"TOEIC": "850", "IELTS": "7.0"}})
    body = client.patch("/api/me", json={"langs": {"OPIc": "IM2"}}).json()
    assert body["profile"]["langs"] == {"OPIc": "IM2"}


def test_patch_keeps_the_other_keys(client):
    new_student(client)
    client.put("/api/me", json={"status": "재학", "semesters": 4})
    body = client.patch("/api/me", json={"gpa_last": {"min": 3.5, "max": 3.79}}).json()
    assert body["profile"] == {"status": "재학", "semesters": 4,
                               "gpa_last": {"min": 3.5, "max": 3.79}}


VALID = [
    {"gpa": None},
    {"gpa": 4.5},
    {"gpa_last": {"min": 3.8, "max": None}},
    {"income_bracket": {"min": None, "max": 5}},
    {"admission_year": 2024},
    {"langs": {}},
    {"langs": {"OPIc": "IM2"}},
    {"langs": {"TOEIC": "990", "IELTS": "9"}},
    {"topik": 0},
    {"topik": 6},
    {"semesters": 8},
    {"credits_total": 250},
    {"history": {"교내장학 수혜": None}},
    {"interests": ["장학", "한국어·문화"]},
    {"grad_year": 2027, "grad_term": "8월", "status": "졸업예정"},
]

INVALID = [
    {"lang_type": "TOEIC"},                    # A11: UI (1) key
    {"lang_score": "850"},                     # A11
    {"langs": {"TOEIC": "999"}},               # A11: TOEIC is 10~990
    {"langs": {"TOEIC": ""}},                  # A11: an empty score
    {"topik": 7},                              # A11: 0~6
    {"gpa": 4.6},
    {"gpa": "3.5"},
    {"semesters": 9},
    {"semesters": 4.0},                        # integers only
    {"semesters": {"min": 2, "max": 4}},       # no range
    {"topik": {"min": 2, "max": 4}},
    {"admission_year": 2024.5},
    {"admission_year": 2027},
    {"admission_year": {"min": 2025, "max": 2023}},
    {"admission_year": {"min": 2023}},         # both ends or neither
    {"credits_last": 31},
    {"credits_total": 10 ** 400},
    {"income_bracket": 11},
    {"income_bracket": True},                  # a bool is not a number
    {"status": "수료"},
    {"status": None},
    {"major": None},
    {"major": ""},
    {"major": "가" * 51},
    {"interests": ["없는 분야"]},
    {"interests": None},
    {"langs": None},
    {"langs": {"TOPIK": "4"}},                 # TOPIK is its own key
    {"langs": {"OPIc": "IM9"}},
    {"history": None},
    {"history": {"교내장학 수혜": "예"}},
    {"history": {"가" * 51: True}},
    {"나이": 20},
]


@pytest.mark.parametrize("profile", VALID)
def test_profile_validation_accepts(client, profile):
    new_student(client)
    assert client.put("/api/me", json=profile).status_code == 200
    assert client.patch("/api/me", json=profile).status_code == 200


@pytest.mark.parametrize("profile", INVALID)
def test_profile_validation_refuses(client, profile):
    # SPEC 10.1 A4, A11
    new_student(client)
    assert client.put("/api/me", json=profile).status_code == 422
    assert client.patch("/api/me", json=profile).status_code == 422


@pytest.mark.parametrize("body", ['{"gpa": NaN}', '{"gpa": Infinity}', '{"gpa": -Infinity}'])
def test_profile_validation_refuses_nan(client, body):
    # SPEC 10.1 A4. json.loads reads these, so the check has to be ours.
    new_student(client)
    res = client.put("/api/me", content=body, headers={"Content-Type": "application/json"})
    assert res.status_code == 422


def test_history_stops_at_100_flags(client):
    new_student(client)
    ok = {"history": {f"flag{i}": True for i in range(100)}}
    assert client.put("/api/me", json=ok).status_code == 200
    assert client.patch("/api/me", json={"history": {"one more": True}}).status_code == 422


# --- the list (SPEC 7 "목록에 보이는 카드") ------------------------------------


def keys_of(client):
    return [item["key"] for item in client.get("/api/notices").json()["items"]]


def test_list_dates(client):
    # SPEC 10.1 A1
    add_card(client.db_path, "hq:end_today", apply_end=TODAY)
    add_card(client.db_path, "hq:start_today", apply_start=TODAY)
    add_card(client.db_path, "hq:posted_today", posted=TODAY)
    add_card(client.db_path, "hq:no_start", apply_start=None)
    add_card(client.db_path, "hq:closed", apply_end="2026-03-15")
    add_card(client.db_path, "hq:not_open_yet", apply_start="2026-03-17")
    add_card(client.db_path, "hq:no_end", apply_end=None)
    add_card(client.db_path, "hq:posted_later", posted="2026-03-17")
    new_student(client)
    assert set(keys_of(client)) == {"hq:end_today", "hq:start_today", "hq:posted_today",
                                    "hq:no_start"}


def test_list_hides_unchecked_hidden_and_linked_cards(client):
    add_card(client.db_path, "hq:ok")
    add_card(client.db_path, "hq:unchecked", check_ok=None)
    add_card(client.db_path, "hq:wrong", check_ok=0)
    add_card(client.db_path, "hq:hidden", hidden=1)
    add_card(client.db_path, "hq:linked", linked_to="hq:ok")
    new_student(client)
    assert keys_of(client) == ["hq:ok"]


def test_list_order_is_new_then_deadline_then_key(client):
    add_card(client.db_path, "hq:b", apply_end="2026-03-20")
    add_card(client.db_path, "hq:a", apply_end="2026-03-20")
    add_card(client.db_path, "hq:early", apply_end="2026-03-18")
    add_card(client.db_path, "hq:fresh", apply_end="2026-03-30", demo_new=1)
    student_id = new_student(client)
    assert keys_of(client) == ["hq:early", "hq:a", "hq:b"]  # demo_new stays hidden
    conn = db.connect(client.db_path)
    with conn:
        conn.execute("UPDATE student SET revealed_new = 1 WHERE id = ?", (student_id,))
    conn.close()
    assert keys_of(client) == ["hq:fresh", "hq:early", "hq:a", "hq:b"]
    assert client.get("/api/notices").json()["items"][0]["is_new"] is True


def test_list_item_shape_and_rows(client):
    add_card(client.db_path, "hq:1", conditions=[gpa_cond()], sub="등록금 일부 감면",
             apply_start="2026-03-09", apply_end="2026-03-20")
    new_student(client)
    client.put("/api/me", json={"gpa": 3.52})
    item = client.get("/api/notices").json()["items"][0]
    assert item == {
        "key": "hq:1", "title": "공지", "sub": "등록금 일부 감면", "dept": "학생지원팀",
        "category": "장학", "apply_start": "2026-03-09", "apply_end": "2026-03-20",
        "is_new": False, "planned": False, "eligible": True, "gap": None,
        "rows": [{"type": "gpa", "label": "평균 학점", "need": "3.0 이상", "status": "pass",
                  "have": "3.52", "gap": "", "chip": "학점 3.0 이상",
                  "tip": "내 평균 학점 3.52", "field": None, "ask": None}],
    }


def test_list_marks_a_planned_card(client):
    add_card(client.db_path, "hq:1")
    student_id = new_student(client)
    conn = db.connect(client.db_path)
    with conn:
        conn.execute("INSERT INTO plan (student_id, notice_key, added_at) VALUES (?, ?, ?)",
                     (student_id, "hq:1", TODAY))
    conn.close()
    assert client.get("/api/notices").json()["items"][0]["planned"] is True


def test_list_judges_each_card_for_this_student(client):
    add_card(client.db_path, "hq:can", conditions=[gpa_cond()])
    add_card(client.db_path, "hq:cannot", conditions=[major_cond()])
    add_card(client.db_path, "hq:missing", conditions=[last_gpa_cond()])
    new_student(client)
    client.put("/api/me", json={"gpa": 3.52, "major": "경영학부"})
    items = {item["key"]: item for item in client.get("/api/notices").json()["items"]}
    assert items["hq:can"]["eligible"] is True
    assert items["hq:cannot"]["eligible"] is False
    assert items["hq:cannot"]["rows"][0]["status"] == "fail"
    assert items["hq:missing"]["rows"][0]["status"] == "missing"
    assert items["hq:missing"]["rows"][0]["field"] == "gpa_last"
    assert client.get("/api/me").json()["eligible_count"] == 1


# --- the detail (SPEC 7 상세, 8.2 alt, 10.1 A9, A13) ---------------------------


def test_detail_adds_url_posted_date_fields_and_tasks(client):
    # SPEC 10.1 A13: posted_date is the notice's own date, not apply_start.
    add_card(client.db_path, "hq:1", posted="2026-03-05", apply_start="2026-03-09",
             fields=[["제출 서류", "신청서"]])
    task_id = add_task(client.db_path, "hq:1", "성적증명서 발급", "2026-03-18")
    student_id = new_student(client)
    body = client.get("/api/notices/hq:1").json()
    assert body["url"] == "https://example/hq:1"
    assert body["posted_date"] == "2026-03-05"
    assert body["fields"] == [["제출 서류", "신청서"]]
    assert body["tasks"] == [{"id": task_id, "title": "성적증명서 발급", "due": "2026-03-18",
                              "done": False}]
    conn = db.connect(client.db_path)
    with conn:
        conn.execute("INSERT INTO task_done (student_id, task_id) VALUES (?, ?)",
                     (student_id, task_id))
    conn.close()
    assert client.get("/api/notices/hq:1").json()["tasks"][0]["done"] is True


def test_detail_of_an_invisible_card_is_404(client):
    add_card(client.db_path, "hq:hidden", hidden=1)
    new_student(client)
    assert client.get("/api/notices/hq:hidden").status_code == 404
    assert client.get("/api/notices/hq:nothing").status_code == 404


def test_alt_picks_the_earliest_of_the_same_category(client):
    # SPEC 10.1 A9
    add_card(client.db_path, "hq:fail", conditions=[major_cond()], category="장학")
    add_card(client.db_path, "hq:late", conditions=[gpa_cond()], category="장학",
             apply_end="2026-03-20")
    add_card(client.db_path, "hq:soon", conditions=[gpa_cond()], category="장학",
             apply_end="2026-03-18")
    add_card(client.db_path, "hq:other", conditions=[none_cond()], category="창업",
             apply_end="2026-03-17")
    new_student(client)
    client.put("/api/me", json={"gpa": 3.52, "major": "경영학부"})
    assert client.get("/api/notices/hq:fail").json()["alt"]["key"] == "hq:soon"


def test_alt_falls_back_to_a_card_without_conditions(client):
    # SPEC 10.1 A9
    add_card(client.db_path, "hq:fail", conditions=[major_cond()], category="장학")
    add_card(client.db_path, "hq:plain", conditions=[], category="창업", apply_end="2026-03-19")
    add_card(client.db_path, "hq:none", conditions=[none_cond()], category="교내활동",
             apply_end="2026-03-18")
    add_card(client.db_path, "hq:with_cond", conditions=[gpa_cond()], category="창업",
             apply_end="2026-03-17")
    new_student(client)
    client.put("/api/me", json={"gpa": 3.52, "major": "경영학부"})
    alt = client.get("/api/notices/hq:fail").json()["alt"]
    assert alt["key"] == "hq:none"
    assert alt["rows"] and alt["eligible"] is True


def test_alt_is_null_without_a_fail_row(client):
    # SPEC 10.1 A9
    add_card(client.db_path, "hq:can", conditions=[gpa_cond()], category="장학")
    add_card(client.db_path, "hq:other", conditions=[], category="장학", apply_end="2026-03-18")
    add_card(client.db_path, "hq:missing", conditions=[last_gpa_cond()], category="장학")
    new_student(client)
    client.put("/api/me", json={"gpa": 3.52})
    assert client.get("/api/notices/hq:can").json()["alt"] is None
    assert client.get("/api/notices/hq:missing").json()["alt"] is None


def test_alt_is_null_when_nothing_fits(client):
    add_card(client.db_path, "hq:fail", conditions=[major_cond()], category="장학")
    add_card(client.db_path, "hq:also_cond", conditions=[gpa_cond(4.0)], category="창업")
    new_student(client)
    client.put("/api/me", json={"gpa": 3.52, "major": "경영학부"})
    assert client.get("/api/notices/hq:fail").json()["alt"] is None


def test_flow_from_new_student_to_detail(client):
    add_card(client.db_path, "hq:scholar", conditions=[gpa_cond()], category="장학",
             apply_end="2026-03-20", title="성적우수 장학금")
    add_card(client.db_path, "hq:sw", conditions=[major_cond()], category="장학",
             apply_end="2026-03-19", title="SW 장학금")
    new_student(client)
    assert client.get("/api/me").json()["eligible_count"] == 0
    client.put("/api/me", json={"status": "재학", "semesters": 4, "major": "경영학부",
                                "gpa": 3.52, "langs": {}, "interests": ["장학"],
                                "history": {"외국인 유학생": False}})
    assert client.get("/api/me").json()["eligible_count"] == 1
    assert keys_of(client) == ["hq:sw", "hq:scholar"]
    detail = client.get("/api/notices/hq:sw").json()
    assert detail["eligible"] is False
    assert detail["gap"] == "소프트웨어학부 대상"
    assert detail["alt"]["key"] == "hq:scholar"
