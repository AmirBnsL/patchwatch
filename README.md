# PatchWatch

**A League of Legends patch-change monitoring agent** — watches versioned game data
(Data Dragon) and official patch-note prose, detects what actually changed between
patches, classifies each change (**buff / nerf / neutral / uncertain**) with
numeric-first logic, produces a cited impact briefing, and routes meta-shifting changes
(quickly: kit reworks, system changes) through a human approval gate.

Niche: patch-notes *readers* are everywhere; the **agentic lifecycle** (scheduled
detect → diff → classify → brief → HITL → re-index) with a **versioned, patch-pinned
index** is not. Exercises every marketable concept: LangGraph, real vector DB
(pgvector), RAG, evals + regression gates, observability, cost.

## Core capabilities (v1)
- **Monitor pipeline** (LangGraph): `ingest → version_diff → change_class → contradict_detect → impact_brief → hitl_gate → reindex`
- **Numeric-first diffing**: stat deltas (`Q 75 ⇒ 90`) detected deterministically — no LLM tokens spent on detection.
- **Time-aware retrieval**: versioned pgvector index (`valid_from`/`valid_to` keyed by patch release date) — answers use the version valid at the queried patch; version-mixing is flagged.
- **Eval harness + regression gates**: change-detection P/R, buff/nerf accuracy, contradiction, faithfulness, citation validity — every one gated.
- **HITL**: rework-level changes pause at a real LangGraph interrupt; runs checkpoint/resume.
- **Observability**: OTel spans per node, cost/latency per run, grounding guardrail.

## Data sources
- **Data Dragon** (official, version-pinned JSON) — detection/classification backbone.
- **Official patch notes** — frozen snapshots for intent, briefing, and eval labels.
- Runtime never scrapes; it reads the DB and committed snapshots.

## Stack
Python 3.14 · LangGraph · Postgres 16 + pgvector · FastAPI · Docker · OpenTelemetry · API-only models (no GPU).

## Docs
- `docs/SPEC.md` — full specification (architecture, data model, pipeline, evals, roadmap).
- `docs/LEARNINGS.md` — (after build) design decisions, what broke, what I learned.

## Status
- [x] Phase A′: foundations (Postgres+pgvector, frozen Data Dragon corpus, numeric-first pipeline, eval harness + gate)
- [x] Phase B′: semantic layers (embeddings + LLM adjudication, contradiction detection, patch-scoped QA, version-mixing flag)
- [ ] Phase C′: impact briefing + HITL + observability
- [ ] Phase D′: live refresh + deploy + blog post

See `docs/SPEC.md` §10 for the phase-by-phase plan.

---

*PatchWatch isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties, are trademarks or registered trademarks of Riot Games, Inc.*
