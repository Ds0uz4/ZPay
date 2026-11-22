# ZPay - Agentic Requirements Engineering for Financial Services

A multi-agent assistant that gathers and analyses requirements for financial systems, grounds them in a local knowledge base (RAG), recommends an SDLC model and produces an audited SRS, with human approval gates. It runs on a local model through **LM Studio**.

- **Orchestration:** [LangGraph](https://langchain-ai.github.io/langgraph/) (Python) - the replacement for Mastra
- **LLM:** LM Studio OpenAI-compatible server, configured in `.env`
- **RAG:** BM25 over `docs/ingested/` (RBI, NIST, OWASP, ISO 20022, Open Banking, NASA, ...), with citations and confidence scores
- **SDLC models scored:** Waterfall, V-Model, Spiral, RAD, Prototype, Agile (XP), Agile (Scrum), Iterative
- **UI:** simple web app (Analyze, Interview, Knowledge base, Agents)

Architecture, flowcharts and the Mastra-to-LangGraph mapping: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Run it

1. In LM Studio, load a chat model and start the **Local Server** (default `http://127.0.0.1:1234`).
2. Configure the connection:

   ```bash
   cp .env.example .env     # then edit LM_STUDIO_MODEL to the model identifier you loaded
   ```

3. Install and start (Python 3.11+):

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   python main.py
   ```

4. Open <http://127.0.0.1:8000>. The top-right badge shows whether LM Studio and the configured model are reachable.

## Using it

- **Analyze:** paste stakeholder input (or click *Load sample*), pick the use case and role, run. Watch the agent pipeline, then review requirements, compliance mappings, risks, the ranked SDLC recommendation with workflow diagram, evidence, the generated SRS and the audit trail. Accept/edit/reject each requirement, have the four roles approve the SDLC, and submit to create the baseline.
- **Interview:** adaptive, role-specific interview (streamed). *Send transcript to Analyze* feeds the answers into the pipeline.
- **Knowledge base:** search the indexed corpus and see BM25 scores.

Outputs are written to `artifacts/runs/<run-id>/` (`SRS.md`, `bundle.json`, `audit.jsonl`).

## Notes

- Small local models can return malformed JSON; ZPay retries once, and if a stage still fails the run continues with a warning. Larger models give noticeably better results.
- Compliance output is advisory and never a legal determination; unsupported mappings are marked `NEEDS-VALIDATION`.
- RBAC/MFA/encryption-at-rest are not part of this local prototype (see the security table in the architecture doc).
- Add knowledge by dropping `.txt`/`.md`/`.yaml` files under `docs/ingested/<finance|product|requirements|security|user>/` and restarting.
- The previous Mastra implementation is in git history.

MIT licensed.
