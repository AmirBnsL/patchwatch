# AGENTS.md — PatchWatch Context

Context for an AI coding agent or engineer starting a session on this project. Read
`docs/SPEC.md` for the full specification; this file is the working-context digest.

## Project in one sentence

A **League of Legends patch-change monitoring agent** — watches versioned game data
(Data Dragon JSON) and official patch-note prose, detects what changed between patches,
classifies each change (buff/nerf/neutral/uncertain) with numeric-first logic, produces
a cited impact briefing, and routes meta-shifting changes (reworks, system changes)
through a human-approval gate (a real LangGraph interrupt).

## Why this exists / positioning

- Niche: patch-notes *readers* are saturated; the **agentic lifecycle** (scheduled
  detect → diff → classify → brief → HITL → re-index) with a **versioned, patch-pinned
  index** is not.
- Exercises every marketable AI-engineering concept: LangGraph orchestration, real
  vector DB (pgvector), RAG, evals + regression gates, observability, cost.
- Patch numbers are first-class versions — the versioning machinery is exercised by real
  recurring data, not simulation.

## Current status (IMPORTANT — read first)

- **Phase A′ in progress.** Foundations (Postgres+pgvector, migrations, LangGraph
  linear skeleton on a synthetic corpus) are built and green. The pivot to LoL data is
  the current work: Data Dragon snapshot corpus, numeric-first diffing, relabeled evals.
- See `docs/SPEC.md` §10 for the phase plan.

## Stack (fixed decisions — do not change without a documented reason)

| Layer | Choice |
|---|---|
| Language | Python 3.14 (uv-managed; requires ≥3.11) |
| Env / deps | **uv** + `uv.lock` · hatchling build |
| Orchestration | **LangGraph** (checkpoints, interrupts, conditional edges, map nodes) |
| Vector DB | **pgvector** in Postgres 16 (single Postgres for state + vectors) |
| Driver | `psycopg` (via SQLAlchemy engine) + `pgvector` Python package |
| Migrations | **Alembic** (SQLAlchemy engine; psycopg stays the driver) |
| Config | **pydantic-settings** (pins model/embedding/dim/DB URL) |
| CLI | **typer** |
| Embeddings | API-only, **pinned version** (`text-embedding-3-small`, dim 1536) |
| LLM | API-only, OpenAI-compatible interface (OpenAI in Phase A); swap models without breaking eval baseline |
| API | FastAPI (patch-scoped QA + monitor trigger + eval endpoints) |
| Eval | Custom harness — **deterministic checks first, calibrated LLM-judge second**; regression gates |
| Observability | **OpenTelemetry** spans per node + per tool call; cost/latency per run |
| Safety | Grounding guardrail; deterministic severity rules; HITL on rework-level changes |
| Deploy | Docker + docker-compose (postgres, app); local-first; no GPU |
| CI | GitHub Actions: **Ruff** (lint+format), **mypy**, pytest, eval gate |

**Compute constraint: API-only, no GPU.** All embedding/LLM work goes through pinned API models.

## Architecture (the monitor graph)

```
ingest → version_diff → change_class → contradict_detect → impact_brief → hitl_gate → reindex
                                                                    │ (approve/reject)
                                                                    └→ end (rejected: log)
```
Conditional edges: no delta → end; all-neutral → end (log only); no contradiction → skip; not rework-level → skip gate.

Second surface: **query graph** — `query → time_aware_retrieve (patch-pinned) → version_mix_check → generate → grounding_guardrail → answer + citations`.

## Non-negotiables / invariants

1. **Versioning, not overwrite.** A new patch = new chunk rows with new `valid_from`
   (patch release date); superseded chunks get `valid_to`. **Never delete or overwrite**
   old chunks. This is the time-aware index and the version-mixing detector.
2. **Deterministic before judge.** Numeric stat deltas, version-mixing, citation
   validity — all deterministic. LLM only for ambiguous prose classification,
   contradiction, and faithfulness — always calibrated.
3. **Model + embedding pinning.** Model/version lives in config; any model change
   re-runs the full eval suite. Embedding dimension is pinned before migrations.
4. **Regression gates on every change.** Every eval suite has a gate (paired bootstrap
   CI, Holm-corrected, Monte Carlo validated) — port the machinery from the agent-harness
   project.
5. **Interface-first.** Define `MonitorState` + node contracts before implementing
   nodes; each node is a testable function taking/returning state with a mockable LLM.
6. **Frozen snapshots are load-bearing.** Data Dragon JSON + official patch-note prose
   for 2–3 consecutive patches, with a planted-edit manifest (typo-fix, number-tweak,
   rework) driving every eval case. Deterministic and reproducible.
7. **Traces as research data.** Export every run's trace as JSONL (diffs, retrieval
   contexts, gate decisions).
8. **No autonomous action.** Output is a monitored, human-gated briefing, never an
   autonomous side effect.
9. **Runtime never scrapes.** Live sources are read only via the snapshot/refresh path;
   the app reads the DB and committed snapshots.

## Data model (core tables — see SPEC §5)

- `documents` — source (`ddragon` | `patch-notes` | `fixture`), external_id
  (`champion/Ahri`, `item/3153`), title, version (**patch number**), content_hash, fetched_at.
- `chunks` — document_id, chunk_index, content, `embedding vector(1536)`, **`valid_from`,
  `valid_to`** (NULL = current), source_hash; HNSW index on embedding.
- `runs`, `detected_changes` (`change_class: buff|nerf|neutral|uncertain`), `briefings`,
  `eval_runs` — unchanged from the scaffolded schema.

Time-aware retrieval predicate: `WHERE valid_to IS NULL OR (valid_from <= :qtime AND valid_to > :qtime)`.
Version-mixing flag: top-k results spanning two `valid_from` windows for the same scope.

## Eval suites (each must have a regression gate)

1. Change-detection precision/recall (planted-changes dataset)
2. Buff/nerf/neutral classification accuracy (numeric fast path + judge)
3. Contradiction-detection accuracy (invalidated-guidance pairs)
4. Briefing faithfulness (every impact point cites a retrieved chunk)
5. Citation validity (cited chunk ids exist, are patch-correct, and were retrieved)
6. Version-mixing rate (<5% on patch-scoped queries)

## Development conventions

- **Language:** Python 3.11+; type hints; docstrings.
- **Project layout:**
  ```
  patchwatch/
    src/patchwatch/
      app/            # FastAPI entrypoints (monitor trigger, QA, eval)
      graph/          # LangGraph nodes + state + graph assembly
      db/             # connection, migrations, repositories
      ingest/         # source fetchers (ddragon, prose snapshots)
      diff/           # numeric + prose diff
      eval/           # suites, judges, regression gates
      observability/  # OTel, cost/latency
      fixtures/       # frozen snapshot corpus + planted-change manifest
    tests/
    docs/             # SPEC.md, LEARNINGS.md
  ```
- **Testing:** pytest; unit tests per node with mocked LLM/fetcher; integration = one
  full monitor run on frozen snapshots; HITL-resume test (interrupt → checkpoint → resume).
- **Reproducibility:** pin models/seeds; freeze snapshots; commit eval baselines.
- **Don't reinvent the regression gate** — port the statistical gate from the
  agent-harness project (paired bootstrap, Holm correction, power analysis).

## Roadmap (see SPEC §10 for detail)

- **Phase A′ (current):** snapshot corpus (3 patches, champions+items); numeric-first
  rewire of `ingest → version_diff → change_class → reindex`; eval harness + first gate.
- **Phase B′:** prose-aware classification; contradiction detection; patch-scoped QA +
  version-mixing flag.
- **Phase C′:** impact briefing (RAG over personal pool); HITL interrupt with Postgres
  checkpointing/resume; OTel + cost/latency; gates on all suites.
- **Phase D′:** live refresh (poll `versions.json`); Docker deploy; CI eval gate; blog post.

## Compliance

Fan project; not endorsed by Riot Games (boilerplate in README). No match data / MMR /
rank prediction; no overlays or automation. Data Dragon CDN + committed snapshots only.
