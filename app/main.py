"""FastAPI app: static files and the /api routes (SPEC 5, 7, 8.2)."""

import json
import math
import os
import secrets
from datetime import datetime

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

from app import db, judge

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(HERE, "static")

app = FastAPI(title="UniQ")

# SPEC 6.3. `interests` and a card's category come from this list.
CATEGORIES = [
    "장학", "인턴·현장실습", "국제교류", "교내활동", "학사·전공",
    "한국어·문화", "창업", "공모전·경진대회", "자격증·어학",
]
STATUSES = ["재학", "휴학", "졸업예정"]
GRAD_TERMS = ["2월", "8월"]
# SPEC 7 "학생 정보 검증": the range of every numeric profile key. judge.KEY_RANGE is
# the same table; grad_year is only displayed, never judged, so it lives here.
NUM_RANGE = dict(judge.KEY_RANGE, grad_year=(2026, 2029))
# Only these two take decimals. Every other numeric key takes integers, range ends
# included, so that "2024.5년" can never be stored (SPEC 7).
DECIMAL_KEYS = ["gpa", "gpa_last"]
# An ask-back answer never makes a range out of these two (SPEC 7).
NO_RANGE_KEYS = ["semesters", "topik"]
# The 6.4 keys that are not numbers. null is a 422 for all of them (SPEC 7).
TEXT_KEYS = ["status", "grad_term", "major", "interests", "langs", "history"]
PROFILE_KEYS = list(NUM_RANGE) + TEXT_KEYS
# SPEC 7: the score range of each written test. OPIc uses judge.OPIC_GRADES instead.
LANG_RANGE = {
    "TOEIC": (10, 990),
    "TOEFL iBT": (0, 120),
    "IELTS": (0, 9),
    "TOEIC Speaking": (0, 200),
}
HISTORY_MAX = 100


def today():
    return os.environ.get("DEMO_TODAY", "2026-03-16")


def bad(message):
    """SPEC 7: a request that breaks the profile rules is a 422."""
    raise HTTPException(status_code=422, detail=message)


def check_scalar(key, value):
    """One plain number of a numeric profile key (SPEC 7)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(f"{key} takes a number")
    if isinstance(value, float) and not math.isfinite(value):
        bad(f"{key} takes a finite number")
    if key not in DECIMAL_KEYS and not isinstance(value, int):
        bad(f"{key} takes an integer")
    low, high = NUM_RANGE[key]
    if not low <= value <= high:
        bad(f"{key} is outside {low}~{high}")


def check_number(key, value):
    """A numeric profile value: a number, an ask-back range, or None (SPEC 7, 6.4)."""
    if value is None:
        return
    if isinstance(value, dict):
        if key in NO_RANGE_KEYS:
            bad(f"{key} takes an integer, not a range")
        if set(value) != {"min", "max"}:
            bad(f"{key} range takes exactly min and max")
        low, high = value["min"], value["max"]
        for end in (low, high):
            if end is not None:
                check_scalar(key, end)
        if low is not None and high is not None and low > high:
            bad(f"{key} range has min above max")
        return
    check_scalar(key, value)


def check_langs(value):
    """SPEC 7: {test: score string}, tests from 6.2's five, score inside its range."""
    if not isinstance(value, dict):
        bad("langs takes an object")
    for test, score in value.items():
        if test not in judge.LANG_TYPES:
            bad(f"unknown language test: {test}")
        if not isinstance(score, str) or not score.strip():
            bad(f"{test} takes a score string")
        if test == "OPIc":
            if score.upper() not in judge.OPIC_GRADES:
                bad("OPIc takes one of " + ", ".join(judge.OPIC_GRADES))
            continue
        try:
            number = float(score)
        except ValueError:
            bad(f"{test} takes a number")
        low, high = LANG_RANGE[test]
        if not low <= number <= high:
            bad(f"{test} is outside {low}~{high}")


def check_history(value):
    """SPEC 7: flags are free text, answers are true, false or null."""
    if not isinstance(value, dict):
        bad("history takes an object")
    if len(value) > HISTORY_MAX:
        bad(f"history keeps at most {HISTORY_MAX} flags")
    for flag, answer in value.items():
        if not 1 <= len(flag) <= 50:
            bad("a history flag is 1~50 characters")
        if answer is not None and not isinstance(answer, bool):
            bad(f"history[{flag}] takes true, false or null")


def check_profile(profile):
    """SPEC 7 "학생 정보 검증". PATCH checks the merged history on top of this."""
    if not isinstance(profile, dict):
        bad("the body takes an object")
    for key, value in profile.items():
        if key not in PROFILE_KEYS:
            # UI (1)'s lang_type and lang_score land here too (SPEC 7).
            bad(f"unknown profile key: {key}")
        if key in NUM_RANGE:
            check_number(key, value)
        elif value is None:
            bad(f"{key} does not take null")
        elif key == "langs":
            check_langs(value)
        elif key == "history":
            check_history(value)
        elif key == "status":
            if value not in STATUSES:
                bad("status takes one of " + ", ".join(STATUSES))
        elif key == "grad_term":
            if value not in GRAD_TERMS:
                bad("grad_term takes one of " + ", ".join(GRAD_TERMS))
        elif key == "major":
            if not isinstance(value, str) or not 1 <= len(value) <= 50:
                bad("major is 1~50 characters")
        elif key == "interests":
            if not isinstance(value, list) or any(v not in CATEGORIES for v in value):
                bad("interests takes the 9 categories of SPEC 6.3")


def current_student(x_student_id: str | None = Header(default=None)):
    """SPEC 7: a student-scoped route needs a known X-Student-Id, or it is a 401."""
    if not x_student_id:
        raise HTTPException(status_code=401, detail="X-Student-Id required")
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM student WHERE id = ?", (x_student_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=401, detail="unknown student")
    try:
        profile = json.loads(row["profile"] or "{}")
    except ValueError:
        profile = {}
    return {"id": row["id"], "profile": profile, "revealed_new": row["revealed_new"]}


def store_profile(student, profile):
    conn = db.connect()
    with conn:
        conn.execute(
            "UPDATE student SET profile = ? WHERE id = ?",
            (json.dumps(profile, ensure_ascii=False), student["id"]),
        )
    conn.close()
    student["profile"] = profile


def visible_rows(conn, student):
    """The cards the list shows, in SPEC 7 order: NEW first, then apply_end, then key."""
    return conn.execute(
        "SELECT c.*, n.url AS notice_url, n.posted_date AS posted_date"
        " FROM card c JOIN notice n ON n.key = c.notice_key"
        " WHERE c.check_ok = 1 AND c.hidden = 0 AND c.linked_to IS NULL"
        "   AND c.apply_end >= ? AND (c.apply_start IS NULL OR c.apply_start <= ?)"
        "   AND n.posted_date <= ? AND (c.demo_new = 0 OR ? = 1)"
        " ORDER BY c.demo_new DESC, c.apply_end, c.notice_key",
        (today(), today(), today(), student["revealed_new"]),
    ).fetchall()


def notice_items(conn, student, rows=None):
    """Every visible card judged for this student (SPEC 7 "목록 항목")."""
    rows = visible_rows(conn, student) if rows is None else rows
    planned = {
        r["notice_key"]
        for r in conn.execute(
            "SELECT notice_key FROM plan WHERE student_id = ?", (student["id"],)
        )
    }
    items = []
    for row in rows:
        card = {"conditions": json.loads(row["conditions"])}
        verdict = judge.judge_notice(card, student["profile"])
        items.append({
            "key": row["notice_key"],
            "title": row["title"],
            "sub": row["sub"],
            "dept": row["dept"],
            "category": row["category"],
            "apply_start": row["apply_start"],
            "apply_end": row["apply_end"],
            "is_new": bool(row["demo_new"]),
            "planned": row["notice_key"] in planned,
            "eligible": verdict["eligible"],
            "gap": verdict["gap"],
            "rows": verdict["rows"],
        })
    return items


def tasks_of(conn, student_id, key):
    """The card's tasks, `done` by this student's task_done (SPEC 7 상세)."""
    done = {
        r["task_id"]
        for r in conn.execute("SELECT task_id FROM task_done WHERE student_id = ?", (student_id,))
    }
    rows = conn.execute(
        "SELECT id, title, due FROM task_template WHERE notice_key = ? ORDER BY ord", (key,)
    )
    return [
        {"id": r["id"], "title": r["title"], "due": r["due"], "done": r["id"] in done}
        for r in rows
    ]


def pick_alt(items, item):
    """SPEC 8.2 "상세의 alt": the card to suggest instead, or None."""
    if not any(row["status"] == "fail" for row in item["rows"]):
        return None
    others = sorted(
        (i for i in items if i["key"] != item["key"] and i["eligible"]),
        key=lambda i: (i["apply_end"], i["key"]),
    )
    same_category = [i for i in others if i["category"] == item["category"]]
    if same_category:
        return same_category[0]
    # Nothing in the same category: a card with no condition, or only `none` ones.
    plain = [i for i in others if all(row["type"] == "none" for row in i["rows"])]
    return plain[0] if plain else None


def detail_body(conn, student, row, item, alt):
    """SPEC 7 상세 = a list item plus url, posted_date, fields, tasks, alt."""
    detail = dict(item)
    detail.update({
        "url": row["notice_url"],
        "posted_date": row["posted_date"],
        "fields": json.loads(row["fields"]),
        "tasks": tasks_of(conn, student["id"], item["key"]),
        "alt": alt,
    })
    return detail


def detail_of(conn, student, key):
    """The detail of one card. A card outside the list is a 404 (SPEC 7)."""
    rows = visible_rows(conn, student)
    row = next((r for r in rows if r["notice_key"] == key), None)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown notice")
    items = notice_items(conn, student, rows)
    item = next(i for i in items if i["key"] == key)
    return detail_body(conn, student, row, item, pick_alt(items, item))


def highlights_of(text, source_id, conditions):
    """SPEC 7 원문 시트: [start, end) of every quote that was read in this section."""
    spans = []
    for cond in conditions:
        quote = cond.get("quote") or ""  # an `unresolved` condition quotes nothing
        if not quote or cond.get("source_id") != source_id:
            continue
        start = text.find(quote)  # the first place only
        if start < 0:
            # ponytail: a quote that drifted from its raw_source is dropped instead of
            # raising. tests/test_data.py is what guards the quotes of the prepared DB.
            continue
        span = [start, start + len(quote)]
        if span not in spans:
            spans.append(span)
    return sorted(spans)


def raw_sheet(conn, student, key):
    """SPEC 7 원문 시트: the sources in `ord` order, with this card's quotes marked."""
    row = next((r for r in visible_rows(conn, student) if r["notice_key"] == key), None)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown notice")
    conditions = json.loads(row["conditions"])
    sections = []
    for source in conn.execute(
        "SELECT id, kind, label, url, text FROM raw_source WHERE notice_key = ? ORDER BY ord",
        (key,),
    ):
        sections.append({
            "kind": source["kind"],
            "label": source["label"],
            "url": source["url"],
            "text": source["text"],
            "highlights": highlights_of(source["text"], source["id"], conditions),
        })
    return {"path": " → ".join(s["label"] for s in sections), "sections": sections}


def me_body(student):
    """SPEC 7: {"profile", "eligible_count"}. eligible_count counts the visible list."""
    conn = db.connect()
    try:
        items = notice_items(conn, student)
    finally:
        conn.close()
    return {
        "profile": student["profile"],
        "eligible_count": sum(1 for item in items if item["eligible"]),
    }


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/api/config")
def config():
    conn = db.connect()
    try:
        sources = conn.execute("SELECT COUNT(DISTINCT source_id) FROM notice").fetchone()[0]
        row = conn.execute("SELECT value FROM meta WHERE key = 'suggested_questions'").fetchone()
    finally:
        conn.close()
    questions = []
    if row:
        try:
            questions = json.loads(row["value"])
        except ValueError:
            questions = []
    return {"today": today(), "sources": sources, "suggested_questions": questions}


@app.post("/api/students")
def create_student():
    """An anonymous student. No name and no student number are taken (SPEC 6.4)."""
    student_id = secrets.token_urlsafe(16)
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO student (id, profile, created_at) VALUES (?, '{}', ?)",
            (student_id, datetime.now().isoformat(timespec="seconds")),
        )
    conn.close()
    return {"id": student_id}


@app.get("/api/me")
def get_me(student=Depends(current_student)):
    return me_body(student)


@app.put("/api/me")
def put_me(profile: dict = Body(...), student=Depends(current_student)):
    """The whole profile at once: a key left out is gone (SPEC 10.1 A3)."""
    check_profile(profile)
    store_profile(student, profile)
    return me_body(student)


@app.patch("/api/me")
def patch_me(patch: dict = Body(...), student=Depends(current_student)):
    check_profile(patch)
    profile = dict(student["profile"])
    for key, value in patch.items():
        if key == "history":
            # history merges flag by flag; langs is replaced whole (SPEC 7, 10.1 A12).
            merged = dict(profile.get("history") or {})
            merged.update(value)
            if len(merged) > HISTORY_MAX:
                bad(f"history keeps at most {HISTORY_MAX} flags")
            profile["history"] = merged
        else:
            profile[key] = value
    store_profile(student, profile)
    return me_body(student)


@app.get("/api/notices")
def notices(student=Depends(current_student)):
    conn = db.connect()
    try:
        return {"items": notice_items(conn, student)}
    finally:
        conn.close()


@app.get("/api/notices/{key}")
def notice(key: str, student=Depends(current_student)):
    conn = db.connect()
    try:
        return detail_of(conn, student, key)
    finally:
        conn.close()


@app.get("/api/notices/{key}/raw")
def notice_raw(key: str, student=Depends(current_student)):
    conn = db.connect()
    try:
        return raw_sheet(conn, student, key)
    finally:
        conn.close()


@app.post("/api/judge")
def judge_with_overrides(body: dict = Body(...), student=Depends(current_student)):
    """SPEC 7 가정 판정: judge these cards with assumed values, and store nothing."""
    keys = body.get("notice_keys")
    if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
        bad("notice_keys takes a list of notice keys")
    overrides = body.get("overrides") or {}
    check_profile(overrides)  # the same validation as PATCH (SPEC 7)
    conn = db.connect()
    try:
        rows = {r["notice_key"]: r for r in visible_rows(conn, student)}
    finally:
        conn.close()
    unknown = [key for key in keys if key not in rows]
    if unknown:
        raise HTTPException(status_code=404, detail="unknown notice: " + ", ".join(unknown))
    profile = judge.with_overrides(student["profile"], overrides)
    return [
        judge.judge_notice({"conditions": json.loads(rows[key]["conditions"])}, profile)
        for key in keys
    ]


@app.get("/api/ask")
def ask(field: str | None = None, student=Depends(current_student)):
    """SPEC 7 되묻기 카드: the question that unlocks the most held notices, or null."""
    conn = db.connect()
    try:
        cards = [{"conditions": json.loads(r["conditions"])} for r in visible_rows(conn, student)]
    finally:
        conn.close()
    try:
        return judge.ask_back(cards, student["profile"], field)
    except ValueError as error:
        bad(str(error))


@app.get("/api/plan")
def get_plan(student=Depends(current_student)):
    """SPEC 7: the planned cards that are still in the list, by deadline. `alt` is null."""
    conn = db.connect()
    try:
        rows = {r["notice_key"]: r for r in visible_rows(conn, student)}
        items = notice_items(conn, student, list(rows.values()))
        planned = sorted(
            (i for i in items if i["planned"]), key=lambda i: (i["apply_end"], i["key"])
        )
        return {
            "items": [
                detail_body(conn, student, rows[item["key"]], item, None) for item in planned
            ]
        }
    finally:
        conn.close()


@app.post("/api/plan/{key}", status_code=204)
def add_to_plan(key: str, student=Depends(current_student)):
    """SPEC 8.2: the server judges the card again, and 409s when it is not eligible."""
    conn = db.connect()
    try:
        row = next((r for r in visible_rows(conn, student) if r["notice_key"] == key), None)
        if row is None:
            raise HTTPException(status_code=404, detail="unknown notice")
        card = {"conditions": json.loads(row["conditions"])}
        if not judge.judge_notice(card, student["profile"])["eligible"]:
            raise HTTPException(status_code=409, detail="not eligible for this notice")
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO plan (student_id, notice_key, added_at) VALUES (?, ?, ?)",
                (student["id"], key, today()),
            )
    finally:
        conn.close()


@app.delete("/api/plan/{key}", status_code=204)
def remove_from_plan(key: str, student=Depends(current_student)):
    """204 even when the card was never in the plan (SPEC 7)."""
    conn = db.connect()
    with conn:
        conn.execute(
            "DELETE FROM plan WHERE student_id = ? AND notice_key = ?", (student["id"], key)
        )
    conn.close()


@app.put("/api/tasks/{task_id}", status_code=204)
def set_task(task_id: int, body: dict = Body(...), student=Depends(current_student)):
    """SPEC 7: a task of any card can be checked, planned or not. An unknown id is a 404."""
    done = body.get("done")
    if not isinstance(done, bool):
        bad("done takes true or false")
    conn = db.connect()
    try:
        if conn.execute("SELECT id FROM task_template WHERE id = ?", (task_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="unknown task")
        with conn:
            if done:
                conn.execute(
                    "INSERT OR IGNORE INTO task_done (student_id, task_id) VALUES (?, ?)",
                    (student["id"], task_id),
                )
            else:
                conn.execute(
                    "DELETE FROM task_done WHERE student_id = ? AND task_id = ?",
                    (student["id"], task_id),
                )
    finally:
        conn.close()


@app.get("/api/alerts")
def get_alerts(student=Depends(current_student)):
    """SPEC 7, 8.1: the three alert kinds, in `new`, `deadline`, `today` order."""
    conn = db.connect()
    try:
        rows = {r["notice_key"]: r for r in visible_rows(conn, student)}
        feed = [
            dict(
                item,
                conditions=json.loads(rows[item["key"]]["conditions"]),
                tasks=tasks_of(conn, student["id"], item["key"]) if item["planned"] else [],
            )
            for item in notice_items(conn, student, list(rows.values()))
        ]
    finally:
        conn.close()
    return judge.alerts(feed, student["profile"], today())


@app.post("/api/reveal-new")
def reveal_new(student=Depends(current_student)):
    """SPEC 7: show this student the demo_new cards. The second call gives nothing."""
    if student["revealed_new"]:
        return {"items": []}
    conn = db.connect()
    try:
        with conn:
            conn.execute("UPDATE student SET revealed_new = 1 WHERE id = ?", (student["id"],))
        student["revealed_new"] = 1
        return {"items": [item for item in notice_items(conn, student) if item["is_new"]]}
    finally:
        conn.close()
