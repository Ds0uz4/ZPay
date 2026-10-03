# ZPay - Payment Processing Systems

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Node.js](https://img.shields.io/badge/Node.js-%3E%3D22.13-339933?logo=node.js&logoColor=white)](https://nodejs.org/)
[![Mastra](https://img.shields.io/badge/Built%20with-Mastra-6366f1)](https://mastra.ai)
[![LM Studio](https://img.shields.io/badge/Inference-LM%20Studio-0ea5e9)](https://lmstudio.ai)
[![TypeScript](https://img.shields.io/badge/TypeScript-6.x-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)

**ZPay** is an AI-powered payment processing systems analyzer. It provides intelligent analysis for payment processing scenarios in the finance sector, covering requirements, security, compliance, and architecture.

---

## Overview

ZPay is built for finance professionals and engineers who need an AI assistant that thinks in tradeoffs, not templates. It combines a local language model, document retrieval, persistent working memory, and a web-based interface into a single system you control end to end.

| Capability | What it does |
| --- | --- |
| **Payment Processing Analysis** | Analyzes payment systems with focus on security, compliance (PCI DSS, RBI), and architecture |
| **Requirements Engineering** | Identifies and lists software requirements for finance scenarios |
| **SDLC Selection** | Picks and justifies software development lifecycles for specifications |
| **Document RAG** | Indexes `docs/` on startup and cites source files in answers |
| **Persistent memory** | Tracks requirements, decisions, and open questions per thread |
| **Extensible skills** | Drop-in `SKILL.md` files extend behavior without code changes |

## Available Agents

| Studio entry | Role |
| --- | --- |
| **Payment Processing Agent** | Analyzes payment processing systems in the finance sector, covering requirements, security, compliance, and architecture |
| **Requirements Agent** | Identifies and lists software requirements for finance scenarios |
| **SDLC Selection Agent** | Identifies a suitable SDLC for completed requirements specifications |
| **requirements-then-sdlc** (Workflows tab) | Runs Requirements Agent then SDLC Selection Agent and concatenates the documents |
| **payment-processing-analysis** (Workflows tab) | Runs Payment Processing Agent for comprehensive payment system analysis |

Start with `npm run dev`. In Studio open **Workflows → payment-processing-analysis** and paste your payment processing scenario. When it finishes, open `artifacts/evaluation/payment-analysis.md` (Cmd+Shift+V) or `payment-analysis.html` in a browser.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Interface                              │
│                  Mastra Studio (local)                          │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                    Mastra Agents                                │
│   Instructions · Working memory · Context processors            │
└──────┬──────────────────┬──────────────────┬────────────────────┘
       │                  │                  │
       ▼                  ▼                  ▼
┌─────────────┐   ┌───────────────┐   ┌──────────────────┐
│  LM Studio  │   │  LibSQL Store │   │  Workspace RAG   │
│  Chat model │   │  Session mem  │   │  docs/ + skills/ │
│  Embeddings │   │  Thread state │   │  Vector search   │
└─────────────┘   └───────────────┘   └──────────────────┘
```

### Components

| Layer | Technology | Role |
| --- | --- | --- |
| **Agent runtime** | [Mastra](https://mastra.ai) | Orchestrates agents, memory, workspace, and workflows |
| **Inference** | [LM Studio](https://lmstudio.ai) | OpenAI-compatible local chat model |
| **Session storage** | LibSQL (`architect.db`) | Conversation history and working memory |
| **Document search** | Mastra BM25 | Fast local retrieval over indexed source text |
| **Knowledge base** | `docs/ingested/` | Original, provenance-tracked publisher material |
| **Skills** | `skills/<name>/SKILL.md` | Optional domain playbooks loaded on demand |

---

## How It Works

1. **Startup** — Mastra boots the agents, connects to LM Studio, and BM25-indexes searchable text, Markdown, and YAML under `docs/ingested/`.
2. **Query** — Each request BM25-searches the workspace (topK 5) in code and attaches the passages before the model writes.
3. **Reasoning** — The model applies architecture-focused instructions: fill gaps with labeled assumptions, separate facts from guesses, and prefer the smallest reliable design.
4. **Memory** — Working memory persists project context, confirmed requirements, and decisions per thread.
5. **Delivery** — Replies stream to Mastra Studio. Source files are cited when RAG contributed to the answer.

---

## Quick Start

### Prerequisites

- **Node.js** ≥ 22.13
- **LM Studio** — [Download](https://lmstudio.ai/download)

### 1. Install LM Studio

Download and install LM Studio for your platform. Open the app and start the local server (default: `http://127.0.0.1:1234`).

### 2. Download models

Load these models in LM Studio before starting ZPay:

| Model | Purpose | Default identifier |
| --- | --- | --- |
| Chat | Architecture reasoning | `qwen/qwen3.5-9b` |

### 3. Configure environment

```bash
git clone https://github.com/AppajiDheeraj/ZPay.git
cd ZPay
npm install
cp .env.example .env
```

Edit `.env` with your values:

```bash
# LM Studio
LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1
LM_STUDIO_API_KEY=lm-studio
LM_STUDIO_MODEL=qwen/qwen3.5-9b

# Storage (defaults work for local development)
MASTRA_DATABASE_URL=file:./architect.db
```

### 4. Add knowledge

Add source originals and mechanically extracted `.txt`, `.md`, or `.yaml` files under `docs/ingested/`, then update `docs/CORPUS_SOURCES.md` and `docs/CORPUS_SHA256.txt`.

### 5. Add skills (optional)

Create `skills/<skill-name>/SKILL.md` with valid `name` and `description` frontmatter. The description tells the model when to activate the skill. Skills are discovered automatically — no code changes required.

### 6. Run

```bash
npm run dev
```

- **Mastra Studio** — Available at the local dev URL printed in the terminal.

### 7. Verify

```bash
npm run check
```

Runs TypeScript checks and a production build.

---

## Project Structure

```
ZPay/
├── docs/                  # Knowledge base (auto-indexed; add your own .md files)
├── skills/                # Skill definitions (SKILL.md)
├── src/mastra/
│   ├── architect-agent.ts # General architecture agent
│   ├── finance-agents.ts  # Requirements, SDLC, and Payment Processing agents
│   ├── prompts.ts         # System prompts for all agents
│   ├── config.ts          # Configuration
│   ├── lm-studio.ts       # LM Studio integration
│   ├── rag.ts             # BM25 retrieve + inject evidence
│   ├── workflow.ts        # Workflows for multi-agent pipelines
│   ├── workspace.ts       # Workspace configuration
│   └── index.ts           # Mastra entry point
├── .env.example
└── package.json
```

---

## Usage Examples

### Payment Processing Analysis

**Via Mastra Studio:**
1. Start LM Studio and load the model
2. Run `npm run dev`
3. Open Mastra Studio at the local URL
4. Navigate to **Workflows → payment-processing-analysis**
5. Enter your scenario, for example:
   ```
   Design a payment processing system for an e-commerce platform in India that needs to handle:
   - Multiple payment methods: UPI, credit/debit cards, net banking, and wallets
   - 50,000 transactions per day
   - Compliance with RBI guidelines and PCI DSS
   - Integration with Razorpay payment gateway
   - Real-time fraud detection
   - Automatic reconciliation with bank statements
   ```
6. Run the workflow
7. View the output in `artifacts/evaluation/payment-analysis.md` or `payment-analysis.html`

**Programmatically:**
```typescript
import { runPaymentProcessingAnalysis } from './src/mastra/workflow.js';

const result = await runPaymentProcessingAnalysis('Your payment processing scenario here');
console.log(result.analysis);
console.log('Markdown saved to:', result.markdownPath);
console.log('HTML saved to:', result.htmlPath);
```

### Requirements Analysis

Use the **requirements-then-sdlc** workflow to generate requirements and select an SDLC for finance scenarios.

---

## Scripts

| Command | Description |
| --- | --- |
| `npm run dev` | Start Mastra in development mode |
| `npm run build` | Production build |
| `npm run start` | Run the production server |
| `npm run typecheck` | TypeScript validation |
| `npm run check` | Typecheck + build |

---

## Deployment Notes

The default configuration is optimized for local development. For a shared or production deployment:

- Replace local LibSQL file paths with a managed database
- Point inference at a hosted OpenAI-compatible endpoint instead of LM Studio
- Set appropriate environment variables for your infrastructure

---

## License

MIT — see [LICENSE](LICENSE).
