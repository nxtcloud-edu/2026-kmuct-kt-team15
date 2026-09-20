"""T12: llm-x gateway client (SPEC 8.4, 10.1 C7 and L1).

No network: the SSE lines are fakes and chat() runs over httpx.MockTransport.
"""

import asyncio
import json
import os

import httpx
import pytest

from app import llm


def test_the_gateway_keys_are_empty_in_tests():
    # SPEC 10: conftest clears them so no test can reach the real llm-x.
    assert os.environ["LLM_API_KEY"] == ""
    assert os.environ["LLM_BASE_URL"] == ""


def sse(*events):
    lines = []
    for event in events:
        lines.append("data: " + json.dumps(event, ensure_ascii=False))
        lines.append("")
    lines.append("data: [DONE]")
    return lines


def test_parse_lines_joins_tokens_and_keeps_the_usage():
    result = llm.parse_lines(sse(
        {"event": "tokens_input", "input": 3200, "max_input": 32768},
        {"type": "token", "text": "지원 가능한 "},
        {"type": "token", "text": "공지는 3건이에요."},
        {"event": "tokens_output", "output": 24, "tps": 41.5},
    ))
    assert result == {
        "text": "지원 가능한 공지는 3건이에요.",
        "input_tokens": 3200,
        "output_tokens": 24,
        "tps": 41.5,
    }


def test_tps_is_none_when_the_gateway_leaves_it_out():
    result = llm.parse_lines(sse(
        {"type": "token", "text": "ok"},
        {"event": "tokens_output", "output": 2},
    ))
    assert result["tps"] is None
    assert result["output_tokens"] == 2


def test_an_unknown_event_is_ignored():
    result = llm.parse_lines(sse({"event": "heartbeat"}, {"type": "token", "text": "ok"}))
    assert result["text"] == "ok"


BROKEN = [
    # C7: the two lines that cut the stream without an error in the rehearsal.
    ("not json", ["data: {not json", "data: [DONE]"]),
    ("tokens_input without input", [
        'data: {"event": "tokens_input", "max_input": 32768}', "data: [DONE]"]),
    ("error event", ['data: {"type": "error", "message": "upstream"}', "data: [DONE]"]),
    ("input at max_input", [
        'data: {"event": "tokens_input", "input": 32768, "max_input": 32768}',
        "data: [DONE]"]),
    ("input over max_input", [
        'data: {"event": "tokens_input", "input": 40000, "max_input": 32768}',
        "data: [DONE]"]),
    ("token without text", ['data: {"type": "token"}', "data: [DONE]"]),
    ("token text is not a string", [
        'data: {"type": "token", "text": 7}', "data: [DONE]"]),
    ("tokens_output without output", [
        'data: {"event": "tokens_output", "tps": 40}', "data: [DONE]"]),
    ("event without a type", ['data: {"text": "ok"}', "data: [DONE]"]),
    ("line that is not SSE data", ["oops", "data: [DONE]"]),
    ("no [DONE]", ['data: {"type": "token", "text": "cut"}']),
]


@pytest.mark.parametrize("case, lines", BROKEN, ids=[c for c, _ in BROKEN])
def test_a_broken_stream_raises(case, lines):
    with pytest.raises(RuntimeError):
        llm.parse_lines(lines)


def test_blank_lines_and_comments_are_skipped():
    assert llm.parse_lines(["", ": keep-alive", 'data: {"type": "token", "text": "a"}',
                            "", "data: [DONE]"])["text"] == "a"


def test_lines_after_done_are_not_read():
    assert llm.parse_lines(["data: [DONE]", "data: {not json"])["text"] == ""


def test_request_args_needs_the_key_at_call_time(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://gw.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "")
    with pytest.raises(RuntimeError):
        llm.request_args([{"role": "user", "content": "안녕"}])
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "")
    with pytest.raises(RuntimeError):
        llm.request_args([{"role": "user", "content": "안녕"}])


def test_request_args_follows_the_gateway_contract(monkeypatch):
    # L1
    monkeypatch.setenv("LLM_BASE_URL", "https://gw.example/v1/")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    monkeypatch.setenv("LLM_THINKING", "0")
    url, headers, body = llm.request_args([{"role": "user", "content": "안녕"}])
    assert url == "https://gw.example/v1/chat"
    assert headers["Authorization"] == "Bearer secret"
    assert body == {
        "messages": [{"role": "user", "content": "안녕"}],
        "stream": True,
        "web_search": False,
        "thinking_enabled": False,
    }
    monkeypatch.setenv("LLM_THINKING", "1")
    assert llm.request_args([])[2]["thinking_enabled"] is True


def run_chat(monkeypatch, body_lines, status=200):
    monkeypatch.setenv("LLM_BASE_URL", "https://gw.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    monkeypatch.setenv("LLM_THINKING", "0")
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(status, content="\n".join(body_lines).encode("utf-8"))

    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "안녕"}]
    coro = llm.chat(messages, transport=httpx.MockTransport(handler))
    return seen, asyncio.run(coro)


def test_chat_posts_the_documented_request_and_returns_the_answer(monkeypatch):
    # L1 over the wire.
    seen, result = run_chat(monkeypatch, sse(
        {"event": "tokens_input", "input": 3300, "max_input": 32768},
        {"type": "token", "text": '{"answer": "네", '},
        {"type": "token", "text": '"refs": [], "found": true}'},
        {"event": "tokens_output", "output": 12, "tps": 38.0},
    ))
    assert seen["method"] == "POST"
    assert seen["url"] == "https://gw.example/v1/chat"
    assert seen["auth"] == "Bearer secret"
    assert seen["body"] == {
        "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "안녕"}],
        "stream": True,
        "web_search": False,
        "thinking_enabled": False,
    }
    assert result["text"] == '{"answer": "네", "refs": [], "found": true}'
    assert result["input_tokens"] == 3300
    assert result["output_tokens"] == 12
    assert result["tps"] == 38.0
    assert result["seconds"] >= 0


def test_chat_raises_on_a_broken_line(monkeypatch):
    # C7: /api/chat turns this into one error event.
    with pytest.raises(RuntimeError):
        run_chat(monkeypatch, ["data: {not json", "data: [DONE]"])


def test_chat_raises_when_the_stream_stops_before_done(monkeypatch):
    with pytest.raises(RuntimeError):
        run_chat(monkeypatch, ['data: {"type": "token", "text": "cut"}'])


def test_chat_raises_http_error_on_a_gateway_status(monkeypatch):
    with pytest.raises(httpx.HTTPStatusError):
        run_chat(monkeypatch, ["data: [DONE]"], status=502)


# ------------------------------------------------ 9/20: the contest gateway (Claude)


def test_claude_path_posts_openai_shape_and_drops_no_think(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-test")
    monkeypatch.setenv("CLAUDE_MODEL", "bedrock-claude-sonnet-5")
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": '{"answer": "네"}'}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 7}})

    messages = [{"role": "system", "content": "지시"}, {"role": "user", "content": "질문"},
                {"role": "system", "content": "오늘은 2026-03-16이다.\n/no_think"}]
    result = asyncio.run(llm.chat(messages, transport=httpx.MockTransport(handler)))
    assert seen["url"] == "https://52.79.201.46/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"]["model"] == "bedrock-claude-sonnet-5"
    assert seen["body"]["stream"] is False
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user", "system"]
    assert seen["body"]["messages"][2]["content"] == "오늘은 2026-03-16이다."
    assert (result["text"], result["input_tokens"], result["output_tokens"]) == ('{"answer": "네"}', 40, 7)


def test_claude_path_needs_its_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        llm.claude_request_args([{"role": "user", "content": "x"}])
