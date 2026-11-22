"""Agent registry: the 12 agents from the problem statement, their retrieval allowlists and prompts."""
from .security import DATA_RULE

# id, name, responsibility, retrieval-source allowlist (least privilege), implemented as pipeline stage
AGENTS = [
    ("coordinator", "Coordinator", "Controls the workflow, masks sensitive data, screens prompt injection, assigns tasks.", [], "intake"),
    ("interaction", "Stakeholder Interaction", "Conducts adaptive, role-specific interviews.", ["requirements", "product", "finance"], "interview"),
    ("extraction", "Requirement Extraction", "Extracts structured requirements from conversations and documents.", ["requirements", "user", "finance"], "extract"),
    ("classification", "Classification", "Multi-label classification of functional and non-functional requirements.", [], "classify"),
    ("clarification", "Clarification", "Detects missing or ambiguous information and drafts follow-up questions.", [], "quality"),
    ("conflict", "Conflict Detection", "Identifies contradictions and duplicates.", [], "quality"),
    ("compliance", "Compliance", "Maps requirements to regulations, standards and controls (no final legal determinations).", ["finance", "security", "requirements"], "compliance"),
    ("security", "Security & Privacy", "Identifies cybersecurity and privacy requirements.", ["security", "finance"], "compliance"),
    ("risk", "Risk Analysis", "Assesses business, technical and compliance risk.", ["security", "finance", "requirements"], "risk"),
    ("sdlc", "SDLC Selection", "Scores project factors and recommends a ranked SDLC model.", ["product", "requirements", "security", "finance"], "sdlc"),
    ("documentation", "Documentation", "Generates SRS, user stories, use cases and traceability records.", [], "document"),
    ("validation", "Validation", "Checks completeness, consistency, citations and confidence.", [], "validate"),
    ("approval", "Human Approval", "Routes critical decisions to authorised people.", [], "approval"),
]

SOURCES = {a[0]: a[3] for a in AGENTS}

USE_CASES = {
    "payments": ("Payment processing", "PAY"),
    "digital-banking": ("Digital / mobile banking", "DBK"),
    "loans": ("Loan origination & credit assessment", "LOAN"),
    "fraud": ("Fraud detection", "FRD"),
    "insurance": ("Insurance & investment platforms", "INS"),
    "reporting": ("Regulatory reporting", "REG"),
    "kyc": ("Customer onboarding & KYC", "KYC"),
    "analytics": ("Financial data analytics", "ANL"),
}

CATEGORIES = [
    "business", "stakeholder", "functional", "security", "privacy", "regulatory", "performance",
    "availability", "usability", "data", "integration", "audit", "operational",
]

ROLE_TEMPLATES = {
    "Customer / end user": ["Which tasks do you perform most often, and what slows you down today?", "What would make you trust (or distrust) this service with your money?", "Which devices and channels do you use?"],
    "Business analyst": ["What business objectives and KPIs define success?", "Describe the current workflow end to end, including exceptions.", "What business rules and approval limits apply?"],
    "Product owner": ["What is the MVP scope and what is explicitly out of scope?", "Who are the user roles and what can each do?", "What are the schedule and budget constraints?"],
    "Software architect / developer": ["Which existing systems must we integrate with, and through what interfaces?", "What availability, latency and throughput targets exist?", "What legacy constraints limit design choices?"],
    "Information security": ["What authentication, authorisation and step-up rules are required?", "How is sensitive data classified, encrypted, masked and retained?", "Which threat scenarios worry you most?"],
    "Compliance / legal officer": ["Which jurisdictions and regulations apply?", "What audit, reporting and retention obligations exist?", "Which decisions need formal compliance sign-off?"],
    "Risk management": ["What are the top business and operational risks?", "What transaction limits and risk thresholds apply?", "What is the impact of an outage or incorrect decision?"],
    "Operations": ["How is the service monitored, supported and reconciled?", "What are the incident and escalation procedures?", "What are the maintenance windows and DR expectations?"],
    "Auditor / regulator": ["What evidence must be retained and for how long?", "What audit trails and reports are expected?", "What previous findings must be addressed?"],
}

INTERVIEW_TOPICS = [
    "business objectives", "users and roles", "existing workflow", "inputs, outputs and business rules",
    "exceptional conditions", "data collection and retention", "authentication and authorisation",
    "financial transaction limits", "audit and reporting", "performance and availability",
    "integration with existing systems", "regulatory and security constraints", "schedule and budget",
]


def interview_prompt(role: str, use_case: str) -> str:
    return (
        f"You are the Stakeholder Interaction Agent of a requirements-engineering assistant for a financial institution. "
        f"You are interviewing a stakeholder with the role '{role}' about a '{use_case}' project.\n"
        "Rules:\n"
        "- Ask at most TWO focused questions per turn. Never lecture.\n"
        "- First acknowledge in one short sentence what you learned, then ask.\n"
        "- If an answer is vague, incomplete or inconsistent with earlier answers, ask a precise follow-up (numbers, limits, who/when).\n"
        f"- Over the interview cover: {', '.join(INTERVIEW_TOPICS)}. Prioritise topics most relevant to the role and not yet covered.\n"
        "- Use the evidence only to ask better questions about regulatory/security constraints; cite sources as (path) when you rely on them.\n"
        "- Do NOT make legal determinations. Do NOT invent facts or numbers.\n"
        f"- {DATA_RULE}\n"
        "- Plain text, concise."
    )


EXTRACT_SYSTEM = f"""You are the Requirement Extraction Agent for a financial institution.
Extract atomic, testable requirements from the stakeholder input. Write statements as "The system shall ...".
Use ONLY facts in the input; put any inference in "assumptions". Cite evidence IDs (like "E2") ONLY from the evidence list and only when the evidence really supports the requirement.
"source" must be a short VERBATIM quote from the stakeholder input that the requirement comes from (empty string if none).
Produce 6 to 8 requirements, the most important ones. Be terse: statements under 25 words, "source" under 15 words, at most 2 acceptance criteria (one short line each), at most 1 assumption, empty strings/lists when not needed. {DATA_RULE}
JSON shape:
{{"requirements":[{{"id":"R1","statement":"The system shall ...","source":"verbatim quote","justification":"max 12 words","priority":"MUST|SHOULD|COULD","dependencies":["R2"],"assumptions":["..."],"acceptance":["Given/When/Then or measurable criterion"],"story":"As a <role>, I want <goal>, so that <benefit> (one line)","evidence":["E1"]}}]}}"""

CLASSIFY_SYSTEM = f"""You are the Classification Agent. For each requirement assign ONE OR MORE categories (multi-label) from exactly:
{", ".join(CATEGORIES)}.
Also decide whether it is a functional requirement ("functional": true) or a non-functional/constraint one (false).
JSON shape: {{"items":[{{"id":"R1","categories":["functional","security"],"functional":true}}]}}"""

QUALITY_SYSTEM = f"""You are the Clarification and Conflict-Detection Agents. Review the requirements for:
ambiguity (vague words like fast, secure, user-friendly), incompleteness, inconsistency, duplication, infeasibility, lack of testability, missing source, undefined terminology, missing security/compliance control.
For each defect give a precise clarifying question for the stakeholder. Also list pairs/groups of requirements that conflict or duplicate each other, and important interview topics that are completely missing.
Only report real defects; if a requirement is fine, omit it.
JSON shape: {{"issues":[{{"id":"R1","type":"ambiguity","detail":"...","question":"..."}}],"conflicts":[{{"ids":["R1","R2"],"detail":"..."}}],"missing_topics":["..."]}}"""

COMPLIANCE_SYSTEM = f"""You are the Compliance and Security & Privacy Agents for a financial institution.
Map each requirement to applicable regulations, standards or controls using ONLY the evidence list (cite IDs like "E3"). If the evidence does not support a mapping, set "framework" to "NEEDS-VALIDATION" and describe the gap. Never invent clause numbers or thresholds.
You do NOT make final legal determinations; high-impact interpretations need compliance/legal sign-off ("checkpoint").
Also propose up to 4 additional security or privacy requirements that are missing (ids "N1".."N4"), each with a verbatim-free "statement" and acceptance criteria.
{DATA_RULE}
JSON shape:
{{"mappings":[{{"id":"R1","framework":"RBI KYC Master Direction","control":"what must be implemented","evidence":["E3"],"gap":"","checkpoint":"Compliance officer approval before go-live"}}],
"new_requirements":[{{"id":"N1","statement":"The system shall ...","justification":"...","acceptance":["..."],"evidence":["E4"],"categories":["security"]}}]}}"""

RISK_SYSTEM = f"""You are the Risk-Analysis Agent. Build a risk register (5 to 8 risks) covering business, technical, security and compliance risks for these requirements.
likelihood and impact are each Low, Medium or High. Link each risk to requirement ids and give a concrete mitigation. Also give an overall risk level per requirement.
JSON shape: {{"risks":[{{"description":"...","likelihood":"Medium","impact":"High","mitigation":"...","reqs":["R1"]}}],"requirement_risk":[{{"id":"R1","level":"High"}}]}}"""

FACTOR_SYSTEM = f"""You are the SDLC Selection Agent. From the requirements, risks and project description, score each project factor from 1 to 5 and give a one-sentence reason that cites requirement ids.
Factors:
{{factors}}
{DATA_RULE}
JSON shape: {{"factors":{{"stability":{{"score":3,"reason":"..."}}, ...all ten factors...}}}}"""

WORKFLOW_SYSTEM = f"""You are the SDLC Selection Agent. Customise the chosen SDLC model for this specific financial project.
For EACH phase listed (use the exact phase names) give: activities (2-4), roles (1-3), deliverables (1-3), security activities (1-2, e.g. threat modelling, static analysis, transaction-integrity testing), compliance checkpoints (1-2), entry criterion, exit criterion, and the human approval gate (who signs off) .
Also write a 3-5 sentence "rationale" explaining why this model fits, citing requirement ids and the factor scores, and why the next-ranked alternatives fit less.
{DATA_RULE}
JSON shape: {{"rationale":"...","phases":[{{"name":"<exact phase name>","activities":["..."],"roles":["..."],"deliverables":["..."],"security":["..."],"compliance":["..."],"entry":"...","exit":"...","approval":"..."}}]}}"""

USECASE_SYSTEM = """You are the Documentation Agent. Write 2 or 3 concise use-case descriptions in Markdown for the most important requirements.
For each: "### UC-n: Title", then bullets for Actor, Preconditions, Main flow (numbered), Alternate/exception flows, Postconditions, Related requirements (ids). Use only the given requirements. No preamble."""
