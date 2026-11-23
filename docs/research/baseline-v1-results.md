# baseline-v1 — first calibration run

**Run 2026-11-24.** Task set `baseline-v1` (14 tasks, machine-graded), temperature 0, one attempt per
task, 42 provider calls total. Reproducible from cassettes with `LYREN_CACHE_MODE=replay`.

## Results

| Model | Passed | Latency p50 | Latency p95 | Tokens in / out |
|---|---|---|---|---|
| `meta.llama-4-scout-17b-16e-instruct` | **12/14 (86%)** | **82 ms** | 1436 ms | 632 / 57 |
| `cohere.command-a-03-2025` | **12/14 (86%)** | 224 ms | 595 ms | 420 / 56 |
| `meta.llama-3.3-70b-instruct` | 11/14 (79%) | 90 ms | 629 ms | 984 / 53 |

Cost: **unknown**. No per-token price is configured, so the harness reported `cost=UNKNOWN` rather
than a guess. Total consumption across all three runs was ~2,036 input and ~166 output tokens.

## The honest reading: this task set cannot tell these models apart

Two tasks failed on **every** model, so they contribute no discrimination. That leaves an effective
12 tasks, across which the whole spread is **one task**. With n=12 and a one-task difference, the
ranking above is noise. The cheapest and fastest model tying the most expensive one is suggestive,
not a result.

This is the measurement that had to exist before anything else was built, and its first finding is
about itself: `baseline-v1` is too small and too easy to support a claim. No component added later
should be credited with an improvement measured on it.

## Task defects found

**`str-003` — contaminated, replace.** "Quantas palavras há na frase: o rato roeu a roupa do rei?"
Expected 7 (recounted and confirmed). The models answered 8, 8 and 9. The prompt quotes a famous
Portuguese tongue-twister whose canonical form continues "…do rei de Roma" (10 words), so a model may
be recalling the canonical sentence instead of counting the one given. A task that cannot distinguish
a counting failure from a recall failure measures nothing. Replace the sentence with a neutral one.

**`str-001` — valid but non-discriminating.** Reversing "engenharia" failed on all three
(`aignegne.`, `airaehgne`, `aicneginhare`). This is the well-known character-level weakness of
subword tokenisation, so it is a legitimate weakness probe but useless for ranking. Keep it, label it
as a known-weakness probe, and exclude that class from the discriminating score.

**`know-001` — grader behaved correctly.** `meta.llama-3.3-70b-instruct` answered "Camberra". The
exact grader failed it, which is right: the spelling is wrong. Recording it here because a near-miss
is the case where a grader is most tempting to loosen, and loosening it would be wrong.

## baseline-v1 stays frozen

The defects above are **not** fixed in place. Frozen means frozen: editing a task set after seeing
results is how a benchmark starts flattering its own system. `baseline-v1` keeps its defects and its
recorded numbers; corrections go into `baseline-v2`.

## What baseline-v2 needs

- Enough discriminating tasks that a one-task difference is not the whole spread. Multi-step
  reasoning, longer instruction-following with several simultaneous constraints, structured
  extraction with exact schemas, and code tasks graded by execution.
- Known-weakness probes tagged and scored separately from the discriminating set.
- Neutral prompts, free of famous phrases, to keep recall from masquerading as reasoning.
- More than one attempt per task, so variance is visible rather than assumed away.
- A price book, so quality can be read against cost instead of alongside it.
