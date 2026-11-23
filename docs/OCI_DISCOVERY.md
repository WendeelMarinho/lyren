# OCI Generative AI — findings

What we learned auditing OCI Generative AI in **`sa-saopaulo-1`**, probed by real calls on
**2026-11-23/24**. Written to be reusable by anyone on OCI.

The tenancy's own identifiers, service limits and quota values are **not** here. They live in the
private infrastructure repository (`lyren-infra`, `docs/TENANCY_INVENTORY.md`), because publishing a
deployment map is a different thing from publishing findings.

## The catalog does not tell you what you can call

This is the finding that shaped the code. The region's model catalog returned 41 models, of which 8
chat entries looked live by their metadata. **Three answered a real request.**

Two traps explain the gap:

1. **Duplicate display-names.** The same model id appears more than once, and the entry whose
   `time-on-demand-retired` is `null` can be the **dedicated-cluster** variant rather than an
   on-demand offer. Filtering on "not retired" therefore selects models that 404 when called.
2. **`time-on-demand-retired` set to epoch zero** (`1970-01-01`) means *not served on demand*. It
   reads like "never retired".

So availability must be established by a probe and recorded, never inferred from catalog metadata.
See [ADR-0003](decisions/0003-empirical-model-availability.md) and
`packages/inference/lyren_inference/registry.py`.

## Three failure modes that need different handling

A call against an unusable model fails in three distinct ways, and collapsing them into one error
loses the only actionable information:

| Response | Meaning | What to do |
|---|---|---|
| **404** `Entity with key <model> not found` | not served on demand here | stop asking for this model |
| **429** `... tenancy limit <name> is set to 0` | the model exists; your quota for it is zero | request a limit increase |
| **401 / 403** | your credentials were rejected | fix auth — never a model problem |

The third one matters more than it looks. An expired credential fails *every* task in a benchmark,
and a harness that reports that as a score of zero has published a credential problem as a model
result. Lyren maps 401/403 to a distinct `ProviderAuthError` and aborts a run that keeps hitting the
same error rather than completing it. See
[ADR-0005](decisions/0005-spend-control-in-process.md) and
[baseline-v2 results](research/baseline-v2-results.md).

## Models callable on demand in this region

Established by real calls, not by the catalog. Availability also depends on per-model quotas, which
vary by tenancy, so treat this as a starting point for your own probe:

| Capability | Model |
|---|---|
| Chat | `cohere.command-a-03-2025` |
| Chat | `meta.llama-3.3-70b-instruct` |
| Chat | `meta.llama-4-scout-17b-16e-instruct` (MoE, 17B active) |
| Embeddings | `cohere.embed-v4.0` — **1536 dimensions**, asymmetric query/document |
| Rerank | `cohere.rerank-v4.0-fast` |

Returned 404: `openai.gpt-oss-120b`, `openai.gpt-oss-20b`, `cohere.command-r-08-2024`,
`meta.llama-3.1-70b-instruct`, `meta.llama-3-70b-instruct`. The `gpt-oss` models are listed as
`ACTIVE` in the catalog and are documented as regionally available, yet are not servable on demand —
the epoch-zero retirement field was the only signal.

Gemini and Grok families were reachable only where the per-model quota was non-zero, which it was
not for us.

## Embeddings carry an input type, and it is not cosmetic

`cohere.embed-v4.0` takes `SEARCH_DOCUMENT`, `SEARCH_QUERY`, `CLASSIFICATION` or `CLUSTERING`.
Query and document embeddings are **asymmetric**: indexing a corpus as queries, or the reverse,
degrades recall with no error and no obvious symptom. Lyren therefore makes `input_type` part of the
request contract rather than a default.

Because the spaces are asymmetric, **absolute cosine similarity is not calibrated** — use the
ranking. Verified on 2026-11-23: a correct match scored ~0.29 and an unrelated one ~0.11, so the
ordering is clear while neither number resembles a "90% match".

## Streaming: the two formats end differently, and one of them repeats itself

Verified against the live service on 2026-11-23. Both formats stream over the SDK's `events()`
iterator with `is_stream=True` on the chat request, and both pad each event with a `pad` field of
filler characters.

**GENERIC** emits deltas under `message.content[].text`, closes with an empty-text event carrying
`finishReason`, then sends a `[DONE]` sentinel:

```
{"index":0,"message":{"role":"ASSISTANT","content":[{"type":"TEXT","text":"po"}]},"pad":"aaa"}
{"message":{"role":"ASSISTANT","content":[{"type":"TEXT","text":""}]},"finishReason":"stop"}
[DONE]
```

**COHERE** emits deltas under `text` — and then closes with a summary event whose `text` is the
**entire answer**, not a delta, alongside `chatHistory` and `finishReason`. There is no `[DONE]`:

```
{"apiFormat":"COHERE","text":"Pong","pad":"a"}
{"apiFormat":"COHERE","text":".","pad":"aa"}
{"apiFormat":"COHERE","text":"Pong.","chatHistory":[...],"finishReason":"COMPLETE"}
```

Concatenating every `text` therefore yields `"Pong.Pong."`. The fix is to drop the summary's text
once any delta has been emitted, and to keep it when none has — which covers an answer short enough
to arrive as a single event. This is the kind of bug that produces plausible-looking duplicated
output rather than an error, so it is regression-tested.

**Neither format reports `usage` on a stream.** Token counts are simply unavailable for streamed
calls, so anything that meters tokens has to treat them as unknown rather than zero.

## Two request formats, one endpoint

Cohere models take `apiFormat: "COHERE"` (a single `message`, `chat_history`, `preamble_override`)
while Meta and Google models take `apiFormat: "GENERIC"` (OpenAI-like `messages` with typed content
parts). One client, one auth mechanism, two request shapes — a provider abstraction has to normalise
this. See `packages/inference/lyren_inference/providers/oci.py`.

## Costs are opaque

Per-token prices are **not exposed through the API**. The usage and cost endpoints also lag by hours,
so a run cannot be priced immediately after it happens. Consequences for anyone building on this:

- Do not convert tokens to money from a guessed rate. Lyren's `PriceBook` returns `None` for an
  unpriced model and the ledger reports the total as incomplete rather than understating it.
- A **call-count cap** is enforceable with no price knowledge at all, which makes it the only usable
  spend guard before the first invoice. A money cap needs a price, and with the price missing the
  guard should fail closed.
- An OCI budget **only alerts**. It does not stop spending.

## Not verified

Max context window per model (not exposed by the API, not measured — left `None` in the registry
rather than guessed), per-token prices, Autonomous AI Database availability, and the
OpenAI-compatible endpoint Oracle documents.
