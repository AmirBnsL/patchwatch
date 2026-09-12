# Patch-pinned RAG: a versioned game-data index that answers for the *right* patch

*Draft — Phase D′ deliverable.*

Every RAG tutorial shows you how to embed documents and retrieve them. Almost none show
you what happens **when the documents change**. Your index quietly holds two versions of
the truth, retrieval returns both, and the model blends them into a confident answer
that is correct for neither. In RAG-reliability research this is **version mixing** —
and it's not an edge case for any corpus that evolves: regulations, policies, docs
sites, and — the corpus this project watches — **League of Legends balance patches**,
which change wholesale every two weeks.

This post is the engineering write-up of [PatchWatch](https://github.com/AmirBnsL/patchwatch),
a patch-change monitoring agent built on LangGraph + Postgres/pgvector. Three ideas
carry the whole design.

## 1. Versions are rows, not updates

The index never overwrites. A new patch inserts *new* chunk rows with `valid_from` (the
patch's release date); the superseded rows get `valid_to` and stay forever:

```sql
WHERE valid_to IS NULL OR (valid_from <= :at_time AND valid_to > :at_time)
```

One predicate makes the index **time-aware**: ask about patch 26.6 and you retrieve
26.6's numbers — even though 26.7, 26.8 and 26.9 are also in the index. Delete nothing;
the history *is* the feature.

The audit trail is visible in the DB after three patch runs:

```
version | valid_from | valid_to
16.16.1 | 2026-08-11 | 2026-08-25
16.17.1 | 2026-08-25 | 2026-09-09
16.18.1 | 2026-09-09 | (current)
```

## 2. Don't spend LLM tokens on what code can prove

Patch data is largely numeric. `armor 34 → 32` needs no language model — it needs a diff.
PatchWatch normalizes Data Dragon JSON into flat digests (`stats.armor`,
`spells.0.cooldown`), diffs digests between patches, and classifies with a small
direction table (cooldown/cost up = nerf; stats up = buff; rank-count changes =
uncertain).

When the frozen 26.18 notes said *"targeted nerfs on overperforming pro supports like
Nautilus and Bard… a round of buffs is in order for… Ekko… Master Yi"*, the numeric
engine — with **zero LLM tokens** — found exactly those champions, with the right
directions, from data alone. The LLM is reserved for what code genuinely can't prove:
prose intent, contradiction ("does the new patch invalidate *max E first*?"), and
briefing faithfulness.

This is the cheapest reliability win in applied AI engineering: **deterministic before
judge**. Everything provable is code; everything else is a calibrated model.

## 3. Quality gates, not vibes

Every eval suite (change-detection precision/recall, buff/nerf accuracy, briefing
faithfulness, citation validity, version-mixing rate) has a **regression gate**: paired
bootstrap confidence intervals on the metric delta, Holm-corrected across suites,
Monte-Carlo-validated false-positive rate. The baselines are committed
(`eval_baselines.json`) and CI re-runs the gate — a change that degrades classification
accuracy doesn't merge. The gate itself is tested with a planted regression: inject a
bad change, watch it fire.

The unglamorous truth: the eval harness and the gate took as long to build as the
pipeline — and they're the reason the pipeline can change at all without silently
rotting.

## What a monitor adds to RAG

A one-shot RAG demo embeds a corpus once. A **monitor** lives with the corpus: it
detects the change (hash), localizes it (digest diff), classifies it (direction table +
adjudication), decides it matters (deterministic severity rules), writes a cited brief,
and only then — after a human approves anything rework-level (a real LangGraph
interrupt, checkpointed in Postgres, resumable a day later) — makes the new version
authoritative. The old version isn't deleted; it's *closed*.

That lifecycle — detect → diff → classify → brief → **human gate** → re-index — is the
part of production RAG nobody demos, and it's where all the interesting engineering
lives.

---

*PatchWatch isn't endorsed by Riot Games and doesn't reflect the views or opinions of
Riot Games or anyone officially involved in producing or managing Riot Games
properties.*
