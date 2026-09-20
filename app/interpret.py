"""Notice interpretation agent (SPEC 8.6, tier 2).

Reads one notice the way the prep step did -- body, attachments, prepared image
transcripts, kookmin links -- and writes the same rows the demo DB already holds
(`card`, `raw_source`, `task_template`, `review`). It calls llm-x, so the demo
never runs it:

    python -m app.interpret <notice key> [--force]

Rules that keep a wrong card from looking like an offer: a quote must sit in the
raw text letter for letter, params must match the 6.2 table, and anything the
agent could not settle stays as an `unresolved` condition with a review row
instead of quietly disappearing.
"""

import asyncio
import io
import json
import os
import re
import sys
import zipfile
from datetime import date, timedelta
from html.parser import HTMLParser
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from pypdf import PdfReader

from app import db, llm

BUDGET = 8  # LLM calls per notice; broken JSON counts (SPEC 8.6)
SOURCE_MAX = 6000  # characters of one raw source in the system message
SOURCES_MAX = 18000  # characters of all of them together
ALLOWED_HOST = "kookmin.ac.kr"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_HTML = os.path.join(HERE, "static", "index.html")

# SPEC 6.3.
CATEGORIES = [
    "장학", "인턴·현장실습", "국제교류", "교내활동", "학사·전공",
    "한국어·문화", "창업", "공모전·경진대회", "자격증·어학",
]
STATUSES = ["재학", "휴학", "졸업예정"]
LANG_TYPES = ["TOEIC", "TOEFL iBT", "IELTS", "TOEIC Speaking", "OPIc"]
OPIC_GRADES = ["NL", "NM", "NH", "IL", "IM1", "IM2", "IM3", "IH", "AL"]

# ponytail: provisional prep days until the team writes its table (SPEC 14.4).
# The first of these words that shows up in the task name wins.
PREP_DAYS = {
    "신청": 0, "제출": 0, "접수": 0, "지원": 0, "등록": 0, "응시": 0,
    "성적": 2, "증명서": 2, "발급": 2, "서류": 1, "준비": 1, "확인": 1,
    "자기소개서": 3, "계획서": 3, "포트폴리오": 5, "추천서": 5, "상담": 3, "검사": 3,
}

BROKEN_NOTE = "방금 답은 JSON으로 읽을 수 없었다. 다른 말 없이 JSON 객체 하나만 내라."
LAST_CALL_NOTE = "이번이 마지막 호출이다. 도구를 더 부르지 말고 finish로 끝내라."


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# SPEC 6.2, the same table tests/test_data.py checks the prepared DB against.
PARAM_RULES = {
    "semesters": ({"min"}, lambda p: is_int(p["min"]) and 0 <= p["min"] <= 8),
    "grade": ({"min", "max"}, lambda p: is_int(p["min"]) and is_int(p["max"])
              and 1 <= p["min"] <= p["max"] <= 4),
    "status": ({"allowed"}, lambda p: isinstance(p["allowed"], list) and p["allowed"]
               and all(x in STATUSES for x in p["allowed"])),
    "gpa": ({"min", "scope"}, lambda p: is_num(p["min"]) and 0 <= p["min"] <= 4.5
            and p["scope"] in ("cumulative", "last")),
    "credits": ({"min", "scope"}, lambda p: is_int(p["min"]) and 0 <= p["min"] <= 250
                and p["scope"] in ("last", "total")),
    "lang": ({"any_of"}, lambda p: isinstance(p["any_of"], dict) and p["any_of"]
             and all(k in LANG_TYPES for k in p["any_of"])
             and all(v in OPIC_GRADES if k == "OPIc" else is_num(v)
                     for k, v in p["any_of"].items())),
    "topik": ({"min"}, lambda p: is_int(p["min"]) and 1 <= p["min"] <= 6),
    "major": ({"majors"}, lambda p: isinstance(p["majors"], list) and p["majors"]
              and all(x in dept_names() for x in p["majors"])),
    "income": ({"max"}, lambda p: is_int(p["max"]) and 0 <= p["max"] <= 10),
    "admission_year": ({"min", "max"}, lambda p: any(v is not None for v in p.values())
                       and all(v is None or (is_int(v) and 2000 <= v <= 2026)
                               for v in (p["min"], p["max"]))),
    "history": ({"flag", "must"}, lambda p: isinstance(p["flag"], str)
                and 1 <= len(p["flag"]) <= 50 and isinstance(p["must"], bool)),
    "none": (set(), lambda p: True),
}

_DEPTS = []


def dept_names():
    """The screen's department list (SPEC 6.2 "major 목록", `static/index.html`)."""
    if not _DEPTS:
        with open(INDEX_HTML, encoding="utf-8") as f:
            page = f.read()
        block = re.search(r"const DEPTS = \[(.*?)\n\];", page, re.S)
        if block is None:
            raise RuntimeError("DEPTS is not in " + INDEX_HTML)
        for _, names in re.findall(r'\[\s*"([^"]+)"\s*,\s*\[([^\]]*)\]', block.group(1)):
            _DEPTS.extend(re.findall(r'"([^"]+)"', names))
        if not _DEPTS:
            raise RuntimeError("DEPTS is empty in " + INDEX_HTML)
    return _DEPTS


# ---------------------------------------------------------------- checks


def check_quote(quote, text):
    """SPEC 6.2: letter for letter, a difference in spacing included."""
    return isinstance(quote, str) and bool(quote.strip()) and quote in (text or "")


def check_condition(cond, sources):
    """One model condition -> the reason it is thrown away, or None."""
    ctype = cond.get("type")
    if ctype not in PARAM_RULES:
        # `unresolved` is the code's own marker and never comes from the model.
        return f"모르는 type: {ctype}"
    for key in ("label", "need"):
        if not isinstance(cond.get(key), str) or not cond[key].strip():
            return f"{key}가 비었다"
    keys, ok = PARAM_RULES[ctype]
    params = cond.get("params")
    if not isinstance(params, dict) or set(params) != keys:
        return f"{ctype} params 키는 {sorted(keys) or '없음'}이다"
    try:
        if not ok(params):
            return f"{ctype} params 값이 표와 다르다"
    except (TypeError, ValueError):
        return f"{ctype} params 값이 표와 다르다"
    number = cond.get("source")
    if not is_int(number) or not 1 <= number <= len(sources):
        return f"source는 1~{len(sources)}번 원문이다"
    if not check_quote(cond.get("quote"), sources[number - 1]["text"]):
        return "quote가 그 원문에 글자 그대로 없다"
    return None


def check_card(card):
    """The card fields the agent fills -> the reason it is sent back, or None."""
    if card.get("category") not in CATEGORIES:
        return "category는 " + ", ".join(CATEGORIES) + " 중 하나다"
    if not isinstance(card.get("sub", ""), str):
        return "sub는 한 줄 문자열이다"
    dates = {}
    for key in ("apply_start", "apply_end"):
        value = card.get(key)
        if value is None:
            dates[key] = None
            continue
        try:
            dates[key] = date.fromisoformat(value)
        except (TypeError, ValueError):
            return f"{key}는 YYYY-MM-DD이거나 null이다"
    if dates["apply_start"] and dates["apply_end"] and dates["apply_start"] > dates["apply_end"]:
        return "apply_start가 apply_end보다 늦다"
    fields = card.get("fields") or []
    if not isinstance(fields, list) or any(
            not isinstance(pair, (list, tuple)) or len(pair) != 2
            or not all(isinstance(x, str) for x in pair) for pair in fields):
        return "fields는 [\"항목\", \"값\"] 쌍의 배열이다"
    return None


def sort_conditions(raw, sources):
    """Split the model's conditions into the ones we keep and the ones we drop."""
    good, dropped = [], []
    for index, cond in enumerate(raw or [], 1):
        if not isinstance(cond, dict):
            dropped.append({"label": f"{index}번 조건", "need": "확인 중",
                            "why": "조건이 객체가 아니다"})
            continue
        why = check_condition(cond, sources)
        if why:
            dropped.append({"label": (cond.get("label") or "지원 자격").strip() or "지원 자격",
                            "need": (cond.get("need") or "확인 중").strip() or "확인 중",
                            "why": why})
        else:
            good.append(cond)
    return good, dropped


# ---------------------------------------------------------------- readers


def attachment_kind(data):
    """PDF, DOCX or HWPX told by content, never by the file name (SPEC 8.6)."""
    if not data:
        return None
    if data[:4] == b"%PDF":
        return "pdf"
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as bundle:
            names = bundle.namelist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return None
    if "word/document.xml" in names:
        return "docx"
    if any(re.fullmatch(r"Contents/section\d+\.xml", name) for name in names):
        return "hwpx"
    return None  # HWP and everything else is unreadable


def pdf_text(data):
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def zip_text(data, kind):
    """DOCX and HWPX are zipped XML; stdlib zipfile and ElementTree only."""
    lines = []
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        if kind == "docx":
            names = ["word/document.xml"]
        else:
            names = sorted(n for n in bundle.namelist()
                           if re.fullmatch(r"Contents/section\d+\.xml", n))
        for name in names:
            root = ElementTree.fromstring(bundle.read(name))
            paragraphs = [el for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "p"]
            for para in paragraphs or [root]:
                line = "".join(para.itertext()).strip()
                if line:
                    lines.append(line)
    return "\n".join(lines).strip()


def attachment_text(data):
    kind = attachment_kind(data)
    if kind is None:
        return ""
    if kind == "pdf":
        return pdf_text(data)
    return zip_text(data, kind)


class TextGrab(HTMLParser):
    """Page text with script and style dropped (stdlib html.parser, SPEC 8.6)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.quiet = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.quiet += 1
        elif tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "table"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.quiet:
            self.quiet -= 1
        elif tag in ("p", "div", "tr", "li", "h1", "h2", "h3", "h4", "table"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.quiet and data.strip():
            self.parts.append(data.strip() + " ")


def html_text(markup):
    grab = TextGrab()
    grab.feed(markup or "")
    grab.close()
    text = re.sub(r"[ \t]+", " ", "".join(grab.parts))
    return "\n".join(line for line in (l.strip() for l in text.split("\n")) if line)


def allowed_host(url):
    """SPEC 8.6: only *.kookmin.ac.kr, checked again on the address after redirects."""
    try:
        host = (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return False
    return host == ALLOWED_HOST or host.endswith("." + ALLOWED_HOST)


def fetch(url):
    return httpx.get(url, timeout=20.0, follow_redirects=True)


def read_attachment(notice, name):
    """-> (source, None) or (None, why). A file we cannot convert is unreadable."""
    files = [f for f in json.loads(notice["attachments"] or "[]") if isinstance(f, dict)]
    found = next((f for f in files if f.get("name") == name), None)
    if found is None and isinstance(name, str) and name:
        found = next((f for f in files if name in (f.get("name") or "")), None)
    if found is None:
        have = ", ".join(f.get("name", "") for f in files) or "없음"
        return None, f"'{name}'이라는 붙임이 없다. 이 공지의 붙임: {have}", None
    label = found.get("name") or "붙임"
    try:
        res = fetch(found.get("url") or "")
        data = res.content if res.status_code < 400 else b""
    except httpx.HTTPError:
        data = b""
    text = attachment_text(data)
    if not text:
        return None, f"{label}은 열람 불가다(형식이나 내려받기 실패).", label
    return ({"kind": "attachment", "label": label, "url": found.get("url") or "",
             "text": text, "confidence": None}, None, None)


def read_image(conn, key, number):
    """Prepared image transcripts only (SPEC 8.6). Nothing prepared is unreadable."""
    rows = conn.execute(
        "SELECT * FROM raw_source WHERE notice_key = ? AND kind = 'image' ORDER BY ord",
        (key,),
    ).fetchall()
    if not is_int(number) or not 1 <= number <= len(rows):
        return None, f"이미지 {number}번 판독본이 없다(판독본 {len(rows)}장).", f"이미지 {number}"
    row = rows[number - 1]
    return ({"kind": "image", "label": row["label"], "url": row["url"], "text": row["text"],
             "confidence": row["confidence"], "row_id": row["id"]}, None, None)


def follow_link(url):
    """A link we cannot open is only told to the model, never an unreadable file."""
    if not allowed_host(url):
        return None, f"{url}은 kookmin.ac.kr 밖이라 열지 않는다.", None
    try:
        res = fetch(url)
    except httpx.HTTPError:
        return None, f"{url}을 열지 못했다.", None
    if res.status_code >= 400 or not allowed_host(str(res.url)):
        return None, f"{url}을 열지 못했다(주소가 밖으로 나갔거나 오류).", None
    text = html_text(res.text)
    if not text:
        return None, f"{url}에서 글자를 찾지 못했다.", None
    return {"kind": "link", "label": url, "url": url, "text": text, "confidence": None}, None, None


def run_tool(conn, notice, step, sources):
    """-> (source, why, unreadable label). Only one of the first two is set."""
    tool, arg = step.get("tool"), step.get("arg")
    if tool == "read_attachment":
        return read_attachment(notice, arg)
    if tool == "read_image":
        return read_image(conn, notice["key"], arg)
    if tool == "follow_link":
        return follow_link(arg if isinstance(arg, str) else "")
    return None, f"그런 도구는 없다: {tool}", None


# ---------------------------------------------------------------- the prompt

INSTRUCTIONS = """너는 국민대 공지 하나를 읽고 학생용 카드를 채우는 해석기다.

출력은 JSON 객체 하나뿐이다. 설명이나 코드 펜스를 붙이지 말라.
{"card": {"category": "<분야>", "sub": "<한 줄 요약>", "apply_start": "<YYYY-MM-DD 또는 null>",
 "apply_end": "<YYYY-MM-DD 또는 null>", "conditions": [<조건>], "fields": [["<항목>", "<값>"]],
 "tasks": ["<할 일 이름>"]},
 "next": {"tool": "<도구 이름>", "arg": <인자>}}
학생이 신청하거나 지원할 수 있는 기회 공지가 아니면 {"skip": "<이유>"}만 낸다.

조건 하나는 이렇게 쓴다.
{"type": "<아래 표의 type>", "label": "<화면에 보일 이름>", "need": "<기준 문구>",
 "params": {...}, "source": <원문 번호>, "quote": "<그 원문에 글자 그대로 있는 문장>"}
- quote는 원문에서 그대로 복사한다. 공백 하나만 달라도 그 조건은 버려진다.
- 원문에 근거가 없는 조건은 만들지 않는다. 조건이 하나도 없으면 conditions는 빈 배열이다.
- type과 params는 표대로만 쓴다.
  semesters {"min": <정수 0~8>} · grade {"min": <1~4>, "max": <1~4>} · status {"allowed": ["재학"]}
  gpa {"min": <0~4.5>, "scope": "cumulative"|"last"} · credits {"min": <정수>, "scope": "last"|"total"}
  lang {"any_of": {"TOEIC": <점수>, "OPIc": "<등급>"}} · topik {"min": <1~6>}
  major {"majors": ["<학과 이름>"]} · income {"max": <정수 0~10>}
  admission_year {"min": <연도 또는 null>, "max": <연도 또는 null>}
  history {"flag": "<예/아니오로 답할 사정>", "must": true|false} · none {}
- 국적 조건은 history flag "외국인 유학생"으로 쓴다(대한민국 국적자면 must false).
- "재학생 누구나"처럼 조건이 없다는 인용이 있으면 type "none"을 쓴다.
- major의 학과 이름은 다음 목록에 있는 것만 쓴다: {depts}
- category는 다음 중 하나다: {categories}

도구는 넷이다. 다 읽었으면 finish를 고른다.
- read_attachment("<붙임 이름>") · read_image(<번호>) · follow_link("<kookmin.ac.kr 주소>") · finish
매번 지금까지 읽은 원문 전부로 card를 다시 채우고, 다음 도구를 고른다."""


def source_block(sources):
    """The raw text in the system message: 6k characters each, 18k in total."""
    parts, total = [], 0
    for index, source in enumerate(sources, 1):
        text = (source["text"] or "")[:SOURCE_MAX]
        if total + len(text) > SOURCES_MAX:
            text = text[:max(0, SOURCES_MAX - total)]
        total += len(text)
        low = " (판독 저신뢰)" if source.get("confidence") == "low" else ""
        parts.append(f"원문 {index}: {source['label']}{low}\n{text}")
        if total >= SOURCES_MAX:
            break
    return "\n\n".join(parts) if parts else "아직 읽은 원문이 없다."


def build_messages(notice, sources, notes, unreadable, last_call):
    # .replace, not .format: the instructions are full of JSON braces.
    head = (INSTRUCTIONS.replace("{depts}", ", ".join(dept_names()))
            .replace("{categories}", ", ".join(CATEGORIES)))
    files = [f.get("name", "") for f in json.loads(notice["attachments"] or "[]")
             if isinstance(f, dict)]
    parts = [head, "붙임: " + (", ".join(files) or "없음"), source_block(sources)]
    if unreadable:
        parts.append("열람 불가로 표시한 것: " + ", ".join(unreadable))
    parts.extend(notes)
    if last_call:
        parts.append(LAST_CALL_NOTE)
    parts.append("다음 JSON을 내라.")
    return [
        {"role": "system", "content": "\n\n".join(parts) + "\n/no_think"},
        # Long text never goes in the user message (SPEC 8.4 "긴 텍스트는 system에").
        {"role": "user", "content": f"{notice['key']}\n{notice['title']}"},
    ]


def first_json(text):
    """The first {...} that reads as a JSON object with one of our keys.

    Same scanner as app.chat.extract_json; kept here so this CLI does not drag
    the web app in.
    """
    decoder = json.JSONDecoder()
    for index, char in enumerate(text or ""):
        if char != "{":
            continue
        try:
            found, _ = decoder.raw_decode(text, index)
        except ValueError:
            continue
        if isinstance(found, dict) and any(k in found for k in ("card", "skip", "next")):
            return found
    return None


# ---------------------------------------------------------------- the result


def prep_days(title):
    """The first table word that shows up in the task name (SPEC 8.6)."""
    days, first = 1, None
    for word, value in PREP_DAYS.items():
        where = title.find(word)
        if where < 0 or (first is not None and where >= first):
            continue
        days, first = value, where
    return days


def build_tasks(card, apply_end):
    """SPEC 6.5 rule 5: due = apply_end - prep days. No deadline, no tasks."""
    if not apply_end:
        return []
    out = []
    for item in card.get("tasks") or []:
        title = item.get("title") if isinstance(item, dict) else item
        if not isinstance(title, str) or not title.strip():
            continue
        title = title.strip()
        due = date.fromisoformat(apply_end) - timedelta(days=prep_days(title))
        out.append({"title": title, "due": due.isoformat()})
    return out


def unresolved(label, need, reason, quote="", source=None):
    return {"type": "unresolved", "label": label, "need": need,
            "params": {"reason": reason}, "source": source, "quote": quote}


def build_conditions(good, dropped, sources, unreadable):
    """The rows we store: kept conditions plus one unresolved per open question.

    Nothing is dropped silently -- a condition that vanishes would read as
    "you can apply" on the screen (SPEC 8.6).
    """
    conditions, reviews = [], []
    for cond in good:
        source = sources[cond["source"] - 1]
        if source.get("confidence") == "low":
            # A shaky image transcript keeps its quote and its source.
            conditions.append(unresolved(cond["label"], cond["need"], "판독 저신뢰",
                                         cond["quote"], cond["source"]))
            reviews.append({"reason": "판독 저신뢰", "note": source["label"]})
        else:
            conditions.append({k: cond[k] for k in
                               ("type", "label", "need", "params", "source", "quote")})
            reviews.append(None)
    for item in dropped:
        conditions.append(unresolved(item["label"], item["need"], "못 찾음"))
        reviews.append({"reason": "못 찾음", "note": item["why"]})
    if unreadable:
        # One condition for the whole notice; the file names go in the note.
        conditions.append(unresolved("지원 자격", "확인 중", "열람 불가"))
        reviews.append({"reason": "열람 불가", "note": ", ".join(unreadable)})
    if not conditions:
        conditions.append(unresolved("지원 자격", "확인 중", "못 찾음"))
        reviews.append({"reason": "못 찾음", "note": "조건을 찾지 못했다"})
    for index, cond in enumerate(conditions, 1):
        cond["id"] = f"c{index}"
    return conditions, reviews


def write_all(conn, notice, card, sources, conditions, reviews, tasks, trace, existing):
    """Raw text and result in one transaction: a failure writes nothing (SPEC 8.6)."""
    key = notice["key"]
    with conn:
        # Prepared image transcripts stay; everything else is written again.
        conn.execute("DELETE FROM raw_source WHERE notice_key = ? AND kind != 'image'", (key,))
        row_ids = {}
        for index, source in enumerate(sources, 1):
            if source.get("row_id"):
                row_ids[index] = source["row_id"]
                continue
            cur = conn.execute(
                "INSERT INTO raw_source (notice_key, ord, kind, label, url, text, confidence)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key, index, source["kind"], source["label"], source["url"],
                 source["text"], source.get("confidence")),
            )
            row_ids[index] = cur.lastrowid
        stored = []
        for cond in conditions:
            number = cond.pop("source", None)
            cond["source_id"] = row_ids.get(number) if number else None
            stored.append({k: cond[k] for k in
                           ("id", "type", "label", "need", "params", "source_id", "quote")})

        conn.execute(
            "DELETE FROM task_done WHERE task_id IN"
            " (SELECT id FROM task_template WHERE notice_key = ?)", (key,))
        conn.execute("DELETE FROM task_template WHERE notice_key = ?", (key,))
        for index, task in enumerate(tasks, 1):
            conn.execute(
                "INSERT INTO task_template (notice_key, ord, title, due) VALUES (?, ?, ?, ?)",
                (key, index, task["title"], task["due"]))

        conn.execute("DELETE FROM review WHERE notice_key = ?", (key,))
        for cond, review in zip(stored, reviews):
            if review:
                conn.execute(
                    "INSERT INTO review (notice_key, condition_id, reason, note, resolved)"
                    " VALUES (?, ?, ?, ?, 0)",
                    (key, cond["id"], review["reason"], review["note"]))

        conn.execute(
            "INSERT OR REPLACE INTO card (notice_key, title, sub, dept, category, apply_start,"
            " apply_end, conditions, fields, trace, linked_to, check_ok, hidden, demo_new,"
            " interpreted_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 'agent')",
            (key, notice["title"], card.get("sub") or "",
             notice["department"] or notice["source_name"], card["category"],
             card.get("apply_start"), card.get("apply_end"),
             json.dumps(stored, ensure_ascii=False),
             json.dumps([list(pair) for pair in card.get("fields") or []], ensure_ascii=False),
             json.dumps(trace, ensure_ascii=False),
             existing["linked_to"] if existing else None,
             existing["hidden"] if existing else 0,
             existing["demo_new"] if existing else 0),
        )
    return stored


# ---------------------------------------------------------------- the loop


async def interpret(key, force=False, chat_fn=None):
    """Read one notice and write its card. -> a short report dict."""
    chat_fn = chat_fn or llm.chat
    conn = db.connect()
    try:
        notice = conn.execute("SELECT * FROM notice WHERE key = ?", (key,)).fetchone()
        if notice is None:
            return {"ok": False, "why": f"모르는 공지 key: {key}"}
        existing = conn.execute("SELECT * FROM card WHERE notice_key = ?", (key,)).fetchone()
        if existing is not None and existing["interpreted_by"] == "claude-prep" and not force:
            return {"ok": False, "why": "claude-prep 카드가 있다. 덮어쓰려면 --force."}

        sources = []
        if (notice["body_text"] or "").strip():
            sources.append({"kind": "body", "label": "본문", "url": notice["url"],
                            "text": notice["body_text"], "confidence": None})
        unreadable, trace, notes = [], [], []
        card, good, dropped = None, [], []
        for call in range(1, BUDGET + 1):
            last_call = call == BUDGET
            messages = build_messages(notice, sources, notes, unreadable, last_call)
            notes = []
            found = first_json((await chat_fn(messages)).get("text") or "")
            if found is None:
                notes.append(BROKEN_NOTE)  # a broken reply costs a call too
                continue
            if isinstance(found.get("skip"), str) and found["skip"].strip():
                return {"ok": True, "skipped": found["skip"].strip()}
            shape = found.get("card")
            if not isinstance(shape, dict):
                notes.append("card 객체가 없다. card와 next를 함께 내라.")
                continue
            why = check_card(shape)
            fresh_good, fresh_dropped = sort_conditions(shape.get("conditions"), sources)
            if why:
                notes.append("카드를 고쳐라: " + why)
            else:  # card and conditions always move together
                card, good, dropped = shape, fresh_good, fresh_dropped
            for item in fresh_dropped:
                notes.append(f"조건 '{item['label']}'을 버렸다: {item['why']}")

            step = found.get("next") or {}
            if step.get("tool") == "finish" or last_call:
                # A finish with thrown-away values is not a finish (SPEC 8.6).
                if last_call or not (why or fresh_dropped):
                    break
                continue
            source, tool_why, cannot_read = run_tool(conn, notice, step, sources)
            trace.append({"tool": step.get("tool"), "arg": step.get("arg"),
                          "ok": source is not None})
            if source is None:
                notes.append(tool_why)
                if cannot_read and cannot_read not in unreadable:
                    unreadable.append(cannot_read)
                continue
            sources.append(source)

        if card is None:
            # SPEC 8.6: no category by the end of the budget writes nothing at all.
            return {"ok": False, "why": "예산 안에 카드를 채우지 못했다"}
        conditions, reviews = build_conditions(good, dropped, sources, unreadable)
        tasks = build_tasks(card, card.get("apply_end"))
        stored = write_all(conn, notice, card, sources, conditions, reviews, tasks,
                           trace, existing)
        return {
            "ok": True,
            "key": key,
            "category": card["category"],
            "conditions": len(stored),
            "unresolved": sum(1 for c in stored if c["type"] == "unresolved"),
            "sources": len(sources),
            "tasks": len(tasks),
        }
    finally:
        conn.close()


def main(argv):
    force = "--force" in argv
    keys = [a for a in argv if not a.startswith("-")]
    if len(keys) != 1:
        print("usage: python -m app.interpret <notice key> [--force]")
        return 1
    report = asyncio.run(interpret(keys[0], force=force))
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
