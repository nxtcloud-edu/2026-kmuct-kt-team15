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


def test_detail_tasks_come_in_ord_order(client):
    # SPEC 6.1 task_template.ord, SPEC 7 상세: neither the title, the due date nor the
    # row id may decide the order, so none of them matches the expected list here.
    add_card(client.db_path, "hq:1")
    add_task(client.db_path, "hq:1", "나 서류 준비", "2026-03-12", ord_=3)
    add_task(client.db_path, "hq:1", "다 신청서 작성", "2026-03-16", ord_=1)
    add_task(client.db_path, "hq:1", "가 증명서 발급", "2026-03-20", ord_=2)
    new_student(client)
    tasks = client.get("/api/notices/hq:1").json()["tasks"]
    assert [t["title"] for t in tasks] == ["다 신청서 작성", "가 증명서 발급", "나 서류 준비"]


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


def test_alt_breaks_a_deadline_tie_by_key(client):
    # SPEC 8.2 "마감이 같으면 key 오름차순으로 앞의 것이다". The NEW card is first in the
    # list although its key sorts last, so the list order cannot stand in for the rule.
    add_card(client.db_path, "hq:fail", conditions=[major_cond()], category="장학",
             apply_end="2026-03-20")
    add_card(client.db_path, "hq:zeta", category="장학", apply_end="2026-03-18", demo_new=1)
    add_card(client.db_path, "hq:beta", category="장학", apply_end="2026-03-18")
    add_card(client.db_path, "hq:gamma", category="장학", apply_end="2026-03-18")
    new_student(client)
    client.put("/api/me", json={"major": "경영학부"})
    client.post("/api/reveal-new")
    assert keys_of(client) == ["hq:zeta", "hq:beta", "hq:gamma", "hq:fail"]
    assert client.get("/api/notices/hq:fail").json()["alt"]["key"] == "hq:beta"


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


# --- the raw sheet (SPEC 7 원문 시트) ------------------------------------------


def add_source(path, key, ord_, kind, label, url, text):
    conn = db.connect(path)
    with conn:
        cur = conn.execute(
            "INSERT INTO raw_source (notice_key, ord, kind, label, url, text, confidence)"
            " VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (key, ord_, kind, label, url, text),
        )
        source_id = cur.lastrowid
    conn.close()
    return source_id


def quote_cond(cond_id, source_id, quote, ctype="none", label="지원 자격", need="재학생 누구나"):
    return {"id": cond_id, "type": ctype, "label": label, "need": need, "params": {},
            "source_id": source_id, "quote": quote}


BODY = "3월 학사 안내입니다. 전체 평점평균 3.0/4.5 이상인 자가 신청합니다."
SHEET = "붙임 서류: 신청서 1부. 재학생 누구나 신청할 수 있습니다."
GPA_QUOTE = "전체 평점평균 3.0/4.5 이상인 자"


def test_raw_sheet_path_sections_and_highlights(client):
    add_card(client.db_path, "hq:1")
    body_id = add_source(client.db_path, "hq:1", 1, "body", "본문", "https://example/hq:1", BODY)
    file_id = add_source(client.db_path, "hq:1", 2, "attachment", "붙임1.pdf",
                         "https://example/hq:1.pdf", SHEET)
    add_card(client.db_path, "hq:1", conditions=[
        quote_cond("c1", body_id, GPA_QUOTE),
        quote_cond("c2", file_id, "재학생 누구나"),
    ])
    new_student(client)
    body = client.get("/api/notices/hq:1/raw").json()
    assert body["path"] == "본문 → 붙임1.pdf"
    assert [s["kind"] for s in body["sections"]] == ["body", "attachment"]
    assert body["sections"][0] == {
        "kind": "body", "label": "본문", "url": "https://example/hq:1", "text": BODY,
        "highlights": [[BODY.index(GPA_QUOTE), BODY.index(GPA_QUOTE) + len(GPA_QUOTE)]],
    }
    start, end = body["sections"][0]["highlights"][0]
    assert BODY[start:end] == GPA_QUOTE
    start, end = body["sections"][1]["highlights"][0]
    assert SHEET[start:end] == "재학생 누구나"


def test_raw_sheet_marks_only_the_section_the_quote_came_from(client):
    add_card(client.db_path, "hq:1")
    body_id = add_source(client.db_path, "hq:1", 1, "body", "본문", "https://example/hq:1", BODY)
    add_source(client.db_path, "hq:1", 2, "image", "이미지 1", "https://example/1.png", BODY)
    add_card(client.db_path, "hq:1", conditions=[quote_cond("c1", body_id, "전체 평점평균")])
    new_student(client)
    sections = client.get("/api/notices/hq:1/raw").json()["sections"]
    assert sections[0]["highlights"] == [[BODY.index("전체 평점평균"),
                                          BODY.index("전체 평점평균") + len("전체 평점평균")]]
    assert sections[1]["highlights"] == []


def test_raw_sheet_skips_empty_quotes_and_repeats(client):
    add_card(client.db_path, "hq:1")
    body_id = add_source(client.db_path, "hq:1", 1, "body", "본문", "https://example/hq:1", BODY)
    add_card(client.db_path, "hq:1", conditions=[
        quote_cond("c1", body_id, "신청합니다"),
        quote_cond("c2", body_id, "3월 학사"),
        quote_cond("c3", body_id, "3월 학사"),                      # the same span once
        {"id": "c4", "type": "unresolved", "label": "지원 자격", "need": "확인 중",
         "params": {"reason": "못 찾음"}, "source_id": body_id, "quote": ""},
        quote_cond("c5", body_id, "이 공지에 없는 문장"),
    ])
    new_student(client)
    sections = client.get("/api/notices/hq:1/raw").json()["sections"]
    assert sections[0]["highlights"] == [
        [0, len("3월 학사")],
        [BODY.index("신청합니다"), BODY.index("신청합니다") + len("신청합니다")],
    ]


def test_raw_sheet_of_an_invisible_card_is_404(client):
    add_card(client.db_path, "hq:hidden", hidden=1)
    add_source(client.db_path, "hq:hidden", 1, "body", "본문", "https://example/x", BODY)
    new_student(client)
    assert client.get("/api/notices/hq:hidden/raw").status_code == 404
    assert client.get("/api/notices/hq:nothing/raw").status_code == 404
    del client.headers["X-Student-Id"]
    assert client.get("/api/notices/hq:hidden/raw").status_code == 401


# --- assumed judging (SPEC 7 POST /api/judge) ---------------------------------


def test_judge_uses_overrides_and_keeps_the_order(client):
    add_card(client.db_path, "hq:a", conditions=[gpa_cond(3.0)])
    add_card(client.db_path, "hq:b", conditions=[gpa_cond(4.0)])
    new_student(client)
    client.put("/api/me", json={"gpa": 2.8})
    body = client.post("/api/judge", json={"notice_keys": ["hq:b", "hq:a"],
                                           "overrides": {"gpa": 3.5}}).json()
    assert [r["eligible"] for r in body] == [False, True]
    assert body[1]["rows"][0]["have"] == "3.50"
    assert body[0]["gap"] == "학점 0.50 부족"
    assert list(body[0]) == ["eligible", "gap", "rows"]


def test_judge_without_overrides_uses_the_saved_profile(client):
    add_card(client.db_path, "hq:a", conditions=[gpa_cond(3.0)])
    new_student(client)
    client.put("/api/me", json={"gpa": 3.52})
    assert client.post("/api/judge", json={"notice_keys": ["hq:a"]}).json()[0]["eligible"] is True


def test_judge_stores_nothing(client):
    add_card(client.db_path, "hq:a", conditions=[gpa_cond(3.0)])
    new_student(client)
    client.put("/api/me", json={"gpa": 2.8, "history": {"징계 이력": False}})
    client.post("/api/judge", json={"notice_keys": ["hq:a"],
                                    "overrides": {"gpa": 3.9, "history": {"편입생": True}}})
    assert client.get("/api/me").json()["profile"] == {"gpa": 2.8, "history": {"징계 이력": False}}


def test_judge_merges_history_overrides_flag_by_flag(client):
    flag = {"id": "c1", "type": "history", "label": "징계 이력", "need": "없음",
            "params": {"flag": "징계 이력", "must": False}, "source_id": 1, "quote": "징계"}
    add_card(client.db_path, "hq:a", conditions=[flag])
    new_student(client)
    client.put("/api/me", json={"history": {"징계 이력": False}})
    body = client.post("/api/judge", json={"notice_keys": ["hq:a"],
                                           "overrides": {"history": {"편입생": True}}}).json()
    assert body[0]["eligible"] is True  # the flag that was already there survives


@pytest.mark.parametrize("overrides", [{"gpa": 9}, {"semesters": 4.5}, {"나이": 20},
                                       {"lang_type": "TOEIC"}])
def test_judge_refuses_bad_overrides(client, overrides):
    add_card(client.db_path, "hq:a", conditions=[gpa_cond()])
    new_student(client)
    res = client.post("/api/judge", json={"notice_keys": ["hq:a"], "overrides": overrides})
    assert res.status_code == 422


def test_judge_refuses_bad_notice_keys(client):
    new_student(client)
    assert client.post("/api/judge", json={}).status_code == 422
    assert client.post("/api/judge", json={"notice_keys": "hq:a"}).status_code == 422
    assert client.post("/api/judge", json={"notice_keys": [1]}).status_code == 422


def test_judge_404_for_a_card_outside_the_list(client):
    add_card(client.db_path, "hq:a", conditions=[gpa_cond()])
    add_card(client.db_path, "hq:hidden", hidden=1)
    new_student(client)
    res = client.post("/api/judge", json={"notice_keys": ["hq:a", "hq:hidden"]})
    assert res.status_code == 404
    assert client.post("/api/judge", json={"notice_keys": ["hq:nothing"]}).status_code == 404


# --- the ask-back card (SPEC 7 되묻기 카드, 10.1 A7, A10) ----------------------


def income_cond(maximum=8):
    return {"id": "c1", "type": "income", "label": "소득 분위", "need": f"{maximum}분위 이하",
            "params": {"max": maximum}, "source_id": 1, "quote": "소득"}


def test_ask_is_null_without_a_held_notice(client):
    add_card(client.db_path, "hq:a", conditions=[gpa_cond()])
    new_student(client)
    assert client.get("/api/ask").json() is None      # gpa is an onboarding key
    client.put("/api/me", json={"gpa": 3.52})
    assert client.get("/api/ask").json() is None


def test_ask_picks_the_key_that_unlocks_the_most(client):
    add_card(client.db_path, "hq:a", conditions=[last_gpa_cond(3.5)], apply_end="2026-03-18")
    add_card(client.db_path, "hq:b", conditions=[last_gpa_cond(3.0)], apply_end="2026-03-19")
    add_card(client.db_path, "hq:c", conditions=[income_cond(8)], apply_end="2026-03-20")
    new_student(client)
    assert client.get("/api/ask").json() == {
        "field": "gpa_last",
        "question": "직전 학기 평점이 어느 구간인가요?",
        "unlock": 2,
        "choices": [{"label": "3.5 이상", "value": {"min": 3.5, "max": None}},
                    {"label": "3.0 ~ 3.5", "value": {"min": 3.0, "max": 3.49}},
                    {"label": "3.0 미만", "value": {"min": None, "max": 2.99}}],
    }


def test_ask_asks_a_history_flag_with_yes_and_no(client):
    flag = {"id": "c1", "type": "history", "label": "편입생", "need": "해당",
            "params": {"flag": "편입생", "must": True}, "source_id": 1, "quote": "편입생"}
    add_card(client.db_path, "hq:a", conditions=[flag])
    new_student(client)
    card = client.get("/api/ask").json()
    assert card["field"] == "history:편입생"
    assert card["question"] == "'편입생'에 해당하나요?"
    assert card["choices"] == [{"label": "예", "value": True},
                               {"label": "아니오", "value": False}]


def test_ask_ignores_a_card_outside_the_list(client):
    # SPEC 10.1 A7
    add_card(client.db_path, "hq:hidden", conditions=[last_gpa_cond()], hidden=1)
    add_card(client.db_path, "hq:closed", conditions=[last_gpa_cond()], apply_end="2026-03-15")
    new_student(client)
    assert client.get("/api/ask").json() is None


def test_ask_with_a_given_field(client):
    # SPEC 10.1 A10: a card with a `fail` row still counts when the key is given.
    add_card(client.db_path, "hq:a", conditions=[major_cond(), last_gpa_cond(3.5)])
    new_student(client)
    client.put("/api/me", json={"major": "경영학부"})
    assert client.get("/api/ask").json() is None      # the card has a fail row
    card = client.get("/api/ask", params={"field": "gpa_last"}).json()
    assert card["field"] == "gpa_last"
    assert card["unlock"] == 1


@pytest.mark.parametrize("field", ["gpa", "langs", "major", "topik", "history:외국인 유학생",
                                   "없는키", ""])
def test_ask_refuses_a_field_without_a_question(client, field):
    # SPEC 10.1 A10
    add_card(client.db_path, "hq:a", conditions=[last_gpa_cond()])
    new_student(client)
    assert client.get("/api/ask", params={"field": field}).status_code == 422


def test_ask_with_a_field_nobody_is_missing_is_null(client):
    add_card(client.db_path, "hq:a", conditions=[last_gpa_cond()])
    new_student(client)
    assert client.get("/api/ask", params={"field": "credits_last"}).json() is None


def test_answering_the_ask_decides_those_rows(client):
    add_card(client.db_path, "hq:a", conditions=[last_gpa_cond(3.5)], apply_end="2026-03-18")
    add_card(client.db_path, "hq:b", conditions=[last_gpa_cond(3.0)], apply_end="2026-03-19")
    new_student(client)
    card = client.get("/api/ask").json()
    assert card["unlock"] == 2
    for choice in card["choices"]:  # every choice value passes PATCH (SPEC 8.1 step 3)
        assert client.patch("/api/me", json={card["field"]: choice["value"]}).status_code == 200
    client.patch("/api/me", json={card["field"]: card["choices"][1]["value"]})  # "3.0 ~ 3.5"
    items = {i["key"]: i for i in client.get("/api/notices").json()["items"]}
    assert items["hq:a"]["rows"][0]["status"] == "fail"
    assert items["hq:b"]["rows"][0]["status"] == "pass"
    assert client.get("/api/ask").json() is None


def admission_cond(minimum=2023, maximum=2026):
    return {"id": "c1", "type": "admission_year", "label": "입학 연도",
            "need": f"{minimum}년 이후 입학", "params": {"min": minimum, "max": maximum},
            "source_id": 1, "quote": "입학"}


def test_answering_an_income_ask_decides_those_rows(client):
    # SPEC 10.1 J20: max 10 gives the boundary 11, which is dropped, so every choice
    # value still passes PATCH.
    add_card(client.db_path, "hq:a", conditions=[income_cond(5)], apply_end="2026-03-18")
    add_card(client.db_path, "hq:b", conditions=[income_cond(10)], apply_end="2026-03-19")
    new_student(client)
    card = client.get("/api/ask").json()
    assert card["field"] == "income_bracket" and card["unlock"] == 2
    assert [c["label"] for c in card["choices"]] == ["6분위 이상", "6분위 미만"]
    for choice in card["choices"]:
        assert client.patch("/api/me", json={card["field"]: choice["value"]}).status_code == 200
    client.patch("/api/me", json={card["field"]: card["choices"][0]["value"]})  # "6분위 이상"
    items = {i["key"]: i for i in client.get("/api/notices").json()["items"]}
    assert items["hq:a"]["rows"][0]["status"] == "fail"
    assert items["hq:b"]["rows"][0]["status"] == "pass"


def test_answering_an_admission_year_ask_decides_those_rows(client):
    # SPEC 10.1 J20: max 2026 gives 2027, which is dropped, so "2027년 이상" never
    # reaches PATCH (that was the 422 of checkpoint 1).
    add_card(client.db_path, "hq:a", conditions=[admission_cond(2023, 2026)])
    new_student(client)
    card = client.get("/api/ask").json()
    assert card["field"] == "admission_year" and card["unlock"] == 1
    assert [c["label"] for c in card["choices"]] == ["2023년 이상", "2023년 미만"]
    for choice in card["choices"]:
        assert client.patch("/api/me", json={card["field"]: choice["value"]}).status_code == 200
    client.patch("/api/me", json={card["field"]: card["choices"][0]["value"]})  # "2023년 이상"
    items = {i["key"]: i for i in client.get("/api/notices").json()["items"]}
    assert items["hq:a"]["rows"][0]["status"] == "pass"
    client.patch("/api/me", json={"admission_year": card["choices"][1]["value"]})
    items = {i["key"]: i for i in client.get("/api/notices").json()["items"]}
    assert items["hq:a"]["rows"][0]["status"] == "fail"


def test_ask_and_judge_need_a_student(client):
    assert client.get("/api/ask").status_code == 401
    assert client.post("/api/judge", json={"notice_keys": []}).status_code == 401


# --- the plan (SPEC 7 계획과 할 일, 8.2, 10.1 A5, A6) --------------------------


def plan_keys(client):
    return [item["key"] for item in client.get("/api/plan").json()["items"]]


def test_plan_lists_by_deadline_with_a_null_alt(client):
    # SPEC 10.1 A6
    add_card(client.db_path, "hq:late", apply_end="2026-03-30", fields=[["제출 서류", "신청서"]])
    add_card(client.db_path, "hq:soon", apply_end="2026-03-19")
    new_student(client)
    assert client.post("/api/plan/hq:late").status_code == 204
    assert client.post("/api/plan/hq:soon").status_code == 204
    items = client.get("/api/plan").json()["items"]
    assert [i["key"] for i in items] == ["hq:soon", "hq:late"]
    assert items[1]["fields"] == [["제출 서류", "신청서"]]
    assert items[1]["posted_date"] == "2026-03-01"
    assert all(i["alt"] is None and i["planned"] is True for i in items)


def test_plan_keeps_a_null_alt_even_when_the_card_turns_ineligible(client):
    add_card(client.db_path, "hq:sw", conditions=[major_cond()], category="장학")
    add_card(client.db_path, "hq:other", category="장학", apply_end="2026-03-18")
    new_student(client)
    client.put("/api/me", json={"major": "소프트웨어학부"})
    client.post("/api/plan/hq:sw")
    client.put("/api/me", json={"major": "경영학부"})
    assert client.get("/api/notices/hq:sw").json()["alt"]["key"] == "hq:other"
    assert client.get("/api/plan").json()["items"][0]["alt"] is None


def test_plan_refuses_a_card_the_student_cannot_apply_to(client):
    # SPEC 10.1 A5: "확인 필요" counts as not eligible too.
    add_card(client.db_path, "hq:gpa", conditions=[gpa_cond()])
    add_card(client.db_path, "hq:last", conditions=[last_gpa_cond()])
    add_card(client.db_path, "hq:unresolved", conditions=[
        {"id": "c1", "type": "unresolved", "label": "지원 자격", "need": "확인 중",
         "params": {"reason": "못 찾음"}, "source_id": 1, "quote": ""}])
    add_card(client.db_path, "hq:open", conditions=[none_cond()])
    new_student(client)
    assert client.post("/api/plan/hq:gpa").status_code == 409
    assert client.post("/api/plan/hq:last").status_code == 409
    assert client.post("/api/plan/hq:unresolved").status_code == 409
    assert client.post("/api/plan/hq:open").status_code == 204
    assert plan_keys(client) == ["hq:open"]
    client.put("/api/me", json={"gpa": 3.52})
    assert client.post("/api/plan/hq:gpa").status_code == 204


def test_plan_add_is_404_outside_the_list_and_repeats_are_fine(client):
    add_card(client.db_path, "hq:ok")
    add_card(client.db_path, "hq:hidden", hidden=1)
    new_student(client)
    assert client.post("/api/plan/hq:hidden").status_code == 404
    assert client.post("/api/plan/hq:nothing").status_code == 404
    assert client.post("/api/plan/hq:ok").status_code == 204
    assert client.post("/api/plan/hq:ok").status_code == 204
    assert plan_keys(client) == ["hq:ok"]


def test_plan_delete_is_204_even_when_it_was_never_there(client):
    add_card(client.db_path, "hq:ok")
    new_student(client)
    client.post("/api/plan/hq:ok")
    assert client.delete("/api/plan/hq:ok").status_code == 204
    assert plan_keys(client) == []
    assert client.delete("/api/plan/hq:ok").status_code == 204
    assert client.delete("/api/plan/hq:nothing").status_code == 204


def test_plan_drops_a_card_that_left_the_list(client):
    add_card(client.db_path, "hq:ok")
    new_student(client)
    client.post("/api/plan/hq:ok")
    conn = db.connect(client.db_path)
    with conn:
        conn.execute("UPDATE card SET hidden = 1 WHERE notice_key = 'hq:ok'")
    conn.close()
    assert plan_keys(client) == []


# --- tasks (SPEC 7 PUT /api/tasks/{id}) ---------------------------------------


def test_task_check_and_uncheck_survive_a_reload(client):
    add_card(client.db_path, "hq:ok")
    task_id = add_task(client.db_path, "hq:ok", "신청서 제출", "2026-03-20")
    new_student(client)
    client.post("/api/plan/hq:ok")
    assert client.put(f"/api/tasks/{task_id}", json={"done": True}).status_code == 204
    assert client.get("/api/plan").json()["items"][0]["tasks"][0]["done"] is True
    assert client.get("/api/notices/hq:ok").json()["tasks"][0]["done"] is True
    assert client.put(f"/api/tasks/{task_id}", json={"done": True}).status_code == 204
    assert client.put(f"/api/tasks/{task_id}", json={"done": False}).status_code == 204
    assert client.get("/api/notices/hq:ok").json()["tasks"][0]["done"] is False


def test_task_of_an_unplanned_card_can_be_checked(client):
    add_card(client.db_path, "hq:ok")
    task_id = add_task(client.db_path, "hq:ok", "성적증명서 발급", "2026-03-18")
    new_student(client)
    assert client.put(f"/api/tasks/{task_id}", json={"done": True}).status_code == 204
    assert client.get("/api/notices/hq:ok").json()["tasks"][0]["done"] is True


def test_task_refuses_an_unknown_id_and_a_bad_body(client):
    add_card(client.db_path, "hq:ok")
    task_id = add_task(client.db_path, "hq:ok", "신청서 제출", "2026-03-20")
    new_student(client)
    assert client.put("/api/tasks/9999", json={"done": True}).status_code == 404
    assert client.put(f"/api/tasks/{task_id}", json={}).status_code == 422
    assert client.put(f"/api/tasks/{task_id}", json={"done": "yes"}).status_code == 422


def test_two_students_keep_their_own_plan_and_checks(client):
    add_card(client.db_path, "hq:ok")
    task_id = add_task(client.db_path, "hq:ok", "신청서 제출", "2026-03-20")
    first = new_student(client)
    client.post("/api/plan/hq:ok")
    client.put(f"/api/tasks/{task_id}", json={"done": True})
    new_student(client)
    assert plan_keys(client) == []
    assert client.get("/api/notices/hq:ok").json()["tasks"][0]["done"] is False
    client.headers["X-Student-Id"] = first
    assert plan_keys(client) == ["hq:ok"]
    assert client.get("/api/plan").json()["items"][0]["tasks"][0]["done"] is True


# --- alerts (SPEC 7 알림 kind, 8.1 알림, 10.1 A13) -----------------------------


def test_alerts_are_empty_without_anything_to_say(client):
    add_card(client.db_path, "hq:ok")
    new_student(client)
    assert client.get("/api/alerts").json() == []


def test_alerts_keep_the_new_deadline_today_order(client):
    # SPEC 10.1 A13
    add_card(client.db_path, "hq:new", title="OK프렌즈 서포터즈", apply_end="2026-03-25",
             demo_new=1)
    add_card(client.db_path, "hq:soon", title="희망사다리 장학금", apply_end="2026-03-19")
    add_card(client.db_path, "hq:task", title="국가근로 장학금", apply_end="2026-03-25")
    done_id = add_task(client.db_path, "hq:task", "이미 한 일", TODAY, ord_=1)
    add_task(client.db_path, "hq:task", "신청서 제출", TODAY, ord_=2)
    add_task(client.db_path, "hq:task", "나중에 할 일", "2026-03-25", ord_=3)
    new_student(client)
    client.post("/api/reveal-new")
    client.post("/api/plan/hq:soon")
    client.post("/api/plan/hq:task")
    client.put(f"/api/tasks/{done_id}", json={"done": True})
    assert client.get("/api/alerts").json() == [
        {"kind": "new", "title": "새 기회를 찾았어요",
         "body": "OK프렌즈 서포터즈 · 내 조건으로 지원할 수 있어요", "notice_key": "hq:new"},
        {"kind": "deadline", "title": "희망사다리 장학금 마감이 3일 남았어요", "body": "",
         "notice_key": "hq:soon"},
        {"kind": "today", "title": "오늘 할 일", "body": "신청서 제출", "notice_key": "hq:task"},
    ]


def test_alerts_skip_a_new_card_the_student_cannot_apply_to(client):
    add_card(client.db_path, "hq:new", conditions=[gpa_cond(4.0)], demo_new=1)
    new_student(client)
    client.put("/api/me", json={"gpa": 3.0})
    client.post("/api/reveal-new")
    assert client.get("/api/alerts").json() == []


def test_alerts_only_watch_the_planned_cards(client):
    add_card(client.db_path, "hq:soon", apply_end="2026-03-19")
    add_card(client.db_path, "hq:task")
    add_task(client.db_path, "hq:task", "신청서 제출", TODAY)
    new_student(client)
    assert client.get("/api/alerts").json() == []  # nothing is in the plan yet
    client.post("/api/plan/hq:soon")
    assert [a["kind"] for a in client.get("/api/alerts").json()] == ["deadline"]


# --- revealing the demo_new card (SPEC 7, 10.1 A8) ----------------------------


def test_reveal_new_shows_the_card_once_and_only_to_that_student(client):
    # SPEC 10.1 A8
    add_card(client.db_path, "hq:ok")
    add_card(client.db_path, "hq:new", title="OK프렌즈 서포터즈", apply_end="2026-03-25",
             demo_new=1)
    first = new_student(client)
    assert keys_of(client) == ["hq:ok"]
    body = client.post("/api/reveal-new").json()
    assert [i["key"] for i in body["items"]] == ["hq:new"]
    assert body["items"][0]["is_new"] is True
    assert body["items"][0]["title"] == "OK프렌즈 서포터즈"
    assert keys_of(client) == ["hq:new", "hq:ok"]
    assert client.post("/api/reveal-new").json() == {"items": []}
    assert keys_of(client) == ["hq:new", "hq:ok"]
    new_student(client)
    assert keys_of(client) == ["hq:ok"]
    client.headers["X-Student-Id"] = first
    assert keys_of(client) == ["hq:new", "hq:ok"]


def test_reveal_new_without_a_demo_card_gives_nothing(client):
    add_card(client.db_path, "hq:ok")
    new_student(client)
    assert client.post("/api/reveal-new").json() == {"items": []}


def test_plan_tasks_alerts_and_reveal_need_a_student(client):
    assert client.get("/api/plan").status_code == 401
    assert client.post("/api/plan/hq:ok").status_code == 401
    assert client.delete("/api/plan/hq:ok").status_code == 401
    assert client.put("/api/tasks/1", json={"done": True}).status_code == 401
    assert client.get("/api/alerts").status_code == 401
    assert client.post("/api/reveal-new").status_code == 401
