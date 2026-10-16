# 生态Agent (Environment Agent)

> A **desktop-grade, domain-specialized agent workspace for the eco-environment industry** — not just a Q&A bot, but a private, local-first agent that runs the whole workflow (look up standards → crunch data → write reports → review reports → crystallize knowledge → scheduled jobs) with consistent, traceable methodology.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey.svg)

**English** | [简体中文](README.zh-CN.md)

---

## Table of Contents

- [Why this exists](#why-this-exists)
- [Core capabilities](#core-capabilities)
- [Self-evolution: benchmarked against Hermes-class autonomous agents](#self-evolution-benchmarked-against-hermes-class-autonomous-agents)
- [Architecture overview](#architecture-overview)
- [Quick start](#quick-start)
- [Connecting an LLM (keys never live in code)](#connecting-an-llm-keys-never-live-in-code)
- [Web search (optional)](#web-search-optional)
- [Directory structure](#directory-structure)
- [Testing](#testing)
- [Data and privacy](#data-and-privacy)
- [FAQ](#faq)
- [License](#license)

---

## Why this exists

General-purpose LLMs can write code and chat, but ask one "what is the ammonia-nitrogen discharge limit?" or "produce an acceptance monitoring report" and it will typically start searching on the spot — with little confidence in environmental regulations.

Environment Agent bakes those capabilities **into the product**: a built-in standards retriever, regulation base, industry formulas, report templates, CMA compliance rules and review roles. Every professional conclusion is required to **carry a standard number and a source**; when unsure it says "to be verified" instead of inventing an answer.

In one line:

| | General agents (e.g. Claude Code / Cursor) | Environment Agent |
|---|---|---|
| Positioning | All-rounder for coding / general tasks | Specialist that can hold a post in environmental compliance work |
| Domain knowledge | Retrieved on the fly, weak on regulations | Standards base / regulations / formulas / templates out of the box |
| Answer discipline | General purpose | Never fabricates citations, reports must pass review, knowledge must be crystallized |
| Deployment | Mostly cloud | Desktop, private, data never leaves the machine |
| Interop | — | Standard interfaces; can work alongside general agents |

---

## Core capabilities

- **Task / session system**: multiple parallel tasks, SQLite persistence, no context bleed between tasks
- **Three modes**: `craft` (execute) / `ask` (Q&A) / `plan` (planning)
- **Multiple providers**: any OpenAI-compatible endpoint (DeepSeek / OpenAI / Zhipu GLM / Qwen / local Ollama), plus a **built-in key-free demo mode**
- **KB-first lookup**: FTS5 full-text + vector + relation multi-way recall (RRF fusion), web search as a supplement, five-category ingestion (web material / government releases / standards / policies / other)
- **Skill system**: auto-discovers `data/agents/skills/*/SKILL.md`, switchable per skill; ships with 22 industry skills (acceptance reports, EIA, carbon accounting, CMA compliance, various monitoring domains…)
- **Multi-expert collaboration**: report orchestration, expert review, role assignment and team registry
- **Report center**: template learning, generation by report type, formula computation, Word/PDF export, three-level review
- **Task memory**: persistent project facts, injected across sessions (profile / facts / relations / episodic vectors)
- **Context compression**: summarizes older turns once the soft budget is exceeded, keeps recent turns verbatim; warns at the hard budget
- **Cache-hit accounting**: parses DeepSeek disk cache / OpenAI `cached_tokens`, showing hit rate and savings
- **Streaming output**: SSE rendering in real time, tool calls shown as cards
- **Scheduled tasks (Cron)**: in-app scheduler with per-task notepad, continuous context and last-summary memory
- **Audit and safety**: audit log, R8 review gate for self-learned artifacts, unified gateway entry point
- **Dual front-ends**: v1.2 template UI (`/legacy`) + Vue3 + Vite UI (chat / knowledge base / reports / planner)

---

## Self-evolution: benchmarked against Hermes-class autonomous agents

Environment Agent implements a complete **self-evolution loop (OERCR)**, aligned with the design direction of today's frontier autonomous agents:

```
Observe  →  Reflect  →  Crystallize  →  Reuse
(task run)  (retrospect)  (freeze into skills/templates)  (auto-hit next time)
```

- **Automatic crystallization**: a successful task flow is abstracted into a reusable skill (`SKILL.md` plus template files)
- **R8 review gate**: every self-learned artifact must pass review before it takes effect — no "learning it wrong"
- **Skill iteration and upgrade proposals**: skills are versioned; runs produce `skill_update_proposals` that are promoted after human confirmation
- **Memory loop**: multi-way recall over facts / profile / relations / episodic vectors, so it learns your methodology the more you use it
- **Template learning**: feed it a batch of reports and it identifies types, clusters them, registers new report types and generates template skeletons

> Note: capability boundaries follow the implementation. This repository ships no mocked or fabricated "self-evolution" demo data.

---

## Architecture overview

The project has converged from a **dual-track** state (v1.2 monolith + v2.0 layered) into **a single track where `src/` is the only implementation**. Same-named files at the repository root are now **thin compatibility shims** (`from src.* import ...`), so legacy usage such as `import app` / `import db` keeps working.

```
L1 Gateway        src/gateway/            Flask Web API (SSE) · 222 routes · MCP server · CLI
L2 Reasoning      src/agent/ · src/llm/   ReAct loop (<=8 rounds) · provider pool · routing/intent
L3 Tools          src/tools/ · src/skills/  kb/web/compute/document · SKILL.md execution chain
L4 Memory/KB      src/memory/ · src/kb/     FTS5 + vectors + relations · facts/profile/episodes
L5 Domain         src/report/ · src/compliance/ · src/compute/  reports/compliance/formulas
L6 Collaboration  src/agents/ · src/roles/ · src/teams/ · src/workflow/  sub-agents/roles/teams/workflows
L7 Learning       src/learn/ · src/obs/     OERCR crystallization · R8 review · audit & observability
```

- **Contracts first**: `src/models/core.py` defines core models with Pydantic v2; interface changes must pass contract tests
- **Data layer**: SQLite + WAL, 17 idempotent migrations (`db/migrations/`), existing databases evolve without data loss
- **Event protocol**: SSE events (budget/usage/reasoning/delta/tool_start/tool_end/assistant_done/done…) are kept stable

---

## Quick start

### Requirements

- Python **3.10+** (developed on 3.14)
- Desktop window mode requires `pywebview` (already in dependencies); on headless machines use `--browser`
- Web search is **optional** (needs SearXNG); without it the agent degrades gracefully and local KB Q&A is unaffected

### Install and run

```bash
git clone <your-repo-url>
cd environment-agent

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Desktop window (default, prefers pywebview)
python run.py

# Browser mode / custom port
python run.py --browser
python run.py --port 5837
```

On first launch the database is created, all 17 migrations run, and the **demo knowledge base seed** is injected — give it a moment and you are ready to go.

> Note: start the app with `run.py`. Running `python app.py` alone only starts Flask (default port 5837), without the desktop shell or the SearXNG supervisor.

### Demo mode (zero keys)

The **demo mode** provider (`kind=mock`) is active on first launch: with no API key at all you can exercise the full loop — ask a question → `kb_lookup` searches the local knowledge base → tool cards → streamed answer.

---

## Connecting an LLM (keys never live in code)

**This repository contains no API keys**: all 6 preset providers ship with an empty key, and demo mode is active by default. There are only two ways to inject a key, and neither one enters version control.

### Option 1: Configure in the UI (recommended for desktop users)

Open **Settings** → provider list → pick a preset (DeepSeek / OpenAI / GLM / Qwen / Ollama) or define your own → enter the **API key** → "Test connection" → activate.

The key is stored in your local SQLite database (`data/ecoagent.db`), which is excluded by `.gitignore`.

### Option 2: Environment variables (recommended for containers / CI / headless)

```bash
cp .env.example .env      # .env is already covered by .gitignore
# edit .env:
# EA_LLM_API_KEY=sk-xxxxxxxx
# EA_LLM_BASE_URL=https://api.deepseek.com
# EA_LLM_MODEL=deepseek-chat
# EA_LLM_PROVIDER=DeepSeek        # optional: target provider by name

python run.py
```

At startup `apply_env_override()` writes these values into the target provider and activates it; **when no `EA_LLM_*` variable is set, nothing is modified**.

| Variable | Description |
|---|---|
| `EA_LLM_API_KEY` | API key |
| `EA_LLM_BASE_URL` | OpenAI-compatible endpoint |
| `EA_LLM_MODEL` | Model name |
| `EA_LLM_PROVIDER` | Target provider name (optional) |
| `PORT` | Server port, `0` = pick a free port automatically |
| `ECOAGENT_DB` | Override the database file path |

> 🔐 **Security**: never commit `.env`, `data/ecoagent.db`, or any file containing a key. If you committed one by accident, **revoke and rotate the key at the provider immediately** — deleting the file does not remove it from git history.

---

## Web search (optional)

Web search uses a self-hosted [SearXNG](https://github.com/searxng/searxng) instance (API-key-free meta search):

```bash
python install_searxng.py        # installs into runtime/searxng
python run.py                    # supervises SearXNG on startup (idempotent, self-heals within 30s)
```

Configuration lives in `data/searxng.json`, and can be overridden with `SEARXNG_URL` / `SEARXNG_ENABLED` / `SEARXNG_MAX_RESULTS` and friends.
Without SearXNG the `web_search` tool simply reports a failure — **the main flow is unaffected**.

---

## Directory structure

```
environment-agent/
├── run.py                     # Entry point (desktop window / browser, supervises SearXNG)
├── app.py                     # Flask entry (thin shim; create_app lives in src/gateway)
├── db.py / tools.py / ...     # v1.2 compatibility shims; real implementations live in src/
├── seed.py                    # Demo knowledge base seed
├── kb_pipeline.py             # KB parsing/chunking/embedding pipeline (PDF/Word/Excel/OCR)
├── ocr_*.py / vlm_convert.py  # OCR and image conversion (RapidOCR etc.)
├── report_*.py                # Report computation / learning / orchestration / rewriting
├── searxng_*.py               # SearXNG launcher and MCP adapters
├── src/                       # v2.0 layered implementation (single source of truth, 22 packages)
│   ├── gateway/  agent/  llm/  tools/  skills/
│   ├── memory/   kb/     report/  compliance/  compute/
│   ├── agents/   roles/  teams/   workflow/   scheduler.py
│   ├── learn/    obs/    security/  public_api/  vision/
│   └── models/   core/            # Contract models and configuration
├── db/migrations/             # 17 idempotent migrations
├── templates/  static/        # v1.2 front-end (static/vditor is the editor dependency)
├── web/                       # Vue3 + Vite front-end sources (built output in static/vue)
├── tests/                     # 86 test files (contract / unit / E2E)
├── assets/                    # Icons
├── extras/searxng/            # SearXNG deployment examples (docker-compose / sample settings)
└── data/                      # Default config + demo skills (DB/uploads/logs are runtime-generated and ignored)
```

> This distribution is **code only**: architecture notes, contracts and design documents are intentionally not bundled.

---

## Testing

```bash
python -m pytest -q                 # full suite
python -m pytest tests/core -q      # config and data layer
python -m pytest -m contract        # contract signature tests
```

Current baseline: **810 passed / 0 failed / 1 skipped** over 86 test files, covering contracts, units and end-to-end.

> The one skipped case verifies parity against a legacy `db.py` backup that is deliberately not shipped (it would contain pre-refactor code only).

> Tip: `pytest.ini` adds `-q` by default; to see the pass-count summary, add `-o addopts=""`, e.g.
> `python -m pytest -o addopts="" --tb=line`.

All tests are isolated in temporary databases and never read or write your `data/ecoagent.db`.

---

## Data and privacy

- **Local first**: everything lives in a local SQLite database (`data/ecoagent.db`) — sessions, knowledge base, memory and audit log never leave the machine
- **Fully offline capable**: demo mode plus the local knowledge base closes the loop; with a local Ollama endpoint no data goes online at all
- **No user data in the repo**: databases, backups, uploads, task outputs and learning records under `data/` are all excluded via `.gitignore`; only default config (`searxng.json`, `report_types.json`) and demo skills are shipped
- **Audit and gates**: the audit log records key operations, and self-learned artifacts only take effect after passing the R8 review

---

## FAQ

**Q: No model available in the sidebar after launch?**
Demo mode is active by default. To use a real model, follow [Connecting an LLM](#connecting-an-llm-keys-never-live-in-code); a provider needs `base_url` + `model` + `api_key` to be usable.

**Q: Web search fails?**
That is the expected graceful degradation. Deploy SearXNG (`python install_searxng.py`) and restart.

**Q: How do I move the database?**
Set `ECOAGENT_DB=/path/to/ecoagent.db`.

**Q: The port is taken?**
`python run.py --port 6000`, or just `python run.py` (picks a free port automatically).

**Q: Local features time out while I am behind a corporate / VPN HTTP proxy?**
Loopback traffic is excluded from proxies automatically: `ensure_local_no_proxy()` adds `127.0.0.1 / localhost / ::1` to `no_proxy`, and local webhook pushes use a proxy-free opener (`src/core/net.py`). External endpoints still honour your proxy settings.

**Q: What about copyright of knowledge base / report content?**
Users ingest their own knowledge base content; the repository distributes no third-party standard texts. Please respect the licensing terms of standards publishers.

---

## License

Released under the **MIT License**, copyright holder **qiumaimai** — see [LICENSE](LICENSE).

Third-party dependencies (Flask, Pydantic, Vite, Vditor, SearXNG, …) remain under their own licenses.
