"""T17: the notice interpretation agent (SPEC 8.6, 6.2).

Pure functions plus a few loop runs on a temp DB with a fake LLM. No network,
no llm-x.
"""

import asyncio
import io
import json
import zipfile

import pytest

from app import db, interpret
from test_api import add_notice

BODY = ("2026학년도 1학기 성적우수 장학생을 모집합니다.\n"
        "지원 자격: 직전 학기 평점평균 3.5 이상인 재학생\n"
        "신청 기간: 2026-03-09 ~ 2026-03-20\n"
        "제출 서류: 신청서, 성적증명서")
QUOTE = "직전 학기 평점평균 3.5 이상인 재학생"


@pytest.fixture
def world(tmp_path, monkeypatch):
    path = str(tmp_path / "interpret.db")
    monkeypatch.setenv("DB_PATH", path)
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init(path)
    add_notice(path, "a:1", title="성적우수 장학금 안내")
    conn = db.connect(path)
    with conn:
        conn.execute("UPDATE notice SET body_text = ? WHERE key = 'a:1'", (BODY,))
    conn.close()
    return path


def sources_of(text=BODY, confidence=None, label="본문"):
    return [{"kind": "body", "label": label, "url": "https://example/a", "text": text,
             "confidence": confidence}]


def gpa_cond(quote=QUOTE, source=1, **over):
    cond = {"type": "gpa", "label": "직전 학기 평점", "need": "3.5 이상",
            "params": {"min": 3.5, "scope": "last"}, "source": source, "quote": quote}
    cond.update(over)
    return cond


def card_of(**over):
    card = {"category": "장학", "sub": "등록금 일부 감면", "apply_start": "2026-03-09",
            "apply_end": "2026-03-20", "conditions": [gpa_cond()],
            "fields": [["제출 서류", "신청서, 성적증명서"]], "tasks": ["신청서 제출"]}
    card.update(over)
    return card


# ------------------------------------------------------------ attachment format


def zipped(*entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as bundle:
        for name, text in entries:
            bundle.writestr(name, text)
    return buf.getvalue()


DOCX_XML = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org'
            '/wordprocessingml/2006/main"><w:body>'
            '<w:p><w:r><w:t>지원 자격: 재학생 누구나</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>마감 2026-03-20</w:t></w:r></w:p></w:body></w:document>')
HWPX_XML = ('<?xml version="1.0"?><hs:sec xmlns:hs="http://hs" xmlns:hp="http://hp">'
            '<hp:p><hp:run><hp:t>소득 8분위 이하</hp:t></hp:run></hp:p></hs:sec>')


@pytest.mark.parametrize("data, kind", [
    (b"%PDF-1.7\n...", "pdf"),
    (zipped(("word/document.xml", DOCX_XML)), "docx"),
    (zipped(("Contents/section0.xml", HWPX_XML)), "hwpx"),
    (zipped(("Contents/section2.xml", HWPX_XML)), "hwpx"),
    (zipped(("hello.txt", "just a zip")), None),  # some other zip
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", None),  # HWP 5.0 (OLE): unreadable
    (b"not a document at all", None),
    (b"", None),
    (None, None),
])
def test_the_format_comes_from_the_content_not_the_name(data, kind):
    assert interpret.attachment_kind(data) == kind


def test_docx_and_hwpx_text_comes_out_paragraph_by_paragraph():
    docx = interpret.attachment_text(zipped(("word/document.xml", DOCX_XML)))
    hwpx = interpret.attachment_text(zipped(("Contents/section0.xml", HWPX_XML)))
    assert docx.splitlines() == ["지원 자격: 재학생 누구나", "마감 2026-03-20"]
    assert hwpx == "소득 8분위 이하"


def test_a_file_we_cannot_convert_has_no_text():
    assert interpret.attachment_text(b"\xd0\xcf\x11\xe0") == ""
    assert interpret.attachment_text(zipped(("a.txt", "x"))) == ""


def test_html_text_drops_script_and_style():
    page = ("<html><head><style>p{color:red}</style></head><body><p>지원 자격</p>"
            "<script>var x = 1;</script><div>재학생 누구나</div></body></html>")
    text = interpret.html_text(page)
    assert "color" not in text and "var x" not in text
    assert text.splitlines() == ["지원 자격", "재학생 누구나"]


@pytest.mark.parametrize("url, ok", [
    ("https://kookmin.ac.kr/a", True),
    ("https://cs.kookmin.ac.kr/a?b=1", True),
    ("https://evil.com/kookmin.ac.kr", False),
    ("https://kookmin.ac.kr.evil.com/a", False),
    ("https://notkookmin.ac.kr/a", False),
    ("", False),
    (None, False),
])
def test_only_kookmin_links_are_opened(url, ok):
    assert interpret.allowed_host(url) is ok


# ------------------------------------------------------------ quote and params


def test_a_quote_must_match_letter_for_letter():
    assert interpret.check_quote(QUOTE, BODY) is True
    assert interpret.check_quote("직전 학기 평점평균  3.5 이상인 재학생", BODY) is False  # spacing
    assert interpret.check_quote("직전학기 평점평균 3.5 이상인 재학생", BODY) is False
    assert interpret.check_quote("", BODY) is False
    assert interpret.check_quote("없는 문장", BODY) is False


def test_a_condition_with_a_real_quote_is_kept():
    assert interpret.check_condition(gpa_cond(), sources_of()) is None


@pytest.mark.parametrize("cond, why", [
    (gpa_cond(quote="평점 3.5 이상"), "quote"),  # the body says "평점평균 3.5 이상"
    (gpa_cond(source=2), "source"),
    (gpa_cond(source="1"), "source"),
    (gpa_cond(params={"min": 3.5}), "params 키"),
    (gpa_cond(params={"min": 3.5, "scope": "semester"}), "params 값"),
    (gpa_cond(params={"min": 9.9, "scope": "last"}), "params 값"),
    (gpa_cond(type="unresolved", params={"reason": "못 찾음"}), "모르는 type"),
    (gpa_cond(type="nationality", params={}), "모르는 type"),
    (gpa_cond(label=""), "label"),
    (gpa_cond(need=" "), "need"),
])
def test_a_condition_that_breaks_a_rule_is_thrown_away(cond, why):
    reason = interpret.check_condition(cond, sources_of())
    assert reason and why in reason


def test_major_names_must_come_from_the_screen_list():
    good = gpa_cond(type="major", label="전공", need="소프트웨어학부",
                    params={"majors": ["소프트웨어학부", "인공지능학부"]},
                    quote=QUOTE)
    bad = dict(good, params={"majors": ["SW 관련 학과"]})
    assert interpret.check_condition(good, sources_of()) is None
    assert "params 값" in interpret.check_condition(bad, sources_of())
    assert "소프트웨어학부" in interpret.dept_names()
    assert "SW 관련 학과" not in interpret.dept_names()


@pytest.mark.parametrize("params, ok", [
    ({"any_of": {"TOEIC": 800, "IELTS": 6.0}}, True),
    ({"any_of": {"OPIc": "IM2"}}, True),
    ({"any_of": {"OPIc": 800}}, False),
    ({"any_of": {"TOPIK": 3}}, False),  # TOPIK is its own type (SPEC 6.2)
    ({"any_of": {}}, False),
])
def test_lang_params_follow_the_table(params, ok):
    cond = gpa_cond(type="lang", label="어학 성적", need="TOEIC 800 이상", params=params)
    assert (interpret.check_condition(cond, sources_of()) is None) is ok


@pytest.mark.parametrize("card, why", [
    (card_of(), None),
    (card_of(category="장학금"), "category"),
    (card_of(apply_end="2026/03/20"), "apply_end"),
    (card_of(apply_start="2026-03-21"), "apply_start"),
    (card_of(apply_start=None, apply_end=None), None),
    (card_of(fields=[["제출 서류"]]), "fields"),
    (card_of(fields=["제출 서류"]), "fields"),
])
def test_the_card_fields_are_checked(card, why):
    reason = interpret.check_card(card)
    assert (reason is None) if why is None else (why in reason)


# ------------------------------------------------------------ what gets stored


def test_a_low_confidence_transcript_keeps_its_quote_but_needs_a_review():
    sources = sources_of(confidence="low", label="이미지 1")
    conditions, reviews = interpret.build_conditions([gpa_cond()], [], sources, [])
    assert conditions[0]["type"] == "unresolved"
    assert conditions[0]["params"] == {"reason": "판독 저신뢰"}
    assert conditions[0]["quote"] == QUOTE and conditions[0]["source"] == 1
    assert reviews[0] == {"reason": "판독 저신뢰", "note": "이미지 1"}


def test_a_thrown_away_condition_stays_as_unresolved_without_its_quote():
    dropped = [{"label": "직전 학기 평점", "need": "3.5 이상", "why": "quote가 없다"}]
    conditions, reviews = interpret.build_conditions([], dropped, sources_of(), [])
    assert conditions[0]["type"] == "unresolved"
    assert conditions[0]["label"] == "직전 학기 평점"  # the model's wording is kept
    assert conditions[0]["quote"] == "" and conditions[0]["source"] is None
    assert reviews[0]["reason"] == "못 찾음"


def test_unreadable_files_become_one_condition_naming_them():
    conditions, reviews = interpret.build_conditions(
        [gpa_cond()], [], sources_of(), ["붙임1.hwp", "붙임2.hwp"])
    assert [c["type"] for c in conditions] == ["gpa", "unresolved"]
    assert conditions[1]["label"] == "지원 자격" and conditions[1]["need"] == "확인 중"
    assert reviews[1] == {"reason": "열람 불가", "note": "붙임1.hwp, 붙임2.hwp"}
    assert reviews[0] is None  # a kept condition has no review row


def test_a_notice_with_nothing_found_still_gets_one_condition():
    conditions, reviews = interpret.build_conditions([], [], sources_of(), [])
    assert len(conditions) == 1
    assert conditions[0]["label"] == "지원 자격" and conditions[0]["need"] == "확인 중"
    assert conditions[0]["params"] == {"reason": "못 찾음"}
    assert reviews[0]["reason"] == "못 찾음"


def test_condition_ids_are_c1_upward():
    conditions, _ = interpret.build_conditions(
        [gpa_cond(), gpa_cond()], [{"label": "x", "need": "y", "why": "z"}],
        sources_of(), ["붙임1.hwp"])
    assert [c["id"] for c in conditions] == ["c1", "c2", "c3", "c4"]


@pytest.mark.parametrize("title, due", [
    ("신청서 제출", "2026-03-20"),
    ("온라인 지원", "2026-03-20"),
    ("성적증명서 발급", "2026-03-18"),
    ("추천서 받기", "2026-03-15"),
    ("무언가 하기", "2026-03-19"),  # not in the table: one day
])
def test_task_due_is_the_deadline_minus_the_prep_days(title, due):
    tasks = interpret.build_tasks({"tasks": [title]}, "2026-03-20")
    assert tasks == [{"title": title, "due": due}]


def test_a_card_without_a_deadline_has_no_tasks():
    assert interpret.build_tasks({"tasks": ["신청서 제출"]}, None) == []


def test_first_json_reads_past_prose_and_a_code_fence():
    assert interpret.first_json('네 {틀림} ```json\n{"skip": "강연 안내"}\n```') == {"skip": "강연 안내"}
    assert interpret.first_json("no json") is None
    assert interpret.first_json('{"answer": "x"}') is None  # not one of our keys


# ------------------------------------------------------------ the loop


def fake_llm(*replies):
    calls = []

    async def chat_fn(messages):
        calls.append(messages)
        assert len(calls) <= len(replies), "the loop called the LLM too many times"
        return {"text": replies[len(calls) - 1], "input_tokens": 9, "output_tokens": 9,
                "tps": None, "seconds": 0.01}

    chat_fn.calls = calls
    return chat_fn


def said(card=None, tool="finish", arg=None, skip=None):
    if skip is not None:
        return json.dumps({"skip": skip}, ensure_ascii=False)
    return json.dumps({"card": card, "next": {"tool": tool, "arg": arg}}, ensure_ascii=False)


def run(key, chat_fn, force=False):
    return asyncio.run(interpret.interpret(key, force=force, chat_fn=chat_fn))


def card_row(path, key="a:1"):
    conn = db.connect(path)
    row = conn.execute("SELECT * FROM card WHERE notice_key = ?", (key,)).fetchone()
    conn.close()
    return row


def test_a_finished_card_is_written_with_its_raw_source_and_tasks(world):
    report = run("a:1", fake_llm(said(card_of())))
    assert report["ok"] and report["category"] == "장학"
    row = card_row(world)
    assert row["interpreted_by"] == "agent" and row["check_ok"] is None
    assert row["apply_end"] == "2026-03-20" and row["sub"] == "등록금 일부 감면"
    conditions = json.loads(row["conditions"])
    assert conditions[0]["type"] == "gpa" and conditions[0]["quote"] == QUOTE
    conn = db.connect(world)
    source = conn.execute("SELECT * FROM raw_source WHERE id = ?",
                          (conditions[0]["source_id"],)).fetchone()
    tasks = conn.execute("SELECT title, due FROM task_template ORDER BY ord").fetchall()
    reviews = conn.execute("SELECT COUNT(*) FROM review").fetchone()[0]
    conn.close()
    assert source["kind"] == "body" and QUOTE in source["text"]
    assert [(t["title"], t["due"]) for t in tasks] == [("신청서 제출", "2026-03-20")]
    assert reviews == 0


def test_the_question_and_the_raw_text_go_to_the_right_messages(world):
    chat_fn = fake_llm(said(card_of()))
    run("a:1", chat_fn)
    system, user = chat_fn.calls[0]
    assert system["role"] == "system" and user["role"] == "user"
    assert QUOTE in system["content"] and system["content"].endswith("/no_think")
    assert user["content"] == "a:1\n성적우수 장학금 안내"  # key and title only


def test_a_made_up_quote_is_asked_again_and_then_left_unresolved(world):
    bad = card_of(conditions=[gpa_cond(quote="평점 3.5 이상")])
    chat_fn = fake_llm(said(bad), said(bad), said(bad), said(bad),
                       said(bad), said(bad), said(bad), said(bad))
    report = run("a:1", chat_fn)
    assert len(chat_fn.calls) == interpret.BUDGET  # finish with a dropped value asks again
    assert "조건 '직전 학기 평점'을 버렸다" in chat_fn.calls[1][0]["content"]
    assert report["ok"] and report["unresolved"] == 1
    conditions = json.loads(card_row(world)["conditions"])
    assert conditions[0]["type"] == "unresolved" and conditions[0]["quote"] == ""
    conn = db.connect(world)
    review = conn.execute("SELECT * FROM review").fetchone()
    conn.close()
    assert review["condition_id"] == "c1" and review["reason"] == "못 찾음"
    assert review["resolved"] == 0


def test_a_skip_writes_nothing(world):
    report = run("a:1", fake_llm(said(skip="강연 안내라 기회 공지가 아니다")))
    assert report == {"ok": True, "skipped": "강연 안내라 기회 공지가 아니다"}
    assert card_row(world) is None


def test_no_category_by_the_end_of_the_budget_writes_nothing(world):
    broken = said(card_of(category="장학금"))
    report = run("a:1", fake_llm(*([broken] * interpret.BUDGET)))
    assert report["ok"] is False
    assert card_row(world) is None


def test_broken_json_costs_a_call_and_the_model_is_told(world):
    chat_fn = fake_llm("음, 잠시만요", said(card_of()))
    report = run("a:1", chat_fn)
    assert report["ok"] and len(chat_fn.calls) == 2
    assert interpret.BROKEN_NOTE in chat_fn.calls[1][0]["content"]


def test_a_prep_card_is_not_overwritten_without_force(world):
    run("a:1", fake_llm(said(card_of())))
    conn = db.connect(world)
    with conn:
        conn.execute("UPDATE card SET interpreted_by = 'claude-prep', hidden = 1,"
                     " demo_new = 1 WHERE notice_key = 'a:1'")
    conn.close()
    assert run("a:1", fake_llm(said(card_of())))["ok"] is False
    report = run("a:1", fake_llm(said(card_of(sub="다시 읽은 요약"))), force=True)
    assert report["ok"]
    row = card_row(world)
    assert row["sub"] == "다시 읽은 요약" and row["interpreted_by"] == "agent"
    assert row["hidden"] == 1 and row["demo_new"] == 1  # kept across a re-run


def test_an_unknown_key_is_an_error(world):
    assert run("nope:1", fake_llm(said(card_of())))["ok"] is False


def test_an_unknown_tool_comes_back_to_the_model(world):
    chat_fn = fake_llm(said(card_of(), tool="ask_dean"), said(card_of()))
    report = run("a:1", chat_fn)
    assert report["ok"]
    assert "그런 도구는 없다" in chat_fn.calls[1][0]["content"]


def test_a_missing_attachment_is_reported_but_an_unreadable_one_is_a_review(world):
    conn = db.connect(world)
    with conn:
        conn.execute("UPDATE notice SET attachments = ? WHERE key = 'a:1'",
                     (json.dumps([{"name": "붙임1.hwp", "url": "https://x/1.hwp"}]),))
    conn.close()
    chat_fn = fake_llm(said(card_of(), tool="read_attachment", arg="없는파일.pdf"),
                       said(card_of()))
    run("a:1", chat_fn)
    assert "붙임이 없다" in chat_fn.calls[1][0]["content"]
    assert "열람 불가로 표시한 것" not in chat_fn.calls[1][0]["content"]


def test_a_prepared_image_transcript_is_read_and_kept(world):
    conn = db.connect(world)
    with conn:
        conn.execute(
            "INSERT INTO raw_source (notice_key, ord, kind, label, url, text, confidence)"
            " VALUES ('a:1', 9, 'image', '이미지 1', 'https://x/1.png', ?, 'low')",
            ("포스터: " + QUOTE,))
        image_id = conn.execute("SELECT id FROM raw_source WHERE kind = 'image'").fetchone()[0]
    conn.close()
    chat_fn = fake_llm(said(card_of(conditions=[]), tool="read_image", arg=1),
                       said(card_of(conditions=[gpa_cond(source=2)])))
    report = run("a:1", chat_fn)
    assert report["ok"] and report["unresolved"] == 1  # low confidence -> review
    conditions = json.loads(card_row(world)["conditions"])
    assert conditions[0]["source_id"] == image_id and conditions[0]["quote"] == QUOTE
    conn = db.connect(world)
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM raw_source ORDER BY id")]
    review = conn.execute("SELECT reason FROM review").fetchone()[0]
    conn.close()
    assert kinds == ["image", "body"]  # the prepared transcript survives the rewrite
    assert review == "판독 저신뢰"
