# SPEC — PatchWatch: League of Legends Patch-Change Monitoring Agent

**Status:** draft
**Version:** 0.2.0
**Owner:** AI-engineering skill-development roadmap — domain-agent project P0
**Links:** `../README.md` (project set)

---

## 1. Executive summary

PatchWatch is a **patch-change monitoring agent** for League of Legends. It watches
versioned game data (Data Dragon static JSON) and official patch-note prose, detects
what actually changed between patches, classifies each change (**buff / nerf / neutral /
uncertain**) with numeric-first logic, produces a **cited impact briefing**, and routes
meta-shifting changes through a human-approval gate before surfacing them and
re-indexing.

**Why this is a strong portfolio project:**
- Patch numbers are first-class versions (26.6 → 26.7 every ~2 weeks) — the versioning
  machinery is exercised by real recurring data instead of simulation.
- Deterministic numeric diffs (stat deltas) mean change detection needs **no LLM** — the
  LLM is reserved for meaning/intent, which is the correct cost/reliability posture.
- Exercises every marketable AI-engineering concept: LangGraph orchestration, real
  vector DB (pgvector), RAG, evals + regression gates, observability, safety, cost.
- Research-relevant data: version-mixing, temporal consistency, gate traces.

---

## 2. Problem definition

### 2.1 Pain
Patch notes are long, infrequent, and prose-heavy. Stale guidance (max orders, rush
items, matchup plans) survives patches because nothing systematically invalidates it.
Players and coaches want: *what changed, does it affect my pool, what should I stop
doing* — with proof, pinned to an exact patch.

### 2.2 Core problems PatchWatch solves
1. **Change detection**: detect that a watched scope (champion/item) changed in a new
   patch — deterministically from Data Dragon JSON.
2. **Change classification**: `buff` / `nerf` / `neutral` / `uncertain` — numeric deltas
   first, LLM adjudication for ambiguous prose.
3. **Impact assessment**: given a personal pool/role/mode context, what does this patch
   mean for *you*?
4. **Briefing + routing**: human-readable briefing with patch-pinned citations;
   meta-shifting changes escalate to a human gate.
5. **Versioned retrieval**: a **time-aware index** so Q&A returns the version valid at
   the queried patch; cross-patch mixing is flagged.

### 2.3 Non-goals (v1)
- No match data / MMR / rank prediction (Riot policy risk; also out of scope).
- No live website scraping at runtime — prose is **frozen snapshots** fetched once.
- No gameplay overlays/automation; output is a monitored, human-gated briefing.
- No multi-user SaaS; single-user local-first.

---

## 3. Architecture

```
                       ┌────────────────────────────────────────────────────┐
                       │                 PatchWatch (LangGraph)             │
                       │                                                    │
 ddragon + prose ────▶ │  ┌──────────┐   ┌───────────┐   ┌─────────────┐   │
 snapshots             │  │  Ingest  │──▶│  Version  │──▶│ ChangeClass │   │
                       │  │  (fetch) │   │  Diff     │   │(numeric 1st)│   │
                       │  └──────────┘   └───────────┘   └──────┬──────┘   │
                       │                                        │          │
                       │  ┌──────────────┐   ┌─────────────┐   ▼          │
                       │  │  ImpactBrief │◀──│ Contradict  │   │          │
                       │  │  (RAG + LLM) │   │ Detect      │   │          │
                       │  └──────┬───────┘   └─────────────┘   │          │
                       │         │                             │          │
                       │         ▼                             │          │
                       │  ┌─────────────┐   ┌──────────────┐   │          │
                       │  │  HITL gate  │──▶│ Re-index     │◀──┘          │
                       │  │  (approve)  │   │ (versioned)  │              │
                       │  └─────────────┘   └──────────────┘              │
                       │                                                  │
                       │  ┌──────────────┐  ┌──────────────────────────┐   │
                       │  │  Query/QA    │  │  Observability + Eval    │   │
                       │  │ (patch-scope)│  │  (OTel, cost, gates)     │   │
                       │  └──────────────┘  └──────────────────────────┘   │
                       └────────────────────────────────────────────────────┘
```

### 3.1 Two user-facing surfaces
1. **Scheduled monitor run** — on patch release (or manually): detect → classify → brief.
2. **Patch-scoped QA** — "What is Ahri Q damage in 26.6?" — answered from the versioned
   index; answers never blend patches.

---

## 4. Dev stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.14 (uv-managed; requires ≥3.11) | LangGraph, pgvector, eval ecosystem |
| Env / deps | **uv** + `uv.lock` · hatchling build | fast, reproducible; pins interpreter via `.python-version` |
| Orchestration | **LangGraph** | state machine, checkpointing, interrupts (HITL), conditional edges |
| Vector DB | **pgvector** (via `psycopg` + `pgvector` Python) | versioned index with `valid_from/valid_to` columns; single Postgres for state+vectors |
| Relational | Postgres 16 | app state, runs, evals, docs metadata, traces |
| Migrations | **Alembic** (SQLAlchemy engine; psycopg remains the driver) | versioned, auditable schema; vector/HNSW via raw DDL |
| Embeddings | **OpenAI `text-embedding-3-small`, dim 1536** (API-only, pinned) | no GPU; pin version + dimension before migrations |
| LLM | API-only, **OpenAI-compatible interface** (OpenAI in Phase A) | swap models without breaking eval baseline |
| Config | **pydantic-settings** | pins model/embedding/dim/DB URL |
| CLI | **typer** | `python -m patchwatch monitor --patch 26.7` |
| Diff | numeric stat deltas + `difflib` prose diff | deterministic first, semantic second |
| API layer | FastAPI | query/QA + monitor trigger + eval endpoints |
| Eval | custom harness (deterministic checks + calibrated LLM-judge) | regression gates on every graph change |
| Observability | **OpenTelemetry** spans per node; cost/latency per run | standard, not optional |
| Safety | grounding guardrail; deterministic severity rules; HITL on reworks | trust posture |
| Deploy | Docker + docker-compose (postgres, app) | local-first; no GPU |
| CI | GitHub Actions: **Ruff** (lint+format), **mypy**, pytest, eval gate | portfolio signal |

**Compute constraint: API-only, no GPU.**

---

## 5. Data model (Postgres + pgvector)

### 5.1 Documents (watched scopes)
```sql
CREATE TABLE documents (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source        TEXT NOT NULL,          -- 'ddragon' | 'patch-notes' | 'fixture'
    external_id   TEXT,                   -- e.g. 'champion/Ahri' | 'item/3153'
    title         TEXT,
    version       TEXT,                   -- patch number, e.g. '26.7'
    content_hash  TEXT NOT NULL,          -- sha256 of normalized content
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, external_id, version)
);
```

### 5.2 Versioned chunks (the time-aware vector index)
```sql
CREATE TABLE chunks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id   UUID REFERENCES documents(id),
    chunk_index   INT,
    content       TEXT NOT NULL,
    embedding     vector(1536),           -- dimension pinned to embedding model
    valid_from    TIMESTAMPTZ NOT NULL,   -- patch release date
    valid_to      TIMESTAMPTZ,            -- NULL = current
    source_hash   TEXT,                   -- chunk-level content hash
    UNIQUE (document_id, chunk_index, valid_from)
);

CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);
```

**Key design decision — versioning, not overwrite:**
- Each *patch* gets its own chunk rows; old chunks get `valid_to` (the new patch's
  release date); new chunks get a new `valid_from`. Nothing is deleted.
- **Time-aware retrieval**: `WHERE valid_to IS NULL OR (valid_from <= :qtime AND valid_to > :qtime)`.
- **Version-mixing detection**: a query whose top-k spans two `valid_from` windows for
  the same scope is flagged.

### 5.3 Monitor runs, changes, briefings, evals
Same as the scaffolded schema: `runs` (status, token_cost_cents, latency_ms, trace_id),
`detected_changes` (old/new patch, diff_preview, change_class `buff|nerf|neutral|
uncertain`, severity `low|medium|high|critical` with **rework** flag, contradiction,
citation JSONB, status), `briefings` (summary, impact_points, grounded_in,
requires_human), `eval_runs` (suite, model, prompt_version, metrics JSONB, baseline).

---

## 6. LangGraph pipeline design (the core)

### 6.1 The monitor graph (per-patch run)

| Node | Responsibility | Key outputs | Routing |
|---|---|---|---|
| `ingest` | Check `versions.json`; fetch new/changed scopes (ddragon JSON + frozen prose); hash | `deltas: [DocDelta]` | → `version_diff` if any delta, else end |
| `version_diff` | **Numeric stat deltas** (deterministic) + prose diff → change candidates | `candidates: [ChangeCandidate]` | → `change_class` |
| `change_class` | `buff`/`nerf`/`neutral`/`uncertain` — numeric direction first, LLM for ambiguous prose | `{change_class, magnitude, confidence}` | meaningful → `contradict_detect`; neutral → end (log only) |
| `contradict_detect` | Does the new patch invalidate prior guidance (max order, rush item, combo)? | `{contradiction: bool, evidence}` | → `impact_brief` |
| `impact_brief` | RAG over personal-pool context + watchlist → cited briefing | `briefing {summary, impact_points, requires_human}` | requires_human → HITL gate; else → `reindex` |
| `hitl_gate` | **LangGraph interrupt**: pause for approve/reject on reworks/system changes | approval decision | approved → `reindex`; rejected → end (log) |
| `reindex` | Close superseded chunks (`valid_to` = patch date); insert new chunks; embed | index update tx | end |

### 6.2 The query graph (patch-scoped QA)
`query → time_aware_retrieve (patch-pinned) → version_mix_check → generate (grounded) → grounding_guardrail → answer + citations`

### 6.3 LangGraph features used (explicit)
- **State**: `MonitorState` (TypedDict): run_id, patch range, deltas, candidates, briefing, approval.
- **Checkpointing**: `MemorySaver` (dev) → Postgres saver (Phase C) — HITL runs are resumable.
- **Interrupts**: `hitl_gate` is a real graph interrupt.
- **Conditional edges**: no-delta → end; all-neutral → end; rework-level → HITL.
- **Parallelism**: `impact_brief` fans out per changed scope.

---

## 7. Data sources

| Source | Role | Access |
|---|---|---|
| **Data Dragon** (`ddragon.leagueoflegends.com`) | numeric backbone — version-pinned champion/item JSON | public CDN, no key; `versions.json` → per-patch files |
| **Official patch notes** (leagueoflegends.com) | intent/prose layer — frozen snapshots | fetched **once** at build/refresh; committed under `fixtures/prose/` |
| Community Dragon / wiki | tertiary cross-check only | not an authority |

**Rules:**
- Data Dragon is the detection/classification authority (numbers).
- Prose snapshots are briefing/eval material — never mutated after freezing.
- Runtime never scrapes; it reads the DB + committed snapshots.
- Data Dragon lag: a new CDN version ≠ live in all regions; record region/realm metadata.

---

## 8. Eval harness

### 8.1 Suites (each with a regression gate)
| Metric | Type | How |
|---|---|---|
| Change-detection **precision/recall** | deterministic | frozen patches: every changed stat/section labeled; does the pipeline find it? |
| **Buff/nerf/neutral accuracy** | deterministic-first + judge | numeric direction fast path; LLM judge for ambiguous prose; per-class P/R; `uncertain` allowed |
| Contradiction detection | judge + deterministic | labeled pairs: "max Q first" vs "max E first", "rush X" vs nerf to X |
| Briefing **faithfulness** | deterministic + NLI/judge | every impact point must cite a retrieved chunk |
| Citation validity | deterministic | cited chunk ids exist, are patch-correct, and were retrieved |
| Version-mixing rate | deterministic | patch-scoped queries answered from the right patch only; target <5% |

### 8.2 The eval loop
- Baselines stored in `eval_runs`; changes to graph/prompts/models re-run the suite.
- **Regression gate**: paired bootstrap CI, Holm correction, Monte Carlo validated
  (machinery ported from the agent-harness project).
- Planted-regression test: inject a bad change into fixtures; the gate must fire.

---

## 9. Observability, safety, cost

### 9.1 Observability
- OTel spans per node/tool/retrieval; trace id on `runs`.
- Metrics: per-run cost, latency P50/95, change counts by class, gate-approval rate.

### 9.2 Safety
- Grounding guardrail: impact points without a retrieved citation are held.
- Deterministic severity first: numeric magnitude → severity; rework flag → HITL.
- No autonomous action — briefings only.

### 9.3 Cost
- Numeric fast path means most patches cost ~zero LLM tokens for detection.
- Model routing: small model for classification, larger for briefing; per-run cost tracked.

---

## 10. Roadmap

### Phase A′ — Foundations (current)
- **A1′** Data Dragon snapshot fetcher: `versions.json` + champion/item JSON for 3
  consecutive patches; frozen prose snapshots; planted-edit manifest
  (typo-fix, number-tweak, rework).
- **A2′** Rewire pipeline for patch-versioned JSON+prose: `ingest → version_diff
  (numeric-first) → change_class → reindex`; mock-LLM unit tests.
- **A3′** Eval harness: change-detection P/R + buff/nerf accuracy; first regression gate.

### Phase B′ — Semantic layers
- **B1′** Prose-aware classification (embedding distance + LLM adjudication, calibrated).
- **B2′** `contradict_detect` (invalidated guidance) + labeled eval set.
- **B3′** Time-aware retrieval + patch-scoped QA graph + version-mixing flag.

### Phase C′ — Impact + HITL + ops
- **C1′** `impact_brief` (RAG over personal pool context) with citations; faithfulness +
  citation-validity evals.
- **C2′** `hitl_gate` interrupt with Postgres checkpointing/resume.
- **C3′** OTel + cost/latency + gates on all suites.

### Phase D′ — Production polish
- **D1′** Live-refresh path (poll `versions.json`; ingest only on new patch).
- **D2′** Docker deploy; CI eval gate; README with architecture + numbers.
- **D3′** Blog post: "patch-pinned RAG: a versioned index for game data."
- **D4′** `docs/LEARNINGS.md`.

---

## 11. Testing & validation
- Unit tests per node with mocked fetcher/LLM; fake repo for graph tests.
- Integration: full monitor run on frozen snapshots against Postgres; versioning
  preserved (`valid_to` semantics, nothing deleted).
- Eval suites with regression gates; planted-regression must fire the gate.
- Reproducibility: pinned models, frozen snapshots, versioned fixture manifest.

## 12. Acceptance criteria (v1 done)
1. `docker compose up` + `python -m patchwatch monitor --patch 26.7` runs the pipeline.
2. Detection P/R ≥ 0.9 on planted edits; buff/nerf accuracy ≥ 0.85 on numeric changes.
3. Patch-scoped QA returns patch-correct answers; version-mixing < 5%.
4. Rework-level changes reach the HITL interrupt; approve resumes and re-indexes.
5. Eval suites gated; a planted regression fires the gate.
6. OTel spans + per-run cost/latency visible; README documents architecture + numbers.

## 13. Open decisions
- Embedding model + dimension — **RESOLVED:** `text-embedding-3-small`, dim 1536, pinned.
- HITL surface — **RESOLVED:** CLI interrupt (v1); API endpoint later.
- Fixture patches — **RESOLVED:** 3 most recent stable patches with verified Data Dragon
  availability at build time.
- Live-refresh cadence and region/realm handling — decide in Phase D′.
- Checkpoint backend — MemorySaver (dev) → Postgres saver (Phase C′).