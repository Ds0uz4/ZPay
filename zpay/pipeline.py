"""Multi-agent requirements-engineering pipeline built as a LangGraph state graph.

intake -> extract -> classify -> quality -> compliance -> risk -> sdlc -> validate -> document
       -> approval (human-in-the-loop interrupt) -> finalize
"""
import json
import re
import threading
from typing import Annotated, Any, Callable, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from . import agents, rag, sdlc
from . import config as settings
from .llm import ask, ask_json, is_connection_error
from .render import render_srs
from .runs import RUNS, Run
from .security import DATA_RULE, fence, mask_sensitive, screen_injection

SDLC_APPROVERS = ["Project manager", "Architect", "Security team", "Compliance officer"]
LEVEL = {"low": 1, "medium": 2, "high": 3}


# ---------------------------------------------------------------- lenient LLM output models
def _list(value) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (str, int, float)):
        return [str(value)]
    if isinstance(value, dict):
        return [json.dumps(value)]
    return [str(v) for v in value]


def _str(value) -> str:
    return "" if value is None else str(value)


SList = Annotated[list[str], BeforeValidator(_list)]
SStr = Annotated[str, BeforeValidator(_str)]


class Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ReqIn(Lenient):
    id: SStr = ""
    statement: SStr
    source: SStr = ""
    justification: SStr = ""
    priority: SStr = "SHOULD"
    dependencies: SList = []
    assumptions: SList = []
    acceptance: SList = []
    story: SStr = ""
    evidence: SList = []


class ExtractOut(Lenient):
    requirements: list[ReqIn]


class ClassifyItem(Lenient):
    id: SStr
    categories: SList = []
    functional: bool = True


class ClassifyOut(Lenient):
    items: list[ClassifyItem] = []


class IssueIn(Lenient):
    id: SStr = ""
    type: SStr = "ambiguity"
    detail: SStr = ""
    question: SStr = ""


class ConflictIn(Lenient):
    ids: SList = []
    detail: SStr = ""


class QualityOut(Lenient):
    issues: list[IssueIn] = []
    conflicts: list[ConflictIn] = []
    missing_topics: SList = []


class MappingIn(Lenient):
    id: SStr
    framework: SStr = "NEEDS-VALIDATION"
    control: SStr = ""
    evidence: SList = []
    gap: SStr = ""
    checkpoint: SStr = ""


class NewReqIn(Lenient):
    id: SStr = ""
    statement: SStr
    justification: SStr = ""
    acceptance: SList = []
    evidence: SList = []
    categories: SList = []


class ComplianceOut(Lenient):
    mappings: list[MappingIn] = []
    new_requirements: list[NewReqIn] = []


class RiskIn(Lenient):
    description: SStr
    likelihood: SStr = "Medium"
    impact: SStr = "Medium"
    mitigation: SStr = ""
    reqs: SList = []


class ReqRiskIn(Lenient):
    id: SStr
    level: SStr = "Medium"


class RiskOut(Lenient):
    risks: list[RiskIn] = []
    requirement_risk: list[ReqRiskIn] = []


class FactorOut(Lenient):
    factors: dict[str, Any]


class PhaseIn(Lenient):
    name: SStr
    activities: SList = []
    roles: SList = []
    deliverables: SList = []
    security: SList = []
    compliance: SList = []
    entry: SStr = ""
    exit: SStr = ""
    approval: SStr = ""


class WorkflowOut(Lenient):
    rationale: SStr = ""
    phases: list[PhaseIn] = []


# ---------------------------------------------------------------- state & helpers
class State(TypedDict, total=False):
    input: dict
    masked_text: str
    mask_counts: dict
    injection: list
    requirements: list
    conflicts: list
    open_questions: list
    compliance: list
    risks: list
    sdlc: dict
    metrics: dict
    use_cases: str
    decisions: dict
    baseline: str
    warnings: Annotated[list, lambda a, b: (a or []) + (b or [])]


def _run(config: RunnableConfig) -> Run:
    return RUNS[config["configurable"]["run_id"]]


def _code(state: State) -> str:
    return agents.USE_CASES.get(state["input"]["useCase"], ("", "GEN"))[1]


def _label(state: State) -> str:
    return agents.USE_CASES.get(state["input"]["useCase"], (state["input"]["useCase"], ""))[0]


def _req_lines(reqs: list[dict], limit: int = 230) -> str:
    return "\n".join(f"{r['id']} | {r['statement'][:limit]}" for r in reqs)


def _valid_evidence(run: Run, ids: list[str]) -> list[str]:
    out = []
    for raw in ids:
        ev_id = re.sub(r"[^E0-9]", "", raw.upper())
        if run.pool.get(ev_id) and ev_id not in out:
            out.append(ev_id)
    return out


def _overlap(quote: str, text: str) -> float:
    q = rag.tokenize(quote)
    if not q:
        return 0.0
    t = set(rag.tokenize(text))
    return sum(1 for w in q if w in t) / len(q)


def _evidence_block(run: Run, hits: list[dict]) -> str:
    return fence("evidence", rag.format_evidence(run.pool.add(hits)))


def stage(stage_id: str, agent_name: str) -> Callable:
    """Wrap a node: emit progress, audit it, and degrade gracefully on non-connection errors."""

    def decorate(fn: Callable[[State, Run], tuple[dict, str]]):
        def wrapper(state: State, config: RunnableConfig) -> dict:
            import time

            run = _run(config)
            run.emit("stage", id=stage_id, status="running", agent=agent_name)
            started = time.time()
            try:
                update, summary = fn(state, run)
            except Exception as exc:  # noqa: BLE001
                if is_connection_error(exc):
                    raise
                run.audit("stage_error", stage=stage_id, error=str(exc))
                run.emit("stage", id=stage_id, status="warning", agent=agent_name, summary=f"Skipped: {exc}"[:300],
                         ms=int((time.time() - started) * 1000))
                return {"warnings": [f"{agent_name}: {exc}"[:300]]}
            ms = int((time.time() - started) * 1000)
            run.audit("stage_done", stage=stage_id, agent=agent_name, summary=summary, ms=ms)
            run.emit("stage", id=stage_id, status="done", agent=agent_name, summary=summary, ms=ms)
            return update

        return wrapper

    return decorate


# ---------------------------------------------------------------- nodes
@stage("intake", "Coordinator")
def intake(state: State, run: Run):
    inp = state["input"]
    raw = inp["text"] + (f"\n\nReviewer notes: {inp['notes']}" if inp.get("notes") else "")
    screened, findings = screen_injection(raw)
    masked, counts = mask_sensitive(screened)
    run.audit("intake", input_chars=len(raw), masked=counts, injection_findings=findings, masked_text=masked,
              kb={**rag.index_info()}, model=settings.LM_MODEL)
    parts = [f"{sum(counts.values())} sensitive value(s) masked"]
    if findings:
        parts.append(f"{len(findings)} suspected injection phrase(s) removed")
    return {"masked_text": masked, "mask_counts": counts, "injection": findings}, "; ".join(parts)


@stage("extract", "Requirement Extraction")
def extract(state: State, run: Run):
    inp = state["input"]
    hits = rag.search(f"{_label(state)} {state['masked_text'][:1500]}", 6, agents.SOURCES["extraction"])
    user = (
        f"Use case: {_label(state)}. Stakeholder role: {inp['role']}.\n\n"
        f"{_evidence_block(run, hits)}\n\n{fence('stakeholder_input', state['masked_text'])}"
    )
    out = ask_json(agents.EXTRACT_SYSTEM, user, ExtractOut, "extraction", run.llm_log)
    code, reqs, id_map = _code(state), [], {}
    for i, item in enumerate(out.requirements[:10], 1):
        id_map[item.id or f"R{i}"] = f"REQ-{code}-{i:03d}"
    for i, item in enumerate(out.requirements[:10], 1):
        final = id_map[item.id or f"R{i}"]
        valid = _valid_evidence(run, item.evidence)
        issues = []
        if len(valid) < len(item.evidence):
            issues.append({"type": "invalid-citation", "detail": "Model cited evidence that was not retrieved; removed."})
        verified = bool(item.source) and _overlap(item.source, state["masked_text"]) >= 0.7
        if not verified:
            issues.append({"type": "missing-source", "detail": "No verbatim stakeholder quote supports this requirement."})
        reqs.append({
            "id": final, "statement": item.statement.strip(), "source": item.source, "sourceVerified": verified,
            "justification": item.justification, "priority": item.priority.upper()[:6] or "SHOULD",
            "dependencies": [id_map.get(d, d) for d in item.dependencies], "assumptions": item.assumptions,
            "acceptance": item.acceptance, "story": item.story, "categories": ["functional"], "regulations": [],
            "risk": "Medium", "evidence": valid, "confidence": 0.0, "issues": issues, "status": "pending",
            "origin": "stakeholder",
        })
    if not reqs:
        raise ValueError("no requirements could be extracted from the input")
    return {"requirements": reqs}, f"{len(reqs)} requirements extracted, {len(run.pool.all())} evidence passages retrieved"


@stage("classify", "Classification")
def classify(state: State, run: Run):
    reqs = state["requirements"]
    out = ask_json(agents.CLASSIFY_SYSTEM, _req_lines(reqs), ClassifyOut, "classification", run.llm_log)
    by_id = {c.id: c for c in out.items}
    for r in reqs:
        item = by_id.get(r["id"])
        if item:
            cats = [c.lower() for c in item.categories if c.lower() in agents.CATEGORIES]
            r["categories"] = cats or (["functional"] if item.functional else ["operational"])
    multi = sum(1 for r in reqs if len(r["categories"]) > 1)
    return {"requirements": reqs}, f"{len(by_id)} requirements classified ({multi} multi-label)"


@stage("quality", "Clarification & Conflict Detection")
def quality(state: State, run: Run):
    reqs = state["requirements"]
    ids = {r["id"] for r in reqs}
    out = ask_json(agents.QUALITY_SYSTEM, f"Use case: {_label(state)}\n{_req_lines(reqs)}", QualityOut, "clarification", run.llm_log)
    questions, n_issues = [], 0
    for issue in out.issues:
        if issue.id in ids and issue.detail:
            next(r for r in reqs if r["id"] == issue.id)["issues"].append(
                {"type": issue.type, "detail": issue.detail, "question": issue.question}
            )
            n_issues += 1
            if issue.question:
                questions.append({"id": issue.id, "question": issue.question})
    questions += [{"id": "-", "question": f"Missing topic: {t}"} for t in out.missing_topics[:6]]
    conflicts = [{"ids": [i for i in c.ids if i in ids], "detail": c.detail} for c in out.conflicts if c.detail]
    return {"requirements": reqs, "conflicts": conflicts, "open_questions": questions}, (
        f"{n_issues} quality issues, {len(conflicts)} conflicts, {len(questions)} open questions"
    )


@stage("compliance", "Compliance and Security & Privacy")
def compliance(state: State, run: Run):
    reqs = state["requirements"]
    query = f"{_label(state)} regulation control compliance " + " ".join(r["statement"] for r in reqs)[:1200]
    hits = rag.search(query, 8, agents.SOURCES["compliance"])
    hits += rag.search("privacy data protection encryption authentication audit logging", 3, agents.SOURCES["security"])
    user = f"Use case: {_label(state)}\n\n{_evidence_block(run, hits)}\n\nRequirements:\n{_req_lines(reqs)}"
    out = ask_json(agents.COMPLIANCE_SYSTEM, user, ComplianceOut, "compliance", run.llm_log)
    ids = {r["id"] for r in reqs}
    items, unsupported = [], 0
    for m in out.mappings:
        if m.id not in ids:
            continue
        valid = _valid_evidence(run, m.evidence)
        framework, gap = m.framework, m.gap
        if not valid and not framework.upper().startswith("NEEDS-VALIDATION"):
            framework, unsupported = f"NEEDS-VALIDATION (unsupported: {framework})", unsupported + 1
            gap = gap or "No retrieved evidence supports this mapping."
        items.append({"reqId": m.id, "framework": framework, "control": m.control, "evidence": valid,
                      "gap": gap, "checkpoint": m.checkpoint or "Compliance officer review"})
        req = next(r for r in reqs if r["id"] == m.id)
        if valid and framework not in req["regulations"]:
            req["regulations"].append(framework)
    code, added = _code(state), 0
    for n in out.new_requirements[:4]:
        added += 1
        valid = _valid_evidence(run, n.evidence)
        cats = [c.lower() for c in n.categories if c.lower() in agents.CATEGORIES] or ["security"]
        reqs.append({
            "id": f"SEC-{code}-{added:03d}", "statement": n.statement.strip(), "source": "", "sourceVerified": False,
            "justification": n.justification, "priority": "MUST", "dependencies": [], "assumptions": [],
            "acceptance": n.acceptance, "story": "", "categories": cats, "regulations": [],
            "risk": "High", "evidence": valid, "confidence": 0.0,
            "issues": [{"type": "derived", "detail": "Proposed by the Security & Privacy agent; no stakeholder stated it."}],
            "status": "pending", "origin": "derived",
        })
    return {"requirements": reqs, "compliance": items}, (
        f"{len(items)} control mappings ({unsupported} unsupported -> NEEDS-VALIDATION), {added} derived security requirements"
    )


@stage("risk", "Risk Analysis")
def risk(state: State, run: Run):
    reqs = state["requirements"]
    hits = rag.search(f"{_label(state)} threat risk fraud cyber resilience incident", 4, agents.SOURCES["risk"])
    run.pool.add(hits)
    out = ask_json(agents.RISK_SYSTEM, f"Use case: {_label(state)}\n{_req_lines(reqs, 180)}", RiskOut, "risk", run.llm_log)
    ids = {r["id"] for r in reqs}
    register = []
    for i, r in enumerate(out.risks[:8], 1):
        score = LEVEL.get(r.likelihood.lower(), 2) * LEVEL.get(r.impact.lower(), 2)
        register.append({"id": f"RISK-{i:02d}", "description": r.description, "likelihood": r.likelihood.title(),
                         "impact": r.impact.title(), "level": "High" if score >= 6 else "Medium" if score >= 3 else "Low",
                         "mitigation": r.mitigation, "reqs": [x for x in r.reqs if x in ids]})
    lookup = {x.id: x.level.title() for x in out.requirement_risk}
    for req in reqs:
        linked = [LEVEL[k["level"].lower()] for k in register if req["id"] in k["reqs"]]
        level = lookup.get(req["id"]) or (["Low", "Medium", "High"][max(linked) - 1] if linked else req["risk"])
        req["risk"] = level if level.lower() in LEVEL else "Medium"
    return {"requirements": reqs, "risks": register}, f"{len(register)} risks registered"


@stage("sdlc", "SDLC Selection")
def select_sdlc(state: State, run: Run):
    reqs = state["requirements"]
    hits = rag.search(
        "software development life cycle selection waterfall v-model spiral agile iterative prototype regulated secure SDLC",
        5, agents.SOURCES["sdlc"],
    )
    evidence = _evidence_block(run, hits)
    factor_help = "\n".join(f"- {k}: {v}" for k, v in sdlc.FACTORS.items())
    summary_text = f"Use case: {_label(state)}\nRequirements:\n{_req_lines(reqs, 160)}\nRisks:\n" + "\n".join(
        f"{k['id']} {k['level']}: {k['description'][:120]}" for k in state.get("risks", [])
    )
    out = ask_json(agents.FACTOR_SYSTEM.replace("{factors}", factor_help),
                   f"{evidence}\n\n{fence('stakeholder_input', state['masked_text'][:1500])}\n\n{summary_text}",
                   FactorOut, "sdlc-factors", run.llm_log)
    raw, notes = {}, {}
    for key in sdlc.FACTORS:
        val = out.factors.get(key, 3)
        if isinstance(val, dict):
            raw[key], notes[key] = val.get("score", 3), str(val.get("reason", ""))
        else:
            raw[key], notes[key] = val, ""
    factors = sdlc.clamp_factors(raw)
    ranking = sdlc.rank(factors)
    chosen = ranking[0]["model"]
    result = {"factors": factors, "factorNotes": notes, "ranking": ranking, "chosen": chosen,
              "rationale": sdlc.SUMMARY[chosen], "phases": [], "approvals": {r: False for r in SDLC_APPROVERS},
              "evidence": [e.id for e in run.pool.add(hits)]}
    run.audit("sdlc_ranking", factors=factors, ranking=ranking)
    try:
        phases = sdlc.PHASES[chosen]
        user = (
            f"{evidence}\n\nChosen SDLC: {chosen}\nPhases (use exactly these names): {json.dumps(phases)}\n"
            f"Factor scores: {json.dumps(factors)}\nRanking: {json.dumps(ranking[:4])}\n"
            f"Project:\n{summary_text}"
        )
        wf = ask_json(agents.WORKFLOW_SYSTEM, user, WorkflowOut, "sdlc-workflow", run.llm_log)
        result["rationale"] = wf.rationale or result["rationale"]
        by_name = {p.name.lower(): p for p in wf.phases}
        for idx, name in enumerate(phases):
            p = by_name.get(name.lower()) or (wf.phases[idx] if idx < len(wf.phases) else PhaseIn(name=name))
            result["phases"].append({**p.model_dump(), "name": name})
    except Exception as exc:  # noqa: BLE001
        if is_connection_error(exc):
            raise
        run.audit("stage_error", stage="sdlc-workflow", error=str(exc))
        result["phases"] = [PhaseIn(name=n).model_dump() for n in sdlc.PHASES[chosen]]
        result["rationale"] += " (Detailed workflow generation failed; phase skeleton only.)"
    result["mermaid"] = sdlc.mermaid(chosen, sdlc.PHASES[chosen])
    return {"sdlc": result}, f"Recommended {chosen} ({ranking[0]['score']}%), runner-up {ranking[1]['model']} ({ranking[1]['score']}%)"


@stage("validate", "Validation")
def validate(state: State, run: Run):
    reqs = state["requirements"]
    mapped = {c["reqId"] for c in state.get("compliance", []) if c["evidence"]}
    needs_review = 0
    for r in reqs:
        best = max([run.pool.get(e).confidence for e in r["evidence"]] or [0.0])
        open_issues = sum(1 for i in r["issues"] if i["type"] != "derived")
        conf = 0.30 + 0.35 * min(1.0, best * 2) + (0.15 if r["acceptance"] else 0) \
            + (0.15 if r["sourceVerified"] else 0) - 0.08 * min(open_issues, 3)
        if r["id"] in mapped:
            conf += 0.05
        r["confidence"] = round(max(0.05, min(0.98, conf)), 2)
        regulated = any(c in r["categories"] for c in ("regulatory", "security", "privacy"))
        if r["confidence"] < 0.6 or (regulated and not r["evidence"] and r["id"] not in mapped):
            r["status"] = "needs-review"
            needs_review += 1
    n = len(reqs) or 1
    metrics = {
        "requirements": len(reqs),
        "citation_coverage": round(100 * sum(1 for r in reqs if r["evidence"]) / n),
        "acceptance_coverage": round(100 * sum(1 for r in reqs if r["acceptance"]) / n),
        "regulatory_mapping_coverage": round(100 * sum(1 for r in reqs if r["id"] in mapped) / n),
        "source_verified": round(100 * sum(1 for r in reqs if r["sourceVerified"]) / n),
        "traceability_coverage": round(100 * sum(
            1 for r in reqs if (r["sourceVerified"] or r["origin"] == "derived") and (r["evidence"] or r["id"] in mapped)) / n),
        "avg_confidence": round(sum(r["confidence"] for r in reqs) / n, 2),
        "needs_review": needs_review,
        "open_issues": sum(len(r["issues"]) for r in reqs),
    }
    return {"requirements": reqs, "metrics": metrics}, (
        f"avg confidence {metrics['avg_confidence']}, {needs_review} escalated for human review, "
        f"traceability {metrics['traceability_coverage']}%"
    )


@stage("document", "Documentation")
def document(state: State, run: Run):
    reqs = [r for r in state["requirements"] if r["origin"] == "stakeholder"][:6]
    use_cases = ""
    try:
        use_cases = ask(agents.USECASE_SYSTEM, _req_lines(reqs, 300))
        run.llm_log("documentation", agents.USECASE_SYSTEM, _req_lines(reqs, 300), use_cases)
    except Exception as exc:  # noqa: BLE001
        if is_connection_error(exc):
            raise
    return {"use_cases": use_cases}, "SRS, user stories, use cases, compliance matrix, RTM and risk register assembled"


def approval(state: State, config: RunnableConfig) -> dict:
    decisions = interrupt({"kind": "baseline_approval"})
    return {"decisions": decisions}


def build_bundle(run: Run, state: State) -> dict:
    sd = state.get("sdlc")
    bundle = {
        "id": run.id, "status": run.status, "input": state.get("input", run.input), "model": settings.LM_MODEL,
        "kb": rag.index_info(), "mask": state.get("mask_counts", {}), "injection": state.get("injection", []),
        "requirements": state.get("requirements", []), "conflicts": state.get("conflicts", []),
        "openQuestions": state.get("open_questions", []), "compliance": state.get("compliance", []),
        "risks": state.get("risks", []), "sdlc": sd, "metrics": state.get("metrics", {}),
        "useCases": state.get("use_cases", ""), "warnings": state.get("warnings", []),
        "baseline": state.get("baseline", "DRAFT - awaiting human approval"),
        "decisions": state.get("decisions"), "evidence": [e.to_dict() for e in run.pool.all()],
    }
    bundle["srs"] = render_srs(bundle)
    return bundle


def finalize(state: State, config: RunnableConfig) -> dict:
    run = _run(config)
    d = state.get("decisions") or {}
    reqs, rejected = state["requirements"], 0
    for r in reqs:
        dec = d.get("requirements", {}).get(r["id"])
        if not dec:
            continue
        action = dec.get("action")
        if action == "approve":
            r["status"] = "approved"
        elif action == "reject":
            r["status"], rejected = "rejected", rejected + 1
        elif action == "modify" and dec.get("statement"):
            r["statement"], r["status"] = dec["statement"].strip(), "modified"
        r["reviewerNote"] = dec.get("note", "")
    sd = dict(state["sdlc"]) if state.get("sdlc") else None
    if sd:
        sd["approvals"] = {role: bool(d.get("sdlc", {}).get(role)) for role in SDLC_APPROVERS}
    live = [r for r in reqs if r["status"] != "rejected"]
    reqs_ok = bool(live) and all(r["status"] in ("approved", "modified") for r in live)
    sdlc_ok = bool(sd) and all(sd["approvals"].values())
    reg_needed = any(r["regulations"] for r in live)
    baseline = "BASELINED" if reqs_ok and sdlc_ok and (d.get("regulatoryAck") or not reg_needed) else \
        "DRAFT - approvals incomplete (all requirements, the SDLC choice by 4 roles, and regulatory acknowledgement are required)"
    update = {"requirements": reqs, "sdlc": sd, "baseline": baseline}
    run.audit("human_decision", reviewer=d.get("reviewer", "unknown"), decisions=d, baseline=baseline)
    run.emit("stage", id="finalize", status="done", agent="Human Approval", summary=baseline, ms=0)
    run.status = "complete"
    bundle = build_bundle(run, {**state, **update})
    (run.dir / "SRS.md").write_text(bundle["srs"], encoding="utf-8")
    (run.dir / "bundle.json").write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
    return update


def _build():
    g = StateGraph(State)
    order = [("intake", intake), ("extract", extract), ("classify", classify), ("quality", quality),
             ("compliance", compliance), ("risk", risk), ("sdlc", select_sdlc), ("validate", validate),
             ("document", document), ("approval", approval), ("finalize", finalize)]
    for name, fn in order:
        g.add_node(name, fn)
    g.add_edge(START, order[0][0])
    for (a, _), (b, _) in zip(order, order[1:]):
        g.add_edge(a, b)
    g.add_edge("finalize", END)
    return g.compile(checkpointer=MemorySaver())


GRAPH = _build()


def _cfg(run: Run) -> RunnableConfig:
    return {"configurable": {"thread_id": run.id, "run_id": run.id}}


def _execute(run: Run, payload) -> None:
    try:
        for _ in GRAPH.stream(payload, _cfg(run), stream_mode="updates"):
            pass
        if GRAPH.get_state(_cfg(run)).next:
            run.status = "awaiting_approval"
            run.audit("awaiting_approval")
            run.emit("approval_required")
        else:
            run.status = "complete"
            run.emit("complete")
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        hint = " Is LM Studio running with a model loaded and its server started?" if is_connection_error(exc) else ""
        run.audit("run_failed", error=str(exc))
        run.emit("error", message=f"{str(exc)[:300]}{hint}")


def start_run(run_input: dict) -> Run:
    run = Run(run_input)
    RUNS[run.id] = run
    run.audit("run_started", input={k: v for k, v in run_input.items() if k != "text"}, input_chars=len(run_input["text"]))
    threading.Thread(target=_execute, args=(run, {"input": run_input}), daemon=True).start()
    return run


def resume_run(run: Run, decisions: dict) -> None:
    run.status = "running"
    run.emit("stage", id="approval", status="done", agent="Human Approval", summary="Decisions submitted", ms=0)
    threading.Thread(target=_execute, args=(run, Command(resume=decisions)), daemon=True).start()


def current_bundle(run: Run) -> dict:
    values = GRAPH.get_state(_cfg(run)).values or {"input": run.input}
    return build_bundle(run, values)
