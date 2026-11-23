# baseline-v2 — first measured run

**Run 2026-11-24**, API-key auth. 22 tasks (20 discriminating + 2 weakness probes), **2 attempts per
task**, temperature 0. 131 provider calls. Reproducible from cassettes with `LYREN_CACHE_MODE=replay`.

## Results

| Model | Discriminating | Weakness probes | Latency p50 | Latency p95 | Tokens in / out | Unstable |
|---|---|---|---|---|---|---|
| `meta.llama-3.3-70b-instruct` | **90.0%** | 50% | 86 ms | 405 ms | 3430 / 335 | none |
| `cohere.command-a-03-2025` | **90.0%** | 50% | 184 ms | 744 ms | 1664 / 304 | none |
| `meta.llama-4-scout-17b-16e-instruct` | 87.5% | 50% | **81 ms** | 482 ms | 2283 / 406 | `time-001` 1/2 |

Cost: unknown. No per-token price is configured, so the harness reports `cost=UNKNOWN`.

## The quantitative conclusion: this harness measures cost and latency, not quality

At n=20 discriminating tasks the standard error of a proportion near p=0.89 is
`sqrt(0.89 × 0.11 / 20) ≈ 7.0` percentage points. The observed spread is **2.5 points ≈ 0.36 SE**.
That is noise. The two attempts per task do not help: repeats of the same prompt are not independent
observations, so the effective n for quality remains 20, not 40.

To detect a 5-point quality difference at 80% power and α=0.05 would take roughly
`(1.96 + 0.84)² × [0.90×0.10 + 0.85×0.15] / 0.05² ≈ 680` tasks per model. A hand-written personal
benchmark will not reach that, and pretending a 20-task set ranks models 2.5 points apart would be
the exact failure this harness exists to prevent.

**What the same n does measure cleanly:**

- **Latency.** `command-a` is 2.3× slower than `scout` at p50 (184 ms vs 81 ms) over 44 samples
  each. Large, consistent, and well outside noise.
- **Token consumption.** For the identical 22 prompts, input tokens ranged from 1664 (`command-a`)
  to 3430 (`llama-3.3-70b`) — a 2.1× tokeniser difference that propagates straight into cost.

**Therefore the Model Router should route on cost and latency subject to a quality floor, not on a
quality ranking.** A quality floor ("does not regress below X% on the discriminating set") is
supportable at this n; a ranking is not. This is an architectural conclusion drawn from the
measurement rather than from preference.

The cheapest and fastest model tying the most expensive one has now been observed twice
(`baseline-v1` and `baseline-v2`). Replication raises confidence that there is **no large quality
gap**; it still does not establish an ordering.

## Task reclassification needed: `wcount-001`

"Quantas palavras há na frase: a casa verde tem duas janelas abertas?" Expected 7. All three models
answered 8, 8 and 9. A task every model fails carries no discriminating information, so it belongs
with the weakness probes.

This also **refutes the hypothesis recorded for `baseline-v1`**. There, the equivalent task quoted a
famous Portuguese tongue-twister whose canonical form has more words, and the failure was attributed
to recall interference. `baseline-v2` used a neutral sentence as the control and the failure
persisted, so the cause is word-counting itself, not contamination. The earlier explanation was
wrong, and the harness is what showed it.

Reclassification goes into `baseline-v3`. `baseline-v2` stays frozen with this run's numbers.

## Other observations

- `probe-reverse-001` (string reversal) failed on every model; `probe-letters-001` (counting a letter
  in a short word) passed on every model. Both are tokenisation probes, so the 50% probe score is
  one of each rather than partial credit.
- `scout` recorded one `provider_auth_error`: a transient 401 on its first call, with a valid API
  key, which succeeded on the following attempt. The fail-fast abort correctly did **not** trigger,
  since the streak was 1. No retry-on-401 was added: retrying a credential failure would mask a
  genuinely expired key, and a retry policy belongs in the deliberate fallback work of Phase 4.
- `scout` was the only model with an unstable task (`time-001`, 1/2 passes at temperature 0),
  consistent with a smaller active parameter count on a multi-step arithmetic prompt.

## What baseline-v3 needs

- Harder tasks, so scores land in the 40-70% band where a 20-task set has far more resolving power
  than it does near 90%.
- `wcount-001` moved to the weakness probes.
- A price book, so the cost axis — the one axis that does discriminate — can be reported in money
  rather than in tokens.

## Addendum, 2026-11-24: a gap the task set cannot see

While verifying streaming end to end, `cohere.command-a-03-2025` answered a Portuguese prompt
("conte de 1 a 5") correctly and then continued **in Spanish**: *"¿Necesitas algo más? Puedo
ayudarte con cualquier otra cosa que necesites."*

For a platform used in Portuguese that is a real defect, and `baseline-v2` **cannot detect it**.
Every `ptbr`-tagged task asks for a short answer — one word, one number, one date — and a
single-token reply reveals nothing about which language the model would write prose in. The task set
measured Portuguese *comprehension* and never Portuguese *production*.

This is the same class of error as the `wcount-001` misdiagnosis: the measurement looked adequate
until something outside it exposed what it was blind to.

`baseline-v3` needs at least one prose task per language with a grader that checks the **response
language**, not just the content. A cheap deterministic version: require a sentence of free prose and
grade with `not_contains` against a list of Spanish-only function words, or score the proportion of
tokens matching a Portuguese stopword list. Neither needs a model to judge a model.

Recorded here rather than fixed in place: `baseline-v2` stays frozen with its numbers.
