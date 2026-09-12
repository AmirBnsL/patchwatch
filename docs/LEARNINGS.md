# LEARNINGS — PatchWatch

Design decisions, what broke, and what was learned while building. Newest phase last.

## Foundations (Phase A′)

1. **Fixture design is load-bearing and fragile in non-obvious ways.** The planted
   meaningful/cosmetic edits must separate under the *similarity heuristic*, and a
   mid-document rewrite shifts every later chunk boundary (token windows), contaminating
   the typo chunk's similarity. What worked: put the cosmetic edit EARLY and the
   meaningful edit in the LAST section; verify chunk sims empirically before writing
   tests. The deeper lesson: a per-chunk similarity threshold can't distinguish "one
   number changed" from "typo" — which is exactly why classification is numeric-first in
   the real pipeline and why the heuristic is a placeholder.

2. **Idempotency is a monitor requirement, not a nicety.** The first end-to-end CLI demo
   crashed on a unique-constraint violation because re-detection re-inserted an existing
   version. Monitors must never crash on re-detection: `insert_document_version` and
   `insert_chunks` are now `ON CONFLICT`-safe.

3. **Test teardown matters as much as setup.** An autouse fixture that cleaned *before*
   the test but not after leaked rows into the DB and broke the next CLI run with
   confusing symptoms (unique violation on a "fresh" bootstrap). Clean both sides.

4. **Versioned-ingest must be hash-driven, not fetch-driven.** The ingest node compares
   `content_hash` against the stored latest — fetching the same content twice is a no-op
   by construction. Bootstrap (all new), step (delta), and re-run (no-op) all fall out of
   one rule.

## Semantic layers (Phase B′)

5. **Deterministic detection reproduced designer intent.** The numeric diff over frozen
   16.17.1→16.18.1 digests found exactly the 7 champions the patch notes describe
   (Bard/Nautilus nerfs, Ekko/Master Yi buffs, Seraphine rank change) — with zero LLM
   tokens. The "deterministic before judge" invariant pays off visibly.

6. **Data Dragon's spell numbers are unreliable — plan for it.** `effectBurn` is often
   zeroed/stale (Riot's ecosystem docs admit this). The digest tracks reliable paths
   (base stats, cooldown/cost/range burns, item gold/stats); damage numbers come from the
   prose layer. Don't build evals on unreliable fields.

7. **Correct time-aware retrieval cannot mix versions — the flag is a leak detector.**
   With `valid_to` closed at the next patch's publish time, the window predicate returns
   exactly one version per scope. The version-mixing flag exists to catch index bugs
   (e.g. a missing supersede), which is the research failure mode in practice.

8. **Bag-of-words test embeddings need care.** `HashEmbeddings` treats a typo as a
   *different token* (cosine ~0.92, not ~1.0) and small dims cause index collisions.
   Deterministic and offline, but thresholds must be calibrated against its actual
   behavior — or test pairs designed to be unambiguous.

## Impact + HITL + observability (Phase C′)

9. **Severity rules need a "bootstrap vs transition" distinction.** The first demo gated
   on bootstrap (brand-new docs with ≥5 chunks hit the "many fields changed" rule).
   Brand-new content is not a rework: breadth counts only transitions (candidates with
   old text).

10. **LangGraph interrupts + checkpointing work, but respect payload size.** The HITL
    interrupt → checkpoint → resume flow works cleanly on modest states (verified against
    the real Postgres saver). Full-corpus states (1041 deltas + digests, MBs per
    superstep) corrupt the psycopg wire protocol (`invalid message length` from the
    server). Postgres checkpointing is opt-in until states are made reference-based
    (Phase D′ refactor).

11. **Graceful degradation keeps the graph demoable.** `contradict_detect` (no LLM) and
    `impact_brief` (no generator) skip with a log line instead of crashing — the Phase A
    linear graph keeps working as the semantic layers land.

## Production polish (Phase D′)

12. **The live path is one door.** `LiveRefresher` is the single sanctioned touchpoint
    with the CDN; the monitor reads frozen snapshots/DB only. Refactoring the build
    script into a library (`corpus_freeze.py`) made the refresh path ~50 lines instead of
    a second implementation.

13. **Eval gates belong in CI from day one.** `check_gate.py` runs the deterministic
    suites against committed baselines (`eval_baselines.json`) with the same
    Holm-corrected gate used at runtime — a quality regression cannot merge, not just
    "be noticed later".
