"""LM Studio client (OpenAI-compatible) with JSON-validated calls and streaming."""
import json
import re
from typing import Callable, Iterator, TypeVar

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from . import config

T = TypeVar("T", bound=BaseModel)

llm = ChatOpenAI(
    model=config.LM_MODEL,
    api_key=config.LM_API_KEY,
    base_url=config.LM_BASE_URL,
    temperature=config.LM_TEMPERATURE,
    max_tokens=config.LM_MAX_TOKENS,
    timeout=config.LM_TIMEOUT,
    max_retries=1,
)

LlmLog = Callable[[str, str, str, str], None]  # agent, system, user, output


def _clean(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    return re.sub(r"^.*?</think>", "", text, flags=re.S | re.I).strip()


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p if isinstance(p, str) else p.get("text", "") for p in content)
    return ""


MAX_TOKENS_CAP = 12288


def ask(system: str, user: str, schema: dict | None = None) -> str:
    """Call the model. Reasoning models may burn the whole budget on thinking and return empty
    content with finish_reason=length; in that case retry with a doubled budget (up to a cap)."""
    budget = config.LM_MAX_TOKENS
    while True:
        model = llm.bind(max_tokens=budget)
        if schema:  # LM Studio supports grammar-constrained JSON via response_format=json_schema
            model = model.bind(response_format={"type": "json_schema", "json_schema": {"name": "result", "schema": schema}})
        res = model.invoke([SystemMessage(system), HumanMessage(user)])
        text = _clean(_text(res.content))
        truncated = (res.response_metadata or {}).get("finish_reason") == "length"
        if text or not truncated or budget >= MAX_TOKENS_CAP:
            return text
        budget = min(budget * 2, MAX_TOKENS_CAP)


def stream_chat(system: str, history: list[dict]) -> Iterator[str]:
    messages = [SystemMessage(system)] + [
        HumanMessage(m["content"]) if m["role"] == "user" else AIMessage(m["content"]) for m in history
    ]
    buffer, in_think = "", False
    for chunk in llm.stream(messages):
        buffer += _text(chunk.content)
        while True:  # hide <think> blocks emitted by reasoning models
            if in_think:
                end = buffer.find("</think>")
                if end == -1:
                    buffer = ""
                    break
                buffer, in_think = buffer[end + 8 :], False
            else:
                start = buffer.find("<think>")
                if start == -1:
                    break
                if start:
                    yield buffer[:start]
                buffer, in_think = buffer[start + 7 :], True
        if not in_think and buffer and not "<think>".startswith(buffer[-6:]):
            yield buffer
            buffer = ""
    if not in_think and buffer:
        yield buffer


def _extract_json(text: str):
    text = re.sub(r"```(?:json)?", "", text)
    match = re.search(r"[{\[]", text)
    if not match:
        raise ValueError("no JSON found in model output")
    start = match.start()
    end = text.rfind("}" if text[start] == "{" else "]")
    if end <= start:
        raise ValueError("unterminated JSON in model output")
    return json.loads(text[start : end + 1])


def ask_json(system: str, user: str, model: type[T], agent: str, log: LlmLog | None = None) -> T:
    """Ask for JSON, validate with pydantic, retry once feeding the error back."""
    prompt, last_error = user, "unknown"
    schema: dict | None = model.model_json_schema()
    sys_prompt = system + "\n\nRespond with ONE valid JSON value only. No prose, no markdown."
    for _ in range(3):
        try:
            output = ask(sys_prompt, prompt, schema)
        except Exception as exc:  # noqa: BLE001
            if schema is None or is_connection_error(exc):
                raise
            schema = None  # server rejected structured output; fall back to prompt-only JSON
            output = ask(sys_prompt, prompt)
        if log:
            log(agent, system, prompt, output)
        try:
            if not output.strip():
                raise ValueError(
                    "empty response - a reasoning model likely used all tokens thinking; "
                    "load a non-thinking instruct model (e.g. qwen3-4b-instruct-2507) or raise LM_STUDIO_MAX_TOKENS"
                )
            return model.model_validate(_extract_json(output))
        except (ValueError, ValidationError) as exc:
            last_error = str(exc)[:300].replace("\n", " ")
            if output.strip():
                last_error += f" | output began: {output.strip()[:120]!r}"
            prompt = f"{user}\n\nYour previous answer was invalid ({last_error}). Return corrected JSON only."
    raise ValueError(f"{agent}: model did not return valid JSON ({last_error})")


def check_lm_studio() -> dict:
    try:
        res = httpx.get(
            config.LM_BASE_URL.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {config.LM_API_KEY}"},
            timeout=3,
        )
        res.raise_for_status()
        return {"ok": True, "models": [m["id"] for m in res.json().get("data", [])]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "models": [], "error": str(exc)[:200]}


def is_connection_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc} {exc.__cause__!r}"
    if "did not return valid JSON" in text:
        return False
    return bool(re.search(r"ConnectError|APIConnectionError|ECONNREFUSED|Connection error|No models loaded|model_not_found|Model .* not found", text))
