"""The ask agent loop (SPEC 8.4).

The model only picks tools and writes the answer; this module runs the tools over
the cards and `app.judge`, and rules -- not the model -- decide which keys may be
cited. The gateway has no tool calling, so one JSON object per reply is the whole
protocol. The loop is served as the /api/chat NDJSON stream at the bottom.
"""

import asyncio
import json
import logging
import math
import time
from collections import Counter
from datetime import date, datetime

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import StreamingResponse

from app import db, judge, llm

# app.main imports this router on its last line, so this module imports main on its
# own last line in turn. Whichever of the two is imported first, the router is
# complete before include_router copies it. Every use of `main` is inside a
# function, so the late import is enough.
router = APIRouter()

BUDGET = 5  # LLM calls per question (SPEC 8.4)
QUESTION_MAX = 300  # characters; the screen sets maxlength=300 as well
PER_MINUTE = 5  # questions per student
WINDOW_SECONDS = 60.0
QUESTION_SECONDS = 60  # the whole question, steps included
CONCURRENCY = 3  # gateway calls in flight across the server
ERROR_TEXT = "잠시 후 다시 물어봐 주세요"
MISS_TEXT = "공지에서 찾을 수 없어요"
SEARCH_MAX = 10  # cards a search returns (SPEC 8.4)
# A tool result is cut before it goes into the system message. check_eligibility without
# keys carries up to 20 cards at ~130 chars each; 1200 cut it after 9 and the model then
# listed 9 of 12 "eligible" cards (checked on the EC2 on 9/20).
RESULT_MAX = 3000
BODY_MAX = 2000  # ponytail: only the head of a notice body is searched and nothing is
# indexed, so every question rescores every card; build an FTS5 index if it drags.
K1, B = 1.2, 0.75

TOOLS = {
    "search_notices": "공지 검색",
    "get_profile": "내 정보 불러오기",
    "check_eligibility": "조건 대조",
    "get_plan": "내 계획 불러오기",
}

# The examples carry placeholders on purpose: with real values the model answered
# with the example itself (SPEC 8.4, checked against the real key on 9/20).
INSTRUCTIONS = """너는 국민대 학생의 공지 질문에 답하는 에이전트다. 학생 정보와 공지는 도구로만 볼 수 있다.

출력은 JSON 객체 하나뿐이다. 설명, 코드 펜스, 다른 문장을 붙이지 말라.
- 도구를 부를 때: {"tool": "<도구 이름>", "args": {"<인자>": "<값>"}}
- 답할 때: {"answer": "<학생에게 보일 한국어 답>", "refs": ["<도구 결과에 나온 공지 key>"], "found": true}
- 학생 정보를 고치자고 제안할 때: {"answer": "<제안>", "confirm_update": {"<정보 키>": "<값>"}, "refs": [], "found": true}

도구는 넷이다.
- search_notices(query, category): 공지를 검색한다. query가 비면 모집 중인 공지를 마감순으로 준다. 결과의 items는 상위 일부이고, 맞는 공지 전체 수는 total이다.
- get_profile(): 학생 정보를 본다.
- check_eligibility(notice_keys, overrides, category): 조건을 대조한다. notice_keys는 도구 결과에 나온 key 1~10개다. notice_keys를 빼면 모집 중인 공지 전체에서 지원 가능한 것을 준다. "학점이 더 높으면"처럼 가정하는 질문은 overrides에 넣는다.
- get_plan(): 학생이 계획에 넣은 공지와 남은 할 일을 본다.

규칙
- 먼저 도구를 부르고, 도구 결과에 있는 사실로만 답한다. 지원 가능한지 아닌지는 check_eligibility 결과로만 말한다.
- refs에는 이번 질문의 도구 결과에 나온 key만 넣는다.
- 마감은 결과의 days_left와 open으로 판단한다. 날짜를 직접 계산하지 말라.
- 지원 가능한 공지가 하나도 없으면 없다고 답한다. 이것도 found: true다.
- 도구 결과로도 답을 찾을 수 없을 때만 found: false를 낸다.
- search_notices로 공지를 찾았으면 답하기 전에 그 key들로 check_eligibility를 부른다. 대조하지 않은 공지는 지원할 수 있다고 말하지 말라.
- 공지 수를 말할 때는 total을 쓴다. items의 개수를 전체 개수처럼 말하지 말라.
- "전부", "전체", "다", "목록"처럼 지원할 수 있는 공지를 모두 달라는 질문에 검색어가 없으면 notice_keys 없이 check_eligibility를 부른다.
- 직전 질문과 답이 주어지면 "나머지", "그건", "그중"처럼 이어지는 질문은 그 문맥으로 해석한다. 그래도 지원 가능 여부와 refs는 이번 질문의 도구 결과로만 정한다.
- 답은 한국어로만 쓴다. 한자, 가나 같은 다른 문자를 섞지 말라.
- 답은 한국어 두세 문장이다. 위 예시의 값은 보기일 뿐이니 그대로 옮기지 말라."""

FIRST_TOOL_NOTE = "아직 도구를 부르지 않았다. 먼저 도구를 불러라."
BROKEN_NOTE = "방금 답은 JSON으로 읽을 수 없었다. 다른 말 없이 JSON 객체 하나만 내라."
LAST_CALL_NOTE = "이번이 마지막 답이다. 도구를 부르지 말고 지금까지의 결과로 답하라."


class ToolError(Exception):
    """Bad arguments: the message goes back to the model instead of a step event."""


# ---------------------------------------------------------------- tool scope


def scope_rows(conn, student):
    """Every card the chat may look at (SPEC 8.4 "조회 범위").

    Wider than the list: a closed notice is still answerable, it just comes back
    with open = false.
    """
    return conn.execute(
        "SELECT c.*, n.posted_date AS posted_date, n.body_text AS body_text"
        " FROM card c JOIN notice n ON n.key = c.notice_key"
        " WHERE c.check_ok = 1 AND c.hidden = 0 AND c.linked_to IS NULL"
        "   AND n.posted_date <= ? AND (c.demo_new = 0 OR ? = 1)"
        " ORDER BY c.notice_key",
        (main.today(), student["revealed_new"]),
    ).fetchall()


def is_open(row, today):
    """The list's apply-period condition (SPEC 7 "목록에 보이는 카드")."""
    end, start = row["apply_end"], row["apply_start"]
    return bool(end and end >= today and (start is None or start <= today))


def days_left(apply_end, today):
    """The model never compares dates itself (SPEC 8.4)."""
    if not apply_end:
        return None
    return (date.fromisoformat(apply_end) - date.fromisoformat(today)).days


def brief(row, today):
    return {
        "key": row["notice_key"],
        "title": row["title"],
        "category": row["category"],
        "apply_end": row["apply_end"],
        "days_left": days_left(row["apply_end"], today),
        "open": is_open(row, today),
    }


# ---------------------------------------------------------------- search (BM25)


def bigrams(text):
    plain = "".join(ch for ch in (text or "").lower() if not ch.isspace())
    return [plain[i:i + 2] for i in range(len(plain) - 1)]


def summary_text(row):
    """The card's own summary of what it asks for: condition labels, needs, fields."""
    parts = []
    for cond in json.loads(row["conditions"] or "[]"):
        parts.append(str(cond.get("label") or ""))
        parts.append(str(cond.get("need") or ""))
    for pair in json.loads(row["fields"] or "[]"):
        parts.extend(str(p) for p in pair)
    return " ".join(parts)


def doc_terms(row):
    """Character bigrams of one card, title counted three times (SPEC 8.4)."""
    terms = bigrams(row["title"]) * 3
    terms += bigrams(row["sub"])
    terms += bigrams(summary_text(row))
    terms += bigrams((row["body_text"] or "")[:BODY_MAX])
    return Counter(terms), len(terms)


def bm25(rows, query):
    """[(key, score)] over the given cards, best first."""
    terms = set(bigrams(query))
    if not terms or not rows:
        return []
    docs = [(row["notice_key"],) + doc_terms(row) for row in rows]
    total = len(docs)
    avg = sum(length for _, _, length in docs) / total or 1
    df = {t: sum(1 for _, counts, _ in docs if t in counts) for t in terms}
    scored = []
    for key, counts, length in docs:
        score = 0.0
        for term in terms:
            freq = counts.get(term, 0)
            if not freq:
                continue
            idf = math.log(1 + (total - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * freq * (K1 + 1) / (freq + K1 * (1 - B + B * length / avg))
        if score > 0:
            scored.append((key, score))
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored


# ---------------------------------------------------------------- the four tools


def normalize_args(name, args):
    """Check the model's arguments and drop what the tool does not take."""
    if not isinstance(args, dict):
        raise ToolError("args는 객체다")
    if name == "search_notices":
        query = args.get("query") or ""
        if not isinstance(query, str):
            raise ToolError("query는 문자열이다")
        return {"query": query.strip(), "category": clean_category(args.get("category"))}
    if name == "check_eligibility":
        keys = args.get("notice_keys")
        if keys is not None:
            if (not isinstance(keys, list) or not 1 <= len(keys) <= 10
                    or any(not isinstance(k, str) for k in keys)):
                raise ToolError("notice_keys는 공지 key 1~10개이거나 null이다")
            keys = list(dict.fromkeys(keys))
        overrides = args.get("overrides") or None
        if overrides is not None:
            if not isinstance(overrides, dict):
                raise ToolError("overrides는 객체다")
            try:
                main.check_profile(overrides)  # the PATCH /api/me rules (SPEC 8.4)
            except HTTPException as exc:
                raise ToolError(f"overrides가 잘못됐다: {exc.detail}")
        return {
            "notice_keys": keys,
            "overrides": overrides,
            "category": clean_category(args.get("category")),
        }
    return {}


def clean_category(value):
    """An unknown category is ignored, not an error (SPEC 8.4 "조회 범위")."""
    if value is not None and not isinstance(value, str):
        raise ToolError("category는 문자열이거나 null이다")
    return value if value in main.CATEGORIES else None


def tool_search(conn, student, args):
    today = main.today()
    rows = scope_rows(conn, student)
    if args["category"]:
        rows = [r for r in rows if r["category"] == args["category"]]
    if args["query"]:
        ranked = bm25(rows, args["query"])
        by_key = {r["notice_key"]: r for r in rows}
        matched = [by_key[key] for key, _ in ranked]
    else:
        # SPEC 10.1 C1: an empty query gives the open cards by deadline, the card
        # closing today included, and never a closed one.
        matched = sorted(
            (r for r in rows if is_open(r, today)),
            key=lambda r: (r["apply_end"], r["notice_key"]),
        )
    items = [brief(row, today) for row in matched[:SEARCH_MAX]]
    # total says how many cards matched, so the model never reads the page size as
    # the whole: on 9/20 it answered "모집 중인 공지는 총 10건" from a 10-card page.
    result = {"items": items, "total": len(matched), "shown": len(items)}
    detail = f"카드 {len(items)}건" if len(matched) == len(items) else f"{len(matched)}건 중 {len(items)}건"
    return result, detail


def tool_profile(conn, student, args):
    profile = student["profile"]
    parts = []
    if isinstance(profile.get("semesters"), int):
        parts.append(f"{profile['semesters']}학기 이수")
    if profile.get("gpa") is not None and not isinstance(profile["gpa"], dict):
        parts.append("평균 " + judge.gpa_text(profile["gpa"]))
    return {"profile": profile}, " · ".join(parts) or "입력한 정보 없음"


def tool_check(conn, student, args):
    today = main.today()
    profile = judge.with_overrides(student["profile"], args["overrides"])
    viewer = dict(student, profile=profile)
    if args["notice_keys"] is None:
        items = main.notice_items(conn, viewer)
        if args["category"]:
            items = [i for i in items if i["category"] == args["category"]]
        good = sorted((i for i in items if i["eligible"]), key=lambda i: (i["apply_end"], i["key"]))
        summary = f"모집 중인 공지 {len(items)}건 중 {len(good)}건에 지금 지원할 수 있다"
        result = {
            "summary": summary,
            "checked": len(items),
            "eligible": len(good),
            "results": [
                {"key": i["key"], "title": i["title"], "apply_end": i["apply_end"],
                 "days_left": days_left(i["apply_end"], today), "category": i["category"]}
                for i in good[:20]
            ],
        }
        return result, f"{len(items)}건 중 {len(good)}건 지원 가능"

    rows = {r["notice_key"]: r for r in scope_rows(conn, student)}
    found = [k for k in args["notice_keys"] if k in rows]
    not_found = [k for k in args["notice_keys"] if k not in rows]
    if not found:
        raise ToolError("notice_keys가 모두 조회 범위 밖이다. search_notices로 key를 먼저 찾아라")
    results = []
    for key in found:
        row = rows[key]
        verdict = judge.judge_notice({"conditions": json.loads(row["conditions"])}, profile)
        item = brief(row, today)
        item.update({
            "eligible": verdict["eligible"],
            "gap": verdict["gap"],
            "conditions": [
                {"label": r["label"], "need": r["need"], "status": r["status"], "have": r["have"]}
                for r in verdict["rows"]
            ],
        })
        results.append(item)
    good = sum(1 for r in results if r["eligible"])
    if len(results) == 1:
        detail = "지원 가능" if results[0]["eligible"] else (results[0]["gap"] or "지원 불가")
    else:
        detail = f"{len(results)}건 중 {good}건 지원 가능"
    result = {"summary": detail, "checked": len(results), "eligible": good,
              "results": results, "not_found": not_found}
    return result, detail


def tool_plan(conn, student, args):
    today = main.today()
    rows = {r["notice_key"]: r for r in scope_rows(conn, student)}
    planned = [
        r["notice_key"]
        for r in conn.execute(
            "SELECT notice_key FROM plan WHERE student_id = ?", (student["id"],))
    ]
    # A card hidden or linked after it was planned drops out, tasks and all (SPEC 8.4).
    keys = sorted((k for k in planned if k in rows),
                  key=lambda k: (rows[k]["apply_end"] or "9999-12-31", k))
    items, remaining = [], 0
    for key in keys:
        tasks = main.tasks_of(conn, student["id"], key)
        remaining += sum(1 for t in tasks if not t["done"])
        item = brief(rows[key], today)
        item["tasks"] = [{"title": t["title"], "due": t["due"], "done": t["done"]} for t in tasks]
        items.append(item)
    return ({"items": items, "remaining_tasks": remaining},
            f"계획 {len(items)}개 · 남은 할 일 {remaining}개")


RUNNERS = {
    "search_notices": tool_search,
    "get_profile": tool_profile,
    "check_eligibility": tool_check,
    "get_plan": tool_plan,
}


# ---------------------------------------------------------------- the loop


def extract_json(text):
    """The first {...} that reads as a JSON object with one of the three keys.

    Leading prose and code fences are ignored; a `{` that does not parse is skipped
    (SPEC 8.4). None means broken JSON.
    """
    decoder = json.JSONDecoder()
    for index, char in enumerate(text or ""):
        if char != "{":
            continue
        try:
            found, _ = decoder.raw_decode(text, index)
        except ValueError:
            continue
        if isinstance(found, dict) and any(k in found for k in ("tool", "answer", "found")):
            return found
    return None


def arg_text(args):
    """SPEC 8.4 `step.arg`: the arguments that are not null, as name=JSON값."""
    return ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}"
                     for k, v in args.items() if v is not None)


def short(result):
    text = json.dumps(result, ensure_ascii=False)
    return text if len(text) <= RESULT_MAX else text[:RESULT_MAX] + " …(줄임)"


def context_message(today, calls, notes, last_call, previous=None):
    """The third message: today, the previous turn, this question's tool results, then what to do next."""
    parts = [f"오늘은 {today}이다."]
    if previous:
        lines = ["직전 질문: " + previous["question"], "직전 답: " + previous["answer"]]
        if previous["keys"]:
            lines.append("직전 답의 공지 key: " + ", ".join(previous["keys"]))
        parts.append(chr(10).join(lines))
    if calls:
        parts.append("이번 질문에서 부른 도구와 결과다.")
        for index, call in enumerate(calls, 1):
            parts.append(f"{index}) {call['tool']}({call['arg']}) →\n{call['result']}")
    else:
        parts.append(FIRST_TOOL_NOTE)
    parts.extend(notes)
    if last_call:
        parts.append(LAST_CALL_NOTE)
    parts.append("다음 JSON을 내라.")
    return "\n\n".join(parts) + "\n/no_think"


def repeat_note(calls):
    """SPEC 8.4 "같은 호출 반복"."""
    if any(call["tool"] == "search_notices" for call in calls):
        nudge = "방금 검색한 key로 check_eligibility를 부르거나 답하라."
    else:
        nudge = 'search_notices를 query ""로 부르거나 답하라.'
    return "이미 결과가 있다. 같은 도구를 같은 인자로 다시 부르지 말라. 다음은 " + nudge


def result_keys(result):
    """The notice keys a tool result showed: the only keys refs may keep."""
    keys = []
    for item in (result.get("items") or []) + (result.get("results") or []):
        if isinstance(item, dict) and isinstance(item.get("key"), str):
            keys.append(item["key"])
    return keys


def source_line(conn, refs):
    """SPEC 8.4 `answer.src`."""
    if len(refs) != 1:
        return "공지 통합 검색"
    row = conn.execute(
        "SELECT posted_date FROM notice WHERE key = ?", (refs[0]["key"],)).fetchone()
    if row is None:
        return "공지 통합 검색"
    posted = date.fromisoformat(row["posted_date"])
    return f"{refs[0]['dept']} 공지 · {posted.month}월 {posted.day}일"


def answer_event(conn, student, reply, seen_keys):
    """Rules, not the model, decide the refs (SPEC 8.4 "근거 검증")."""
    allowed = set(seen_keys)
    wanted = [k for k in (reply.get("refs") or [])
              if isinstance(k, str) and k in allowed]
    items = {item["key"]: item for item in main.notice_items(conn, student)}
    # A past notice has no detail page (404), so it never becomes a ref row.
    refs = [items[k] for k in dict.fromkeys(wanted) if k in items]
    update = reply.get("confirm_update")
    return {
        "type": "answer",
        "text": reply["answer"].strip(),
        "refs": refs,
        "src": source_line(conn, refs),
        # Passed through as it came: the screen asks, PATCH /api/me stores (SPEC 8.4).
        "confirm_update": update if isinstance(update, dict) and update else None,
    }


def miss_event(conn, student, question):
    with conn:
        conn.execute(
            "INSERT INTO chat_miss (student_id, question, created_at) VALUES (?, ?, ?)",
            (student["id"], question, datetime.now().isoformat(timespec="seconds")),
        )
    return {"type": "answer", "text": MISS_TEXT, "refs": [], "src": "공지 통합 검색",
            "confirm_update": None}


async def run_question(student, question, chat_fn=None):
    """One question: yields a `step` event per tool call, then one `answer` event.

    `chat_fn` is `llm.chat`; T14 passes a wrapper that holds the concurrency
    semaphore. A gateway failure propagates and the route turns it into an `error`.
    """
    chat_fn = chat_fn or llm.chat
    conn = db.connect()
    try:
        today = main.today()
        calls, notes, seen_keys = [], [], []
        broken, nudged, reply = 0, False, None
        previous = LAST.get(student["id"])  # SPEC 8.4: one turn of memory, this process only
        for turn in range(1, BUDGET + 1):
            last_call = turn == BUDGET
            messages = [
                {"role": "system", "content": INSTRUCTIONS},
                {"role": "user", "content": question},
                {"role": "system", "content": context_message(today, calls, notes, last_call, previous)},
            ]
            notes = []
            started = time.monotonic()
            found = extract_json((await chat_fn(messages)).get("text") or "")
            if found is not None and "tool" not in found and not isinstance(
                    found.get("answer"), str):
                found = None  # an answer without text is as broken as no JSON at all
            if found is None:
                broken += 1
                if broken >= 2:  # two in a row: no answer (SPEC 8.4)
                    break
                notes.append(BROKEN_NOTE)
                continue
            broken = 0

            if "tool" in found:
                if last_call:  # a tool on the last call is not run and ends the loop
                    break
                name = found.get("tool")
                if not isinstance(name, str) or name not in TOOLS:
                    notes.append("그런 도구는 없다. 도구는 " + ", ".join(TOOLS) + "다.")
                    continue
                try:
                    args = normalize_args(name, found.get("args") or {})
                    signature = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
                    if any(call["signature"] == signature for call in calls):
                        notes.append(repeat_note(calls))
                        continue
                    result, detail = RUNNERS[name](conn, student, args)
                except ToolError as exc:
                    notes.append(f"{name} 호출이 잘못됐다: {exc}")
                    continue
                seen_keys.extend(result_keys(result))
                calls.append({"tool": name, "arg": arg_text(args), "signature": signature,
                              "result": short(result)})
                yield {"type": "step", "title": TOOLS[name], "tool": name,
                       "arg": arg_text(args), "detail": detail,
                       "ms": int((time.monotonic() - started) * 1000)}
                continue

            if found.get("found") is False:
                # SPEC 8.4 "found: false 되돌리기": twice this is not an answer yet.
                if not calls:
                    notes.append(FIRST_TOOL_NOTE)
                    continue
                if seen_keys and not nudged:
                    nudged = True
                    notes.append(
                        f"도구 결과에 공지 {len(set(seen_keys))}건이 있다. 이 결과로 답하라.")
                    continue
                break
            reply = found
            break

        if reply is None:
            event = miss_event(conn, student, question)
        else:
            event = answer_event(conn, student, reply, seen_keys)
        LAST[student["id"]] = {"question": question, "answer": event["text"][:LAST_ANSWER_MAX],
                               "keys": [r["key"] for r in event.get("refs") or []]}
        yield event
    finally:
        conn.close()


# ---------------------------------------------------------------- the route

SEM = asyncio.Semaphore(CONCURRENCY)
# ponytail: the rate-limit window lives in this process's memory, so a restart
# forgets it and a second worker would not share it; move it to the DB if we scale.
ASKS = {}
# ponytail: the previous turn per student lives in this process's memory like ASKS,
# so a restart forgets it; keep it in the student row if that ever matters.
LAST = {}
LAST_ANSWER_MAX = 300  # characters of the previous answer carried into the next question


async def guarded_chat(messages):
    """One gateway call holding one of the three server-wide slots (SPEC 8.4)."""
    async with SEM:
        return await llm.chat(messages)


def take_slot(student_id, now=None):
    """Five questions a minute per student. A refused question is not counted."""
    now = time.monotonic() if now is None else now
    recent = [when for when in ASKS.get(student_id, []) if now - when < WINDOW_SECONDS]
    ASKS[student_id] = recent
    if len(recent) >= PER_MINUTE:
        return False
    recent.append(now)
    return True


def ndjson(event):
    return json.dumps(event, ensure_ascii=False) + "\n"


async def stream(student, question, chat_fn=None):
    """The NDJSON body: a `step` line per tool, then one `answer` or `error` line."""
    if not take_slot(student["id"]):
        yield ndjson({"type": "error", "text": ERROR_TEXT})
        return
    events = run_question(student, question, chat_fn or guarded_chat)
    deadline = time.monotonic() + QUESTION_SECONDS
    try:
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("the question ran past its limit")
            # The limit is awaited here and not around the yield, so a slow reader
            # never eats the budget and the steps already sent stay put.
            try:
                event = await asyncio.wait_for(events.__anext__(), left)
            except StopAsyncIteration:
                break
            yield ndjson(event)
    except Exception:
        # A gateway failure, a DB failure, the 60s limit, anything unexpected: log it
        # and close with one error line instead of cutting the stream (SPEC 8.4).
        logging.exception("chat failed for student %s", student["id"])
        try:
            await events.aclose()
        except Exception:
            logging.exception("closing the agent loop failed")
        yield ndjson({"type": "error", "text": ERROR_TEXT})


@router.post("/api/chat")
async def ask(body: dict = Body(...), x_student_id: str | None = Header(default=None)):
    """SPEC 7, 8.4. The only async route; everything else stays sync.

    The header is read here instead of with Depends(main.current_student) because
    the route is built before the main import at the bottom of this file.
    """
    student = main.current_student(x_student_id)
    question = body.get("message")
    if not isinstance(question, str) or not question.strip():
        main.bad("message는 질문 문자열이다")
    if len(question) > QUESTION_MAX:
        main.bad(f"message는 {QUESTION_MAX}자 이하다")
    return StreamingResponse(stream(student, question), media_type="application/x-ndjson")


from app import main  # noqa: E402  (see the router comment at the top of the file)
