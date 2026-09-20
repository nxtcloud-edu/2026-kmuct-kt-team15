"""Operator queue (SPEC 8.5, tier 2).

A person corrects a review, the card is rewritten, and every student who entered
anything is judged again. Never shown in the demo; the code lives in the repo.
"""

import json
import os
import re
import secrets
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app import db, judge

router = APIRouter(prefix="/admin")
basic = HTTPBasic(auto_error=False)

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BODY_KEYS = {"condition", "apply_end", "hidden"}


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# SPEC 6.2: the exact params keys of each type and the shape of their values. A
# corrected condition has to keep them, so the card stays judgeable by app/judge.py.
PARAM_RULES = {
    "semesters": ({"min"}, lambda p: _is_int(p["min"])),
    "grade": ({"min", "max"}, lambda p: _is_int(p["min"]) and _is_int(p["max"])),
    "status": ({"allowed"}, lambda p: isinstance(p["allowed"], list) and p["allowed"]
               and all(isinstance(x, str) for x in p["allowed"])),
    "gpa": ({"min", "scope"}, lambda p: _is_num(p["min"]) and p["scope"] in ("cumulative", "last")),
    "credits": ({"min", "scope"}, lambda p: _is_int(p["min"]) and p["scope"] in ("last", "total")),
    "lang": ({"any_of"}, lambda p: isinstance(p["any_of"], dict) and p["any_of"]
             and all(k in judge.LANG_TYPES for k in p["any_of"])
             and all(_is_num(v) or (k == "OPIc" and v in judge.OPIC_GRADES)
                     for k, v in p["any_of"].items())),
    "topik": ({"min"}, lambda p: _is_int(p["min"]) and 0 <= p["min"] <= 6),
    "major": ({"majors"}, lambda p: isinstance(p["majors"], list) and p["majors"]
              and all(isinstance(x, str) for x in p["majors"])),
    "income": ({"max"}, lambda p: _is_int(p["max"])),
    "admission_year": ({"min", "max"},
                       lambda p: all(v is None or _is_int(v) for v in (p["min"], p["max"]))),
    "history": ({"flag", "must"},
                lambda p: isinstance(p["flag"], str) and isinstance(p["must"], bool)),
    "none": (set(), lambda p: True),
}


def guard(credentials: HTTPBasicCredentials | None = Depends(basic)):
    """SPEC 8.5: /admin needs ADMIN_PASSWORD. Empty means nobody gets in, and the
    user name is never looked at."""
    password = os.environ.get("ADMIN_PASSWORD", "")
    given = credentials.password if credentials else ""
    if not password or not secrets.compare_digest(given, password):
        raise HTTPException(
            status_code=401,
            detail="admin password required",
            headers={"WWW-Authenticate": "Basic"},
        )


router.dependencies.append(Depends(guard))


def bad(message):
    raise HTTPException(status_code=422, detail=message)


def covered_unresolved(review, conditions):
    """The `unresolved` conditions this review stands for (SPEC 8.5)."""
    return [
        cond for cond in conditions
        if cond.get("type") == "unresolved"
        and (review["condition_id"] is None or cond.get("id") == review["condition_id"])
    ]


def check_condition(conn, key, raw, condition_id):
    """A corrected condition still has to keep SPEC 6.2 and quote the raw source."""
    if not isinstance(raw, dict):
        bad("condition은 6.2 조건 객체다")
    ctype = raw.get("type")
    if ctype not in PARAM_RULES:  # `unresolved` is not in the table either (SPEC 8.5)
        bad("고친 조건의 type은 6.2 표 안이고 unresolved일 수 없다")
    text = {}
    for field in ("label", "need", "quote"):
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            bad(f"{field}는 비울 수 없다")
        text[field] = value
    params = raw.get("params")
    keys, ok = PARAM_RULES[ctype]
    if not isinstance(params, dict) or set(params) != keys or not ok(params):
        bad(f"{ctype}의 params가 6.2 표와 다르다")
    source = conn.execute(
        "SELECT id FROM raw_source WHERE notice_key = ? AND id = ? AND instr(text, ?) > 0",
        (key, raw.get("source_id"), text["quote"]),
    ).fetchone()
    if source is None:
        bad("인용은 같은 공지의 원문 한 행에 글자 그대로 있어야 한다")
    # SPEC 8.5: the corrected condition inherits the id of the `unresolved` one it replaces.
    return {
        "id": condition_id,
        "type": ctype,
        "label": text["label"],
        "need": text["need"],
        "params": params,
        "source_id": source["id"],
        "quote": text["quote"],
    }


def check_apply_end(conn, key, value):
    """`apply_end` is YYYY-MM-DD or null, and never earlier than a task due (SPEC 8.5)."""
    last = conn.execute(
        "SELECT MAX(due) AS due FROM task_template WHERE notice_key = ?", (key,)
    ).fetchone()["due"]
    if value is None:
        if last is not None:
            bad("할 일이 있는 카드는 마감을 비울 수 없다")
        return None
    if not isinstance(value, str) or not DATE.match(value):
        bad("apply_end는 YYYY-MM-DD나 null이다")
    try:
        date.fromisoformat(value)
    except ValueError:
        bad("apply_end는 YYYY-MM-DD나 null이다")
    if last is not None and value < last:
        bad(f"마감은 할 일 기한({last})보다 이를 수 없다")
    return value


def entered_profiles(conn):
    """Every student who entered anything (SPEC 8.5: `profile`이 `{}`가 아닌 학생)."""
    out = []
    for row in conn.execute("SELECT profile FROM student"):
        try:
            profile = json.loads(row["profile"] or "{}")
        except ValueError:
            profile = {}
        if profile:
            out.append(profile)
    return out


@router.get("")
def admin_page():
    return FileResponse(os.path.join(main.STATIC, "admin.html"))


@router.get("/api/reviews")
def reviews():
    """SPEC 8.5: the unresolved queue in id order, with what the screen edits."""
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT r.id, r.notice_key, r.condition_id, r.reason, r.note, r.resolved,"
            " c.title, c.apply_end, c.hidden, c.conditions, n.url"
            " FROM review r JOIN card c ON c.notice_key = r.notice_key"
            " JOIN notice n ON n.key = r.notice_key"
            " WHERE r.resolved = 0 ORDER BY r.id"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": row["id"],
            "notice_key": row["notice_key"],
            "condition_id": row["condition_id"],
            "reason": row["reason"],
            "note": row["note"],
            "resolved": bool(row["resolved"]),
            "title": row["title"],
            "apply_end": row["apply_end"],
            "hidden": bool(row["hidden"]),
            "conditions": json.loads(row["conditions"]),
            "url": row["url"],
        }
        for row in rows
    ]


@router.get("/api/notices/{key}/raw")
def admin_raw(key: str):
    """The raw sources of any card, list or not (SPEC 8.5)."""
    conn = db.connect()
    try:
        card = conn.execute(
            "SELECT conditions FROM card WHERE notice_key = ?", (key,)
        ).fetchone()
        conditions = json.loads(card["conditions"]) if card else []
        sources = conn.execute(
            "SELECT id, kind, label, url, text FROM raw_source WHERE notice_key = ? ORDER BY ord",
            (key,),
        ).fetchall()
    finally:
        conn.close()
    if card is None and not sources:
        raise HTTPException(status_code=404, detail="unknown notice")
    return [
        {
            "id": source["id"],
            "kind": source["kind"],
            "label": source["label"],
            "url": source["url"],
            "text": source["text"],
            "highlights": main.highlights_of(source["text"], source["id"], conditions),
        }
        for source in sources
    ]


@router.put("/api/reviews/{review_id}")
def correct(review_id: int, body: dict = Body(...)):
    """One correction, then everyone is judged again (SPEC 8.5)."""
    if set(body) - BODY_KEYS:
        bad(f"보낼 수 있는 키는 {sorted(BODY_KEYS)}다")
    conn = db.connect()
    try:
        review = conn.execute(
            "SELECT * FROM review WHERE id = ? AND resolved = 0", (review_id,)
        ).fetchone()
        if review is None:
            raise HTTPException(status_code=404, detail="unknown or resolved review")
        card = conn.execute(
            "SELECT * FROM card WHERE notice_key = ?", (review["notice_key"],)
        ).fetchone()
        if card is None:
            raise HTTPException(status_code=404, detail="review without a card")

        before = json.loads(card["conditions"])
        after = list(before)
        apply_end, hidden = card["apply_end"], card["hidden"]

        if "condition" in body:
            covered = covered_unresolved(review, after)
            if not covered:
                bad("이 검토가 덮는 unresolved 조건이 남아 있지 않다")
            target = covered[0]
            fixed = check_condition(conn, review["notice_key"], body["condition"], target["id"])
            after = [fixed if cond is target else cond for cond in after]
        if "apply_end" in body:
            apply_end = check_apply_end(conn, review["notice_key"], body["apply_end"])
        if "hidden" in body:
            if not isinstance(body["hidden"], bool):
                bad("hidden은 true나 false다")
            hidden = 1 if body["hidden"] else 0

        profiles = entered_profiles(conn)
        newly = 0
        for profile in profiles:
            was = judge.judge_notice({"conditions": before}, profile)["eligible"]
            now = judge.judge_notice({"conditions": after}, profile)["eligible"]
            if now and not was:
                newly += 1
        # SPEC 8.5: hidden or apply_end alone leaves the review in the queue.
        resolved = not covered_unresolved(review, after)

        with conn:
            conn.execute(
                "UPDATE card SET conditions = ?, apply_end = ?, hidden = ? WHERE notice_key = ?",
                (json.dumps(after, ensure_ascii=False), apply_end, hidden, review["notice_key"]),
            )
            if resolved:
                conn.execute("UPDATE review SET resolved = 1 WHERE id = ?", (review_id,))
    finally:
        conn.close()
    return {"resolved": resolved, "rejudged": len(profiles), "newly_eligible": newly}


from app import main  # noqa: E402  (main imports this router at its very end)
