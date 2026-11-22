"""FastAPI server: JSON/SSE API plus the static web UI."""
import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agents, config, rag, sdlc
from .llm import check_lm_studio, is_connection_error, stream_chat
from .pipeline import current_bundle, resume_run, start_run
from .runs import RUNS
from .security import DATA_RULE, fence, mask_sensitive, screen_injection

_index: dict = {}
_health_cache: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    _index.update(await asyncio.to_thread(rag.build_index))
    print(f"RAG index ready: {_index['files']} files, {_index['chunks']} passages")
    yield


app = FastAPI(title="ZPay Requirements Engineering Assistant", lifespan=lifespan)


class RunRequest(BaseModel):
    project: str = Field("", max_length=200)
    useCase: str = "payments"
    role: str = "Business analyst"
    text: str = Field(min_length=20, max_length=40000)
    notes: str = Field("", max_length=4000)


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class InterviewRequest(BaseModel):
    role: str = "Business analyst"
    useCase: str = "payments"
    history: list[Turn] = Field(min_length=1, max_length=40)


class Decision(BaseModel):
    action: Literal["approve", "reject", "modify"]
    statement: str = ""
    note: str = ""


class ApprovalRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=120)
    requirements: dict[str, Decision] = {}
    sdlc: dict[str, bool] = {}
    regulatoryAck: bool = False


def _run(run_id: str):
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "unknown run")
    return run


@app.get("/api/health")
async def health():
    now = time.time()
    if now - _health_cache.get("at", 0) > 60:  # cache so LM Studio's log isn't flooded
        _health_cache.update(at=now, lm=await asyncio.to_thread(check_lm_studio))
    lm = _health_cache["lm"]
    model_loaded = config.LM_MODEL in lm["models"]
    return {"lmStudio": lm, "configuredModel": config.LM_MODEL, "modelAvailable": model_loaded,
            "baseURL": config.LM_BASE_URL, "kb": rag.index_info()}


@app.get("/api/meta")
async def meta():
    return {
        "useCases": [{"id": k, "label": v[0]} for k, v in agents.USE_CASES.items()],
        "roles": agents.ROLE_TEMPLATES,
        "topics": agents.INTERVIEW_TOPICS,
        "agents": [{"id": a[0], "name": a[1], "responsibility": a[2], "sources": a[3], "stage": a[4]} for a in agents.AGENTS],
        "sdlcModels": [{"model": m, "summary": sdlc.SUMMARY[m], "phases": sdlc.PHASES[m]} for m in sdlc.MODELS],
        "factors": sdlc.FACTORS,
        "approvers": ["Project manager", "Architect", "Security team", "Compliance officer"],
    }


@app.get("/api/kb/search")
async def kb_search(q: str, k: int = 6):
    hits = await asyncio.to_thread(rag.search, q[:500], max(1, min(k, 12)))
    return [{k_: v for k_, v in h.items() if k_ != "key"} | {"text": h["text"][:900]} for h in hits]


@app.post("/api/runs")
async def create_run(req: RunRequest):
    return {"id": start_run(req.model_dump()).id}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    return await asyncio.to_thread(current_bundle, _run(run_id))


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, after: int = 0):
    run = _run(run_id)

    async def gen():
        sent = max(0, after)
        while True:
            batch = run.events[sent:]
            for event in batch:
                yield f"data: {json.dumps(event)}\n\n"
            sent += len(batch)
            if batch and batch[-1]["type"] in ("complete", "error", "approval_required"):
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/runs/{run_id}/approve")
async def approve(run_id: str, req: ApprovalRequest):
    run = _run(run_id)
    if run.status != "awaiting_approval":
        raise HTTPException(409, f"run is {run.status}, not awaiting approval")
    resume_run(run, req.model_dump())
    return {"ok": True}


@app.get("/api/runs/{run_id}/audit")
async def get_audit(run_id: str, full: bool = False):
    records = _run(run_id).read_audit()
    if not full:
        for r in records:
            for key in ("system", "prompt", "output", "masked_text"):
                if key in r:
                    r[key] = str(r[key])[:600]
    return records


@app.get("/api/runs/{run_id}/srs.md")
async def download_srs(run_id: str):
    bundle = await asyncio.to_thread(current_bundle, _run(run_id))
    return PlainTextResponse(bundle["srs"], headers={"Content-Disposition": f'attachment; filename="SRS-{run_id}.md"'})


@app.post("/api/interview")
async def interview(req: InterviewRequest):
    """Adaptive stakeholder interview: RAG-grounded, streamed over SSE."""
    label = agents.USE_CASES.get(req.useCase, (req.useCase, ""))[0]
    history = []
    for turn in req.history:
        text = turn.content
        if turn.role == "user":
            text, _ = screen_injection(text)
            text, _ = mask_sensitive(text)
        history.append({"role": turn.role, "content": text})
    last_user = next((t["content"] for t in reversed(history) if t["role"] == "user"), "")
    hits = rag.search(f"{label} {last_user}", 4, agents.SOURCES["interaction"])
    evidence = "\n".join(f"({h['source']}) {h['text'][:400].strip()}" for h in hits) or "(none)"
    system = f"{agents.interview_prompt(req.role, label)}\n\n{fence('evidence', evidence)}"

    def tokens():
        try:
            for piece in stream_chat(system, history):
                yield f"data: {json.dumps({'token': piece})}\n\n"
            yield f"data: {json.dumps({'done': True, 'sources': sorted({h['source'] for h in hits})})}\n\n"
        except Exception as exc:  # noqa: BLE001
            hint = " Is LM Studio running with a model loaded?" if is_connection_error(exc) else ""
            yield f"data: {json.dumps({'error': str(exc)[:200] + hint})}\n\n"

    return StreamingResponse(tokens(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/")
async def index():
    return FileResponse(config.WEB_DIR / "index.html")


app.mount("/", StaticFiles(directory=config.WEB_DIR), name="web")
