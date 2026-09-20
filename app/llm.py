"""llm-x gateway client (SPEC 8.4).

The gateway is not OpenAI compatible: one POST to {LLM_BASE_URL}/chat streams SSE
lines, each `data: {json}`, and the stream is only complete once `data: [DONE]`
arrives. Every failure the caller has to turn into one `error` event is a
RuntimeError here (missing config, `error` event, max_input reached, unreadable
line, no [DONE]); transport failures stay httpx.HTTPError.
"""

import json
import os
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

# The read timeout is a backstop only: /api/chat cancels the whole question at 60s.
TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def request_args(messages):
    """URL, headers and body for one gateway call.

    The config is read here and not at import time, so the server still boots
    with an empty key and only the chat tab fails (SPEC 8.4).
    """
    base = (os.environ.get("LLM_BASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("LLM_API_KEY") or "").strip()
    if not base or not key:
        raise RuntimeError("llm-x is not configured: set LLM_BASE_URL and LLM_API_KEY")
    thinking = (os.environ.get("LLM_THINKING") or "0").strip() == "1"
    body = {
        "messages": messages,
        "stream": True,  # never off: Cloudflare cuts a non-streaming call at ~100s
        "web_search": False,
        "thinking_enabled": thinking,
    }
    # Cloudflare in front of llm-x answers a challenge page (403) to httpx's default
    # User-Agent when the call comes from a cloud IP such as the EC2; a browser-like
    # UA passes. Korean home/campus IPs pass either way, which hid this in rehearsal.
    headers = {"Authorization": "Bearer " + key,
               "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
    return base + "/chat", headers, body


def new_state():
    return {
        "parts": [],
        "input_tokens": None,
        "output_tokens": None,
        "tps": None,
        "done": False,
    }


def feed(state, line):
    """Consume one SSE line. Returns True once `data: [DONE]` closed the stream."""
    line = line.strip()
    if not line:
        return False
    # ponytail: only `data:` lines and SSE comments are accepted, so a gateway that
    # starts sending `event:` lines would look unreadable; add the field then.
    if line.startswith(":"):
        return False
    if not line.startswith("data:"):
        raise RuntimeError("llm-x sent a line that is not SSE data")
    payload = line[len("data:"):].strip()
    if payload == "[DONE]":
        state["done"] = True
        return True
    try:
        event = json.loads(payload)
    except ValueError:
        raise RuntimeError("llm-x sent a line that is not JSON")
    if not isinstance(event, dict):
        raise RuntimeError("llm-x sent a line that is not an object")
    name = event.get("type") or event.get("event")
    if not isinstance(name, str):
        raise RuntimeError("llm-x sent an event without a type")

    if name == "token":
        text = event.get("text")
        if not isinstance(text, str):
            raise RuntimeError("llm-x sent a token event without text")
        state["parts"].append(text)
    elif name == "error":
        raise RuntimeError("llm-x returned an error event: {}".format(_reason(event)))
    elif name == "tokens_input":
        used = _number(event, "input")
        cap = _number(event, "max_input")
        state["input_tokens"] = int(used)
        if used >= cap:
            # Over max_input the gateway truncates silently, so the answer would be
            # built from a cut prompt. Fail loudly instead.
            raise RuntimeError(
                "llm-x input {} reached max_input {}".format(int(used), int(cap))
            )
    elif name == "tokens_output":
        state["output_tokens"] = int(_number(event, "output"))
        if event.get("tps") is not None:
            state["tps"] = float(_number(event, "tps"))
    # An event name we do not know yet is ignored on purpose.
    return False


def finish(state):
    if not state["done"]:
        raise RuntimeError("llm-x stream ended without [DONE]")
    return {
        "text": "".join(state["parts"]),
        "input_tokens": state["input_tokens"],
        "output_tokens": state["output_tokens"],
        "tps": state["tps"],
    }


def parse_lines(lines):
    """Fold whole SSE lines into the chat() result (seconds excluded)."""
    state = new_state()
    for line in lines:
        if feed(state, line):
            break
    return finish(state)


# ---------------------------------------------------------------- Claude (A/B, 9/20)

# The contest gateway (OpenAI-compatible, Claude behind Bedrock aliases; SPEC 3, 8.4).
# LLM_PROVIDER=claude turns it on; CLAUDE_API_KEY and CLAUDE_MODEL pick the key and the
# alias. Same contract as chat(). Chosen on 9/20 after an A/B on the rehearsal server:
# Qwen via llm-x dropped the search -> check_eligibility chain on 2 of 2 deadline
# questions, Claude Sonnet 5 kept it on 2 of 2. llm-x stays as the fallback path.
CLAUDE_BASE_URL = "https://52.79.201.46/v1"
CLAUDE_MODEL = "bedrock-claude-sonnet-5"


def claude_request_args(messages):
    """URL, headers and body for one gateway call; the Qwen-only `/no_think` tail is dropped."""
    base = (os.environ.get("CLAUDE_BASE_URL") or CLAUDE_BASE_URL).rstrip("/")
    key = (os.environ.get("CLAUDE_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("claude is not configured: set CLAUDE_API_KEY")
    body = {
        "model": os.environ.get("CLAUDE_MODEL") or CLAUDE_MODEL,
        "messages": [{"role": m["role"], "content": m["content"].removesuffix("/no_think").rstrip()}
                     for m in messages],
        "max_tokens": 1024,
        "stream": False,
    }
    return base + "/chat/completions", {"Authorization": "Bearer " + key}, body


async def claude_chat(messages, transport=None):
    url, headers, body = claude_request_args(messages)
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
    seconds = time.monotonic() - started
    data = resp.json()
    text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    usage = data.get("usage") or {}
    out = usage.get("completion_tokens")
    return {"text": text, "input_tokens": usage.get("prompt_tokens"), "output_tokens": out,
            "tps": round(out / seconds, 1) if out and seconds else None, "seconds": round(seconds, 2)}


async def chat(messages, transport=None):
    """One gateway call. Returns {text, input_tokens, output_tokens, tps, seconds}.

    `transport` is for tests (httpx.MockTransport); production leaves it None.
    """
    if os.environ.get("LLM_PROVIDER") == "claude":
        return await claude_chat(messages, transport)
    url, headers, body = request_args(messages)
    state = new_state()
    started = time.monotonic()
    # ponytail: a fresh AsyncClient per call, so connections are not pooled; keep one
    # module-level client if the handshake latency starts to show in the demo.
    async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as client:
        async with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                resp.raise_for_status()
            async for line in resp.aiter_lines():
                if feed(state, line):
                    break
    result = finish(state)
    result["seconds"] = round(time.monotonic() - started, 3)
    return result


def _number(event, field):
    value = event.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError("llm-x sent a {} event without {}".format(
            event.get("type") or event.get("event"), field))
    return value


def _reason(event):
    for field in ("error", "message", "text"):
        value = event.get(field)
        if isinstance(value, str) and value:
            return value
    return "no reason given"
