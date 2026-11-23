# ADR-0008 — Streaming: what a started response can and cannot do

**Date:** 2026-11-24 · **Status:** Accepted

## Context
Streaming changes error handling, cancellation and usage accounting at once, which is why it was
held back rather than half-built. Four properties had to be decided, and three of them are forced by
the fact that **once the first byte is sent, the response is committed**.

## Decisions

**1. Usage is recorded in `finally`, so a client that disconnects still spends its quota.**
The tokens were generated whether or not anyone read them. Recording only on clean completion would
make cancellation a way around the rate limit — open a stream, read one frame, disconnect, repeat.
Verified by a test that disconnects after the first frame and asserts the call was still counted.

**2. A failure after the first byte becomes an error frame inside the stream, not an HTTP status.**
The headers are long gone, so `502` is not available any more. The stream emits
`data: {"error": {...}}` followed by `data: [DONE]`. This is the only honest option, and it means a
streaming client must inspect frames for an `error` key rather than trusting the status line.

**3. Alias fallback happens only before the first chunk.** Switching models mid-answer would splice
two different completions into one reply, which is worse than failing. Once a byte is out the model
is committed; before that, a retryable provider error still falls through to the next candidate and
still records the availability verdict.

**4. A cassette preserves content, not token timing.** A replayed stream arrives as a single chunk
holding the whole text. Reproducing arrival times would be a fiction, and content is what the
experiments compare. A streamed call and a non-streamed one therefore **share a cassette**: the
result of the prompt is the same object either way.

**5. A stream cancelled part-way is not recorded.** Storing a truncated answer would poison every
later replay of that prompt. Recording happens only when the generator completes.

## Consequences
`stream=true` against a provider that cannot stream is refused **before** the response starts, with
a normal HTTP error, because that is knowable up front.

OCI reports **no token counts on a stream** (verified 2026-11-24). So a streamed call is counted
against the daily and per-minute quotas, and its tokens are left unknown rather than recorded as
zero. Per-principal token attribution is therefore incomplete for streamed traffic — stated here
rather than papered over.

The handler is declared `response_model=None`, since it returns either a JSON body or a
`StreamingResponse` and FastAPI cannot derive one schema from both.
