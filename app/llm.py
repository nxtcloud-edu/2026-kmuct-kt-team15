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
    return base + "/chat", {"Authorization": "Bearer " + key}, body


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


async def chat(messages, transport=None):
    """One gateway call. Returns {text, input_tokens, output_tokens, tps, seconds}.

    `transport` is for tests (httpx.MockTransport); production leaves it None.
    """
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
