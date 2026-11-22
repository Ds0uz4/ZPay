"""Deterministic SDLC selection engine: factor profiles -> ranked suitability scores.

Models: Waterfall, V-Model, Spiral, RAD, Prototype, Agile (XP), Agile (Scrum), Iterative.
Each model has an "ideal" project profile on 1-5 factor scales; the score is the closeness of the
project's factor vector to that profile (weighted RMS distance mapped to 0-100%).
"""
import math

FACTORS = {
    "stability": "Requirement stability (5 = fixed and fully known)",
    "regulatory": "Regulatory criticality (5 = heavily regulated, formal approvals)",
    "security": "Security / privacy risk (5 = very high)",
    "uncertainty": "Technical / requirement uncertainty (5 = very high)",
    "change_frequency": "Expected frequency of change (5 = constant)",
    "delivery_speed": "Need for fast / continuous delivery (5 = continuous)",
    "verification": "Need for formal verification & documentation (5 = strict)",
    "stakeholder_availability": "Stakeholder availability for collaboration (5 = always available)",
    "failure_consequence": "Consequence of system failure (5 = severe financial / legal)",
    "complexity": "Project complexity and size (5 = very large / complex)",
}

WEIGHTS = {"regulatory": 1.5, "security": 1.5, "failure_consequence": 1.5}

# order: stability, regulatory, security, uncertainty, change, delivery, verification, stakeholder, failure, complexity
_ORDER = list(FACTORS)
_PROFILES = {
    "Waterfall": (5, 4, 3, 1, 1, 1, 4, 2, 3, 2),
    "V-Model": (4, 5, 4, 2, 2, 1, 5, 3, 5, 3),
    "Spiral": (2, 3, 4, 5, 3, 2, 3, 3, 5, 5),
    "RAD": (2, 2, 2, 3, 4, 4, 2, 5, 2, 2),
    "Prototype": (1, 2, 2, 5, 4, 3, 2, 5, 2, 2),
    "Agile (XP)": (1, 2, 3, 4, 5, 5, 3, 5, 3, 3),
    "Agile (Scrum)": (2, 3, 3, 3, 4, 4, 3, 4, 3, 3),
    "Iterative": (3, 4, 4, 3, 3, 3, 4, 3, 4, 4),
}

MODELS = list(_PROFILES)

SUMMARY = {
    "Waterfall": "Sequential phases with sign-off at each stage; best when requirements are stable and approvals are extensive.",
    "V-Model": "Each development phase is paired with a test phase; best for strict verification and validation.",
    "Spiral": "Repeated cycles of objectives, risk analysis, build and review; best for high uncertainty or technical risk.",
    "RAD": "Rapid, component-based builds with heavy user involvement; best for modular systems with engaged users.",
    "Prototype": "Throw-away or evolutionary prototypes validated with users; best when requirements are unclear.",
    "Agile (XP)": "Engineering-practice-driven (TDD, pair programming, CI, small releases); best for rapidly changing requirements.",
    "Agile (Scrum)": "Time-boxed sprints with backlog, review and retrospective; best for evolving requirements with available product owner.",
    "Iterative": "Repeated full mini-lifecycles that grow the system increment by increment; balances change with governance.",
}

# Fixed phase skeletons so generated workflows are grounded; the LLM fills in the details per phase.
PHASES = {
    "Waterfall": ["Requirements", "System Design", "Implementation", "Verification", "Deployment", "Maintenance"],
    "V-Model": ["Requirements Analysis", "System Design", "Architecture Design", "Module Design", "Coding",
                "Unit Testing", "Integration Testing", "System Testing", "Acceptance Testing"],
    "Spiral": ["Determine Objectives", "Identify & Resolve Risks", "Develop & Test", "Plan Next Loop"],
    "RAD": ["Business Modeling", "Data Modeling", "Process Modeling", "Application Generation", "Testing & Turnover"],
    "Prototype": ["Requirements Gathering", "Quick Design", "Build Prototype", "User Evaluation", "Refine Prototype",
                  "Engineer Final Product"],
    "Agile (XP)": ["Planning Game", "Test-Driven Development & Pair Programming", "Continuous Integration",
                   "Refactoring", "Small Release", "Customer Acceptance"],
    "Agile (Scrum)": ["Product Backlog Refinement", "Sprint Planning", "Sprint Execution", "Sprint Review",
                      "Retrospective", "Release"],
    "Iterative": ["Initial Planning", "Requirements (increment)", "Analysis & Design", "Implementation", "Testing",
                  "Evaluation & Next Iteration"],
}

DEFAULT_FACTORS = {k: 3 for k in FACTORS}


def clamp_factors(raw: dict) -> dict[str, int]:
    out = {}
    for key in FACTORS:
        try:
            out[key] = max(1, min(5, round(float(raw.get(key, 3)))))
        except (TypeError, ValueError):
            out[key] = 3
    return out


def rank(factors: dict[str, int]) -> list[dict]:
    weights = [WEIGHTS.get(k, 1.0) for k in _ORDER]
    total_w = sum(weights)
    result = []
    for model, profile in _PROFILES.items():
        msd = sum(w * (factors[k] - p) ** 2 for w, k, p in zip(weights, _ORDER, profile)) / total_w
        result.append({"model": model, "score": round(100 * (1 - math.sqrt(msd) / 4))})
    return sorted(result, key=lambda r: r["score"], reverse=True)


def mermaid(model: str, phases: list[str]) -> str:
    """Flowchart of the chosen SDLC, with the loop/feedback structure of that model."""
    ids = [f"P{i}" for i in range(len(phases))]
    lines = ["flowchart TD"]
    lines += [f'    {i}["{name}"]' for i, name in zip(ids, phases)]
    if model == "V-Model":
        left, right = ids[:4], list(reversed(ids[5:]))
        lines += [f"    {a} --> {b}" for a, b in zip(ids[:4], ids[1:5])]
        lines += [f"    {a} --> {b}" for a, b in zip(ids[4:], ids[5:])]
        for l, r in zip(left, right):
            lines.append(f"    {l} -.verifies.-> {r}")
    else:
        lines += [f"    {a} --> {b}" for a, b in zip(ids, ids[1:])]
        if model in ("Spiral", "Iterative", "Agile (Scrum)", "Agile (XP)"):
            lines.append(f"    {ids[-1]} -->|next cycle| {ids[0]}")
        elif model == "Prototype":
            lines.append(f"    {ids[3]} -->|feedback| {ids[1]}")
            lines.append(f"    {ids[4]} -->|accepted?| {ids[5]}")
        elif model == "RAD":
            lines.append(f"    {ids[-1]} -->|next component| {ids[0]}")
        elif model == "Waterfall":
            lines.append(f"    {ids[-1]} -.change request.-> {ids[0]}")
    lines.append(f"    {ids[-1]} --> GATE{{{{\"Human approval gate\"}}}}")
    return "\n".join(lines)
