"""Render the full requirement artefact set (SRS, stories, matrices, register, SDLC) as Markdown."""
from datetime import datetime, timezone


def _cell(text) -> str:
    return str(text if text not in (None, "") else "-").replace("|", "\\|").replace("\n", " ")


def _table(headers: list[str], rows: list[list]) -> str:
    if not rows:
        return "_None._\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return "\n".join(out) + "\n"


def render_srs(b: dict) -> str:
    inp, reqs = b["input"], b["requirements"]
    ev = {e["id"]: e for e in b["evidence"]}
    cite = lambda ids: ", ".join(f"{i} ({ev[i]['source']})" if i in ev else i for i in ids)  # noqa: E731
    m = b.get("metrics") or {}
    lines = [
        f"# Software Requirements Specification - {inp.get('project') or 'Untitled project'}",
        "",
        f"- **Run:** `{b['id']}`  |  **Generated:** {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}  |  **Model:** `{b['model']}`",
        f"- **Use case:** {inp.get('useCase')}  |  **Stakeholder role:** {inp.get('role')}",
        f"- **Knowledge base:** {b['kb'].get('chunks', 0)} passages, SHA-256 `{(b['kb'].get('hash') or '')[:16]}`",
        f"- **Baseline status:** **{b['baseline']}**",
        f"- **Sensitive data masked before LLM:** {sum(b['mask'].values())} value(s) {b['mask'] or ''}",
        "",
        "> AI-generated draft. Regulatory interpretation, requirement approval and SDLC adoption remain the "
        "responsibility of authorised human stakeholders.",
        "",
        "## 1. Requirements",
        _table(
            ["ID", "Statement", "Categories", "Priority", "Risk", "Confidence", "Status", "Origin"],
            [[r["id"], r["statement"], ", ".join(r["categories"]), r["priority"], r["risk"], r["confidence"],
              r["status"], r["origin"]] for r in reqs],
        ),
        "## 2. User stories and acceptance criteria",
    ]
    for r in reqs:
        lines.append(f"### {r['id']}")
        if r["story"]:
            lines.append(f"*{r['story']}*\n")
        lines += [f"- {a}" for a in r["acceptance"]] or ["- _No acceptance criteria._"]
        lines.append("")
    lines += ["## 3. Use cases", b.get("useCases") or "_Not generated._", "", "## 4. Compliance-control matrix"]
    lines.append(_table(
        ["Req", "Framework / standard", "Control", "Evidence", "Gap", "Approval checkpoint"],
        [[c["reqId"], c["framework"], c["control"], cite(c["evidence"]), c["gap"], c["checkpoint"]] for c in b["compliance"]],
    ))
    lines += ["## 5. Risk register", _table(
        ["ID", "Risk", "Likelihood", "Impact", "Level", "Mitigation", "Requirements"],
        [[k["id"], k["description"], k["likelihood"], k["impact"], k["level"], k["mitigation"], ", ".join(k["reqs"])]
         for k in b["risks"]],
    )]
    lines += ["## 6. Requirements traceability matrix", _table(
        ["Req", "Stakeholder source (verbatim)", "Verified", "Evidence", "Controls", "Acceptance criteria", "Status"],
        [[r["id"], r["source"] or ("(derived by agent)" if r["origin"] == "derived" else ""),
          "yes" if r["sourceVerified"] else "no", cite(r["evidence"]), "; ".join(r["regulations"]),
          len(r["acceptance"]), r["status"]] for r in reqs],
    )]
    lines += ["## 7. Assumptions and dependencies", _table(
        ["Req", "Assumptions", "Dependencies"],
        [[r["id"], "; ".join(r["assumptions"]), ", ".join(r["dependencies"])] for r in reqs if r["assumptions"] or r["dependencies"]],
    )]
    lines.append("## 8. Open issues and clarification questions")
    rows = [[r["id"], i["type"], i["detail"], i.get("question", "")] for r in reqs for i in r["issues"]]
    lines.append(_table(["Req", "Type", "Detail", "Question"], rows))
    for c in b["conflicts"]:
        lines.append(f"- **Conflict** ({', '.join(c['ids'])}): {c['detail']}")
    lines += [f"- **Open question** ({q['id']}): {q['question']}" for q in b["openQuestions"]]
    lines += ["", "## 9. SDLC recommendation"]
    sd = b.get("sdlc")
    if sd:
        lines += [f"**Recommended: {sd['chosen']}**\n", sd["rationale"], "", "### Ranked suitability",
                  _table(["Rank", "Model", "Score"], [[i + 1, r["model"], f"{r['score']}%"] for i, r in enumerate(sd["ranking"])]),
                  "### Decision factors",
                  _table(["Factor", "Score (1-5)", "Reason"], [[k, v, sd["factorNotes"].get(k, "")] for k, v in sd["factors"].items()]),
                  "### Workflow", "```mermaid", sd["mermaid"], "```", ""]
        for p in sd["phases"]:
            lines += [f"#### {p['name']}",
                      f"- **Activities:** {'; '.join(p['activities']) or '-'}",
                      f"- **Roles:** {', '.join(p['roles']) or '-'}",
                      f"- **Deliverables:** {'; '.join(p['deliverables']) or '-'}",
                      f"- **Security:** {'; '.join(p['security']) or '-'}",
                      f"- **Compliance checkpoints:** {'; '.join(p['compliance']) or '-'}",
                      f"- **Entry / exit:** {p['entry'] or '-'} / {p['exit'] or '-'}",
                      f"- **Human approval gate:** {p['approval'] or '-'}", ""]
        lines.append("**SDLC approvals:** " + ", ".join(f"{r}: {'yes' if ok else 'pending'}" for r, ok in sd["approvals"].items()))
    lines += ["", "## 10. Quality metrics", _table(["Metric", "Value"], [[k.replace("_", " "), v] for k, v in m.items()])]
    lines += ["## 11. Evidence cited", _table(
        ["ID", "Source", "Retrieval confidence"], [[e["id"], e["source"], e["confidence"]] for e in b["evidence"]]
    )]
    if b["warnings"]:
        lines += ["## 12. Warnings"] + [f"- {w}" for w in b["warnings"]]
    return "\n".join(lines) + "\n"
