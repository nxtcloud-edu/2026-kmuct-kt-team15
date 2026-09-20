"""T13, T14: the ask agent loop and the /api/chat stream (SPEC 8.4, 10.1 C1~C9).

The LLM is a fake that hands back canned replies in order. No network.
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import chat, db, llm
from test_api import add_card, add_task, gpa_cond, none_cond

TODAY = "2026-03-16"


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A temp DB with a student, plus the cards each test adds."""
    path = str(tmp_path / "chat.db")
    monkeypatch.setenv("DB_PATH", path)
    monkeypatch.setenv("DEMO_TODAY", TODAY)
    monkeypatch.setattr(db, "DB_PATH", path)
    chat.ASKS.clear()  # the rate-limit window is module state (SPEC 8.4)
    db.init(path)
    conn = db.connect(path)
    with conn:
        conn.execute(
            "INSERT INTO student (id, profile, created_at) VALUES ('s1', '{}', '2026-03-16')")
    conn.close()
    return {"path": path, "student": student(path, {"semesters": 5, "gpa": 3.52})}


def student(path, profile, student_id="s1", revealed=0):
    conn = db.connect(path)
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO student (id, profile, revealed_new, created_at)"
            " VALUES (?, ?, ?, '2026-03-16')",
            (student_id, json.dumps(profile, ensure_ascii=False), revealed),
        )
    conn.close()
    return {"id": student_id, "profile": profile, "revealed_new": revealed}


def fake_llm(*replies):
    """An LLM that answers with `replies` in order and complains if asked once more."""
    calls = []

    async def chat_fn(messages):
        calls.append(messages)
        assert len(calls) <= len(replies), "the loop called the LLM too many times"
        return {"text": replies[len(calls) - 1], "input_tokens": 10,
                "output_tokens": 5, "tps": None, "seconds": 0.01}

    chat_fn.calls = calls
    return chat_fn


def run(world, question, chat_fn):
    async def go():
        return [event async for event in
                chat.run_question(world["student"], question, chat_fn)]

    return asyncio.run(go())


def tool(name, **args):
    return json.dumps({"tool": name, "args": args}, ensure_ascii=False)


def answer(text="지원할 수 있어요.", refs=(), found=True, **extra):
    body = {"answer": text, "refs": list(refs), "found": found}
    body.update(extra)
    return json.dumps(body, ensure_ascii=False)


def steps(events):
    return [e for e in events if e["type"] == "step"]


def last(events):
    return events[-1]


def misses(world):
    conn = db.connect(world["path"])
    rows = conn.execute("SELECT student_id, question FROM chat_miss").fetchall()
    conn.close()
    return [(r["student_id"], r["question"]) for r in rows]


# ------------------------------------------------------------------ the tools


def test_an_empty_search_gives_the_open_cards_by_deadline(world):
    # C1
    add_card(world["path"], "a:1", apply_end="2026-03-20")
    add_card(world["path"], "a:2", apply_end=TODAY)  # closing today is still open
    add_card(world["path"], "a:3", apply_end="2026-03-15")  # closed
    add_card(world["path"], "a:4", apply_start="2026-03-20", apply_end="2026-03-30")
    events = run(world, "지금 뭐 있어?", fake_llm(tool("search_notices", query=""), answer()))
    result = steps(events)[0]
    assert result["detail"] == "카드 2건"
    conn = db.connect(world["path"])
    found, _ = chat.tool_search(conn, world["student"], {"query": "", "category": None})
    conn.close()
    assert [i["key"] for i in found["items"]] == ["a:2", "a:1"]
    assert [i["days_left"] for i in found["items"]] == [0, 4]
    assert all(i["open"] for i in found["items"])


def test_search_ranks_the_title_first_and_marks_a_past_notice(world):
    add_card(world["path"], "a:1", title="교환학생 파견 모집", apply_end="2026-03-20")
    add_card(world["path"], "a:2", title="장학금 안내", sub="교환학생 준비", apply_end="2026-03-20")
    add_card(world["path"], "a:3", title="교환학생 설명회", apply_end="2026-03-10")
    conn = db.connect(world["path"])
    result, detail = chat.tool_search(conn, world["student"], {"query": "교환학생", "category": None})
    conn.close()
    keys = [i["key"] for i in result["items"]]
    assert detail == "카드 3건"
    assert keys[-1] == "a:2"  # the title counts three times, the sub once
    assert [i["open"] for i in result["items"] if i["key"] == "a:3"] == [False]


def test_search_ignores_an_unknown_category_and_keeps_a_known_one(world):
    add_card(world["path"], "a:1", category="장학")
    add_card(world["path"], "a:2", category="국제교류")
    conn = db.connect(world["path"])
    both, _ = chat.tool_search(conn, world["student"], chat.normalize_args(
        "search_notices", {"query": "", "category": "없는분야"}))
    one, _ = chat.tool_search(conn, world["student"], chat.normalize_args(
        "search_notices", {"query": "", "category": "국제교류"}))
    conn.close()
    assert len(both["items"]) == 2
    assert [i["key"] for i in one["items"]] == ["a:2"]


def test_the_tools_never_see_a_card_outside_the_scope(world):
    add_card(world["path"], "ok:1")
    add_card(world["path"], "no:1", check_ok=None)
    add_card(world["path"], "no:2", hidden=1)
    add_card(world["path"], "no:3", linked_to="ok:1")
    add_card(world["path"], "no:4", posted="2026-03-17")
    add_card(world["path"], "no:5", demo_new=1)
    conn = db.connect(world["path"])
    rows = chat.scope_rows(conn, world["student"])
    conn.close()
    assert [r["notice_key"] for r in rows] == ["ok:1"]


def test_check_eligibility_without_keys_counts_the_open_cards(world):
    add_card(world["path"], "a:1", conditions=[gpa_cond(3.0)], apply_end="2026-03-20")
    add_card(world["path"], "a:2", conditions=[gpa_cond(4.0)], apply_end="2026-03-18")
    add_card(world["path"], "a:3", conditions=[none_cond()], apply_end="2026-03-19")
    conn = db.connect(world["path"])
    result, detail = chat.tool_check(conn, world["student"], chat.normalize_args(
        "check_eligibility", {}))
    conn.close()
    assert detail == "3건 중 2건 지원 가능"
    assert result["summary"] == "모집 중인 공지 3건 중 2건에 지금 지원할 수 있다"
    assert result["checked"] == 3 and result["eligible"] == 2
    assert [i["key"] for i in result["results"]] == ["a:3", "a:1"]  # deadline order
    assert result["results"][0]["days_left"] == 3


def test_check_eligibility_with_keys_reports_the_gap_and_not_found(world):
    add_card(world["path"], "a:1", conditions=[gpa_cond(4.0)])
    conn = db.connect(world["path"])
    result, detail = chat.tool_check(conn, world["student"], chat.normalize_args(
        "check_eligibility", {"notice_keys": ["a:1", "gone:9"]}))
    conn.close()
    assert result["not_found"] == ["gone:9"]
    assert result["results"][0]["eligible"] is False
    assert detail == result["results"][0]["gap"] == "학점 0.48 부족"
    assert result["results"][0]["conditions"][0]["status"] == "fail"


def test_check_eligibility_judges_with_the_overrides_and_keeps_the_profile(world):
    add_card(world["path"], "a:1", conditions=[gpa_cond(4.0)])
    conn = db.connect(world["path"])
    result, detail = chat.tool_check(conn, world["student"], chat.normalize_args(
        "check_eligibility", {"notice_keys": ["a:1"], "overrides": {"gpa": 4.2}}))
    conn.close()
    assert detail == "지원 가능"
    assert result["results"][0]["eligible"] is True
    assert world["student"]["profile"]["gpa"] == 3.52  # SPEC 8.1: never stored


@pytest.mark.parametrize("overrides", [
    {"gpa": 9}, {"semesters": 4.5}, {"lang_type": "TOEIC"}, {"topik": 7}, {"status": "졸업"},
])
def test_bad_overrides_are_rejected_like_patch(world, overrides):
    # C2: the same validation as PATCH /api/me.
    with pytest.raises(chat.ToolError):
        chat.normalize_args("check_eligibility", {"overrides": overrides})


@pytest.mark.parametrize("args", [
    {"notice_keys": []},
    {"notice_keys": ["a:%d" % i for i in range(11)]},
    {"notice_keys": [1, 2]},
    {"notice_keys": "a:1"},
])
def test_bad_notice_keys_are_rejected(args):
    with pytest.raises(chat.ToolError):
        chat.normalize_args("check_eligibility", args)


def test_keys_all_outside_the_scope_are_bad_arguments(world):
    add_card(world["path"], "a:1")
    conn = db.connect(world["path"])
    with pytest.raises(chat.ToolError):
        chat.tool_check(conn, world["student"], chat.normalize_args(
            "check_eligibility", {"notice_keys": ["gone:1", "gone:2"]}))
    conn.close()


def test_get_profile_detail_reads_the_profile(world):
    conn = db.connect(world["path"])
    result, detail = chat.tool_profile(conn, world["student"], {})
    _, no_gpa = chat.tool_profile(conn, student(world["path"], {"semesters": 5}, "s2"), {})
    _, empty = chat.tool_profile(conn, student(world["path"], {}, "s3"), {})
    conn.close()
    assert result["profile"]["gpa"] == 3.52
    assert detail == "5학기 이수 · 평균 3.52"
    assert no_gpa == "5학기 이수"
    assert empty == "입력한 정보 없음"


def test_get_plan_counts_the_remaining_tasks_and_drops_a_hidden_card(world):
    add_card(world["path"], "a:1", apply_end="2026-03-20")
    add_card(world["path"], "a:2", apply_end="2026-03-18", hidden=1)
    done_id = add_task(world["path"], "a:1", "서류 준비", "2026-03-18")
    add_task(world["path"], "a:1", "신청서 제출", "2026-03-19", ord_=2)
    conn = db.connect(world["path"])
    with conn:
        conn.execute("INSERT INTO plan VALUES ('s1', 'a:1', '2026-03-16')")
        conn.execute("INSERT INTO plan VALUES ('s1', 'a:2', '2026-03-16')")
        conn.execute("INSERT INTO task_done VALUES ('s1', ?)", (done_id,))
    result, detail = chat.tool_plan(conn, world["student"], {})
    conn.close()
    assert [i["key"] for i in result["items"]] == ["a:1"]
    assert detail == "계획 1개 · 남은 할 일 1개"


# ------------------------------------------------------------------ the loop


def test_message_order_and_the_date_line(world):
    add_card(world["path"], "a:1")
    chat_fn = fake_llm(tool("search_notices", query=""), answer())
    run(world, "뭐 있어?", chat_fn)
    first, second = chat_fn.calls[0], chat_fn.calls[1]
    assert [m["role"] for m in first] == ["system", "user", "system"]
    assert first[1]["content"] == "뭐 있어?"
    assert first[2]["content"].startswith(f"오늘은 {TODAY}이다.")
    assert first[2]["content"].endswith("/no_think")
    assert chat.FIRST_TOOL_NOTE in first[2]["content"]
    # The tool result lands in the third message, never in the instructions.
    assert "search_notices" in second[2]["content"]
    assert "a:1" in second[2]["content"]
    assert "a:1" not in second[0]["content"]


def test_step_events_carry_the_arg_and_detail(world):
    add_card(world["path"], "a:1", conditions=[gpa_cond(3.0)])
    events = run(world, "이거 돼?", fake_llm(
        tool("search_notices", query="장학"),
        tool("check_eligibility", notice_keys=["a:1"]),
        tool("get_profile"),
        answer(refs=["a:1"]),
    ))
    found = steps(events)
    assert [s["tool"] for s in found] == ["search_notices", "check_eligibility", "get_profile"]
    assert [s["title"] for s in found] == ["공지 검색", "조건 대조", "내 정보 불러오기"]
    assert found[0]["arg"] == 'query="장학"'
    assert found[1]["arg"] == 'notice_keys=["a:1"]'
    assert found[2]["arg"] == ""
    assert found[1]["detail"] == "지원 가능"
    assert all(isinstance(s["ms"], int) and s["ms"] >= 0 for s in found)


def test_refs_keep_only_the_keys_this_question_saw(world):
    # C3: a key the tools never showed and a closed notice both drop out.
    add_card(world["path"], "a:1", title="교환학생 모집", apply_end="2026-03-20")
    add_card(world["path"], "old:1", title="교환학생 지난 공지", apply_end="2026-03-10")
    events = run(world, "교환학생?", fake_llm(
        tool("search_notices", query="교환학생"),
        answer(refs=["a:1", "old:1", "never:9"]),
    ))
    reply = last(events)
    assert [r["key"] for r in reply["refs"]] == ["a:1"]
    assert reply["refs"][0]["rows"] == []
    assert reply["src"] == "학생지원팀 공지 · 3월 1일"


def test_src_is_the_search_line_when_refs_are_not_one(world):
    add_card(world["path"], "a:1", apply_end="2026-03-20")
    add_card(world["path"], "a:2", apply_end="2026-03-21")
    events = run(world, "뭐 있어?", fake_llm(
        tool("search_notices", query=""), answer(refs=["a:1", "a:2"])))
    assert last(events)["src"] == "공지 통합 검색"


def test_broken_json_is_retried_once(world):
    add_card(world["path"], "a:1")
    chat_fn = fake_llm("음... 잠시만요", tool("search_notices", query=""), answer())
    events = run(world, "뭐 있어?", chat_fn)
    assert chat.BROKEN_NOTE in chat_fn.calls[1][2]["content"]
    assert len(steps(events)) == 1
    assert last(events)["text"] == "지원할 수 있어요."


def test_two_broken_replies_in_a_row_are_a_miss(world):
    chat_fn = fake_llm("죄송합니다", "```\n{아직도 아님\n```")
    events = run(world, "뭐 있어?", chat_fn)
    assert last(events) == {"type": "answer", "text": chat.MISS_TEXT, "refs": [],
                            "src": "공지 통합 검색", "confirm_update": None}
    assert misses(world) == [("s1", "뭐 있어?")]


def test_json_is_read_out_of_prose_and_a_code_fence(world):
    assert chat.extract_json('생각: {틀림} 그리고 {"x": 1}\n```json\n{"answer": "네", "found": true}\n```'
                             ) == {"answer": "네", "found": True}
    assert chat.extract_json("{}") is None
    assert chat.extract_json("no json here") is None


def test_the_budget_is_five_calls_and_ends_in_a_miss(world):
    # Four tool calls plus the last call: the loop stops at five LLM calls.
    add_card(world["path"], "a:1")
    chat_fn = fake_llm(
        tool("search_notices", query="장학"),
        tool("get_profile"),
        tool("get_plan"),
        tool("check_eligibility"),
        tool("search_notices", query="또"),  # a tool on the last call is not run
    )
    events = run(world, "뭐 있어?", chat_fn)
    assert len(chat_fn.calls) == 5
    assert len(steps(events)) == 4
    assert last(events)["text"] == chat.MISS_TEXT
    assert misses(world) == [("s1", "뭐 있어?")]


def test_the_last_call_says_not_to_call_a_tool(world):
    # C5
    add_card(world["path"], "a:1")
    chat_fn = fake_llm(
        tool("get_profile"), tool("get_plan"), tool("search_notices", query=""),
        tool("check_eligibility"), answer())
    run(world, "뭐 있어?", chat_fn)
    assert chat.LAST_CALL_NOTE not in chat_fn.calls[3][2]["content"]
    assert chat.LAST_CALL_NOTE in chat_fn.calls[4][2]["content"]


def test_the_same_call_twice_is_not_run_again(world):
    # C4: no step, no second execution, but it costs a turn.
    add_card(world["path"], "a:1")
    chat_fn = fake_llm(
        tool("search_notices", query="장학"),
        tool("search_notices", query="장학"),
        answer(),
    )
    events = run(world, "뭐 있어?", chat_fn)
    assert len(steps(events)) == 1
    assert "이미 결과가 있다" in chat_fn.calls[2][2]["content"]
    assert "check_eligibility" in chat_fn.calls[2][2]["content"]


def test_an_unknown_tool_is_handed_back_to_the_model(world):
    # C6: a list where the tool name should be must not break the stream.
    add_card(world["path"], "a:1")
    chat_fn = fake_llm(
        json.dumps({"tool": ["search_notices"], "args": {}}),
        json.dumps({"tool": "ask_dean", "args": {}}),
        tool("search_notices", query=""),
        answer(),
    )
    events = run(world, "뭐 있어?", chat_fn)
    assert len(steps(events)) == 1
    assert "그런 도구는 없다" in chat_fn.calls[1][2]["content"]
    assert "그런 도구는 없다" in chat_fn.calls[2][2]["content"]
    assert last(events)["text"] == "지원할 수 있어요."


def test_bad_arguments_come_back_without_a_step(world):
    # C2 inside the loop.
    add_card(world["path"], "a:1")
    chat_fn = fake_llm(
        tool("check_eligibility", overrides={"gpa": 9}),
        tool("search_notices", query=""),
        answer(),
    )
    events = run(world, "학점 9면 돼?", chat_fn)
    assert len(steps(events)) == 1
    assert "check_eligibility 호출이 잘못됐다" in chat_fn.calls[1][2]["content"]


def test_found_false_before_any_tool_is_sent_back(world):
    add_card(world["path"], "a:1")
    chat_fn = fake_llm(
        answer("모르겠어요", found=False),
        tool("search_notices", query=""),
        answer(),
    )
    events = run(world, "뭐 있어?", chat_fn)
    assert chat.FIRST_TOOL_NOTE in chat_fn.calls[1][2]["content"]
    assert last(events)["text"] == "지원할 수 있어요."
    assert misses(world) == []


def test_found_false_with_results_is_nudged_once_then_missed(world):
    add_card(world["path"], "a:1")
    chat_fn = fake_llm(
        tool("search_notices", query=""),
        answer("없어요", found=False),
        answer("역시 없어요", found=False),
    )
    events = run(world, "뭐 있어?", chat_fn)
    assert "도구 결과에 공지 1건이 있다" in chat_fn.calls[2][2]["content"]
    assert last(events)["text"] == chat.MISS_TEXT
    assert misses(world) == [("s1", "뭐 있어?")]


def test_confirm_update_is_passed_through_and_not_stored(world):
    add_card(world["path"], "a:1", conditions=[gpa_cond(3.0)])
    events = run(world, "학점 3.8이야", fake_llm(
        tool("get_profile"),
        answer("학점을 바꿀까요?", confirm_update={"gpa": 3.8}),
    ))
    reply = last(events)
    assert reply["confirm_update"] == {"gpa": 3.8}
    conn = db.connect(world["path"])
    stored = conn.execute("SELECT profile FROM student WHERE id = 's1'").fetchone()[0]
    conn.close()
    assert json.loads(stored)["gpa"] == 3.52


def test_an_answer_with_no_notice_is_still_found(world):
    add_card(world["path"], "a:1", conditions=[gpa_cond(4.5)])
    events = run(world, "지원 가능한 거 있어?", fake_llm(
        tool("check_eligibility"), answer("지금 지원할 수 있는 공지는 없어요.")))
    assert steps(events)[0]["detail"] == "1건 중 0건 지원 가능"
    assert last(events)["text"] == "지금 지원할 수 있는 공지는 없어요."
    assert misses(world) == []


# ------------------------------------------------------------------ the stream


@pytest.fixture
def client(world):
    from app import main

    with TestClient(main.app) as c:
        c.headers["X-Student-Id"] = "s1"
        c.db_path = world["path"]
        yield c


def reply(text):
    return {"text": text, "input_tokens": 10, "output_tokens": 5, "tps": None,
            "seconds": 0.01}


def gateway(answer_text=None, delay=0.0, raises=None):
    """A stand-in for llm.chat: search once, then answer (SPEC 8.4 message order)."""
    async def chat_fn(messages):
        if raises is not None and chat.FIRST_TOOL_NOTE not in messages[2]["content"]:
            raise raises
        if chat.FIRST_TOOL_NOTE in messages[2]["content"]:
            return reply(tool("search_notices", query=""))
        if delay:
            await asyncio.sleep(delay)
        return reply(answer_text or answer(refs=["a:1"]))

    return chat_fn


def ask(client, message="지금 지원할 수 있는 거 있어?"):
    res = client.post("/api/chat", json={"message": message})
    lines = [json.loads(line) for line in res.text.splitlines() if line.strip()]
    return res, lines


def test_the_chat_route_needs_a_known_student(world):
    from app import main

    with TestClient(main.app) as c:
        assert c.post("/api/chat", json={"message": "안녕"}).status_code == 401
        c.headers["X-Student-Id"] = "nobody"
        assert c.post("/api/chat", json={"message": "안녕"}).status_code == 401


@pytest.mark.parametrize("message", ["가" * 301, "   ", "", None, 7, ["질문"]])
def test_a_bad_message_is_422(client, monkeypatch, message):
    monkeypatch.setattr(llm, "chat", gateway())
    assert client.post("/api/chat", json={"message": message}).status_code == 422


def test_three_hundred_characters_are_accepted(client, monkeypatch):
    add_card(client.db_path, "a:1")
    monkeypatch.setattr(llm, "chat", gateway())
    res, lines = ask(client, "가" * 300)
    assert res.status_code == 200
    assert lines[-1]["type"] == "answer"


def test_the_stream_is_ndjson_with_steps_then_one_answer(client, monkeypatch):
    add_card(client.db_path, "a:1", conditions=[gpa_cond(3.0)], apply_end="2026-03-20")
    monkeypatch.setattr(llm, "chat", gateway())
    res, lines = ask(client)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/x-ndjson")
    assert [line["type"] for line in lines] == ["step", "answer"]
    assert lines[0]["title"] == "공지 검색" and lines[0]["detail"] == "카드 1건"
    answer_line = lines[-1]
    assert [r["key"] for r in answer_line["refs"]] == ["a:1"]
    assert answer_line["refs"][0]["rows"][0]["chip"] == "학점 3.0 이상"  # 목록 항목 모양
    assert answer_line["confirm_update"] is None


def test_a_gateway_error_ends_the_stream_with_one_error_line(client, monkeypatch):
    # C7: an unreadable SSE line is a RuntimeError, and the route turns it into
    # exactly one error event.
    add_card(client.db_path, "a:1")

    async def broken(messages):
        return llm.parse_lines(["data: {not json", "data: [DONE]"])

    monkeypatch.setattr(llm, "chat", broken)
    res, lines = ask(client)
    assert res.status_code == 200
    assert lines == [{"type": "error", "text": chat.ERROR_TEXT}]


def test_a_missing_tokens_input_field_ends_the_same_way(client, monkeypatch):
    # C7, the second line of the table.
    add_card(client.db_path, "a:1")

    async def broken(messages):
        return llm.parse_lines(['data: {"event": "tokens_input", "max_input": 32768}',
                                "data: [DONE]"])

    monkeypatch.setattr(llm, "chat", broken)
    assert ask(client)[1] == [{"type": "error", "text": chat.ERROR_TEXT}]


def test_the_steps_already_sent_survive_a_timeout(client, monkeypatch):
    add_card(client.db_path, "a:1")
    monkeypatch.setattr(chat, "QUESTION_SECONDS", 0.2)
    monkeypatch.setattr(llm, "chat", gateway(delay=5))
    res, lines = ask(client)
    assert res.status_code == 200
    assert [line["type"] for line in lines] == ["step", "error"]
    assert lines[-1]["text"] == chat.ERROR_TEXT


def test_a_db_failure_is_an_error_line_too(client, monkeypatch):
    # The header is read first, so let that connection through and break the next.
    opened = {"count": 0}
    real = db.connect

    def flaky(path=None):
        opened["count"] += 1
        if opened["count"] > 1:
            raise db.sqlite3.OperationalError("unable to open database file")
        return real(path)

    monkeypatch.setattr(llm, "chat", gateway())
    monkeypatch.setattr(db, "connect", flaky)
    assert ask(client)[1] == [{"type": "error", "text": chat.ERROR_TEXT}]


def test_the_sixth_question_in_a_minute_is_refused(client, monkeypatch):
    # C9
    add_card(client.db_path, "a:1")
    monkeypatch.setattr(llm, "chat", gateway())
    for _ in range(chat.PER_MINUTE):
        assert ask(client)[1][-1]["type"] == "answer"
    res, lines = ask(client)
    assert res.status_code == 200  # refused, but not an HTTP error
    assert lines == [{"type": "error", "text": chat.ERROR_TEXT}]
    assert len(chat.ASKS["s1"]) == chat.PER_MINUTE  # a refused question is not counted


def test_the_window_lets_the_student_back_in_after_a_minute():
    # C9: 61 seconds later the same student is served again.
    chat.ASKS.clear()
    for second in range(chat.PER_MINUTE):
        assert chat.take_slot("s9", now=second) is True
    assert chat.take_slot("s9", now=59.9) is False
    assert chat.take_slot("s9", now=61) is True
    chat.ASKS.clear()


def test_the_limit_is_per_student():
    chat.ASKS.clear()
    for second in range(chat.PER_MINUTE):
        chat.take_slot("one", now=second)
    assert chat.take_slot("one", now=6) is False
    assert chat.take_slot("two", now=6) is True
    chat.ASKS.clear()


def test_at_most_three_gateway_calls_run_at_once(world, monkeypatch):
    # C8: the fourth question waits for a slot and still gets its answer.
    assert chat.CONCURRENCY == 3
    live = {"now": 0, "peak": 0}

    async def slow(messages):
        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        await asyncio.sleep(0.05)
        live["now"] -= 1
        return reply(answer("네, 있어요."))

    monkeypatch.setattr(llm, "chat", slow)
    # A fresh semaphore: TestClient gives each test its own event loop and an
    # asyncio.Semaphore binds to the first loop that has to wait on it.
    monkeypatch.setattr(chat, "SEM", asyncio.Semaphore(chat.CONCURRENCY))

    async def go():
        async def one(index):
            who = student(world["path"], {}, f"c{index}")
            return [event async for event
                    in chat.run_question(who, "질문", chat.guarded_chat)]

        return await asyncio.gather(*(one(i) for i in range(4)))

    runs = asyncio.run(go())
    assert live["peak"] <= chat.CONCURRENCY
    assert [run[-1]["text"] for run in runs] == ["네, 있어요."] * 4


# ------------------------------------------------ 9/20: total, and one turn of memory


def test_search_reports_the_total_beyond_the_page(world, monkeypatch):
    for i in range(12):
        add_card(world["path"], f"a:{i}", apply_end=f"2026-03-{20 + i}")
    conn = db.connect(world["path"])
    result, detail = chat.tool_search(conn, world["student"], {"query": "", "category": None})
    conn.close()
    assert (result["total"], result["shown"], len(result["items"])) == (12, 10, 10)
    assert detail == "12건 중 10건"


def test_the_previous_turn_is_carried_into_the_next_question(world):
    chat.LAST.clear()
    add_card(world["path"], "a:1")
    run(world, "뭐 있어?", fake_llm(tool("search_notices", query=""), answer("하나 있어요.", refs=["a:1"])))
    chat_fn = fake_llm(answer("그건 a:1이에요."))
    run(world, "그건 뭐야?", chat_fn)
    context = chat_fn.calls[0][2]["content"]
    assert "직전 질문: 뭐 있어?" in context
    assert "직전 답: 하나 있어요." in context
    assert "직전 답의 공지 key: a:1" in context
    # Another student never sees it, and the first question of a session has none.
    other = student(world["path"], {}, student_id="s2")
    chat_fn = fake_llm(answer())
    asyncio.run(chat.run_question(other, "뭐 있어?", chat_fn).__anext__())
    assert "직전 질문" not in chat_fn.calls[0][2]["content"]


def test_a_keyed_check_carries_the_cards_tasks(world):
    add_card(world["path"], "a:1")
    conn = db.connect(world["path"])
    with conn:
        conn.execute("INSERT INTO task_template (notice_key, ord, title, due) VALUES ('a:1', 1, '서류 준비', '2026-03-18')")
        conn.execute("INSERT INTO task_template (notice_key, ord, title, due) VALUES ('a:1', 2, '온라인 신청', '2026-03-20')")
    result, _ = chat.tool_check(conn, world["student"], chat.normalize_args(
        "check_eligibility", {"notice_keys": ["a:1"]}))
    conn.close()
    assert result["results"][0]["tasks"] == [
        {"title": "서류 준비", "due": "2026-03-18"}, {"title": "온라인 신청", "due": "2026-03-20"}]
    # The no-key list stays lean: no tasks there.
    conn = db.connect(world["path"])
    listing, _ = chat.tool_check(conn, world["student"], chat.normalize_args("check_eligibility", {}))
    conn.close()
    assert all("tasks" not in r for r in listing["results"])
