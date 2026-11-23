# Open Source Reuse Matrix

Metadata read from the GitHub API on **2026-11-23**. All candidates are actively maintained (pushed
within the last three weeks) and none is archived.

| Project | License | Last push | Stars | Decision |
|---|---|---|---|---|
| [assistant-ui](https://github.com/assistant-ui/assistant-ui) | MIT | 2026-11-23 | 13.4k | **Adopt** — Phase 2 web UI |
| [vercel/chatbot](https://github.com/vercel/chatbot) | `NOASSERTION` | 2026-11-03 | 21.1k | **Reference only** |
| [litellm](https://github.com/BerriAI/litellm) | `NOASSERTION` | 2026-11-23 | 63.8k | **Deferred** — see below |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | MIT | 2026-11-23 | 136.2k | **Adopt** — Phase 2 local inference |
| [langgraph](https://github.com/langchain-ai/langgraph) | MIT | 2026-11-22 | 45.3k | **Adopt** — Phase 6 orchestration |
| [deepagents](https://github.com/langchain-ai/deepagents) | MIT | 2026-11-23 | 31.5k | **Evaluate on top of LangGraph** |
| [mem0](https://github.com/mem0ai/mem0) | Apache-2.0 | 2026-11-23 | 69.4k | **Port the design, not the service** |
| [opencode](https://github.com/anomalyco/opencode) | MIT | 2026-11-23 | 228.7k | **Integrate** — Phase 7 |

## Decisions and their reasons

**LiteLLM — deferred, not rejected.** The repository reports `NOASSERTION`: the core is MIT but an
enterprise subtree carries a separate proprietary license, so adoption needs a file-level license
read first. Independently, its value is provider normalisation across many vendors, and this tenancy
has **three callable chat models behind one API with one auth mechanism**. A thin
`ChatProvider` port (already written, ~100 lines) covers that without pulling a large dependency
onto a 12 GB box. Revisit when a second provider family lands — then the normalisation earns itself.

**vercel/chatbot — reference only.** `NOASSERTION` plus a dependency chain on Neon, Vercel Blob and
AI Gateway, none of which fits an OCI-hosted deployment. Useful to read for auth and history
patterns. assistant-ui is the smaller adaptation cost.

**llama.cpp — adopt, but local inference is an experiment subject, not the workhorse.** Two ARM
OCPUs give single-digit tokens/second on a 7-8B quant, which cannot drive an agent loop. Target the
1B-4B GGUF range and benchmark before choosing. The point of the local provider is to be a routing
arm with a real cost profile, not the primary engine.

**LangGraph — one durable runtime, not two.** The original plan paired LangGraph with Temporal. Both
persist state, retry and resume, and Temporal additionally requires deterministic workflow code, so
LLM calls must live in activities — embedding a LangGraph graph inside a Temporal workflow forces a
choice between reimplementing the graph as activities or losing durability inside it. LangGraph
alone, and Temporal only if a failure mode appears that LangGraph genuinely cannot handle. See
[ADR-0002](decisions/0002-single-durable-runtime.md).

**deepagents — evaluate, do not stack.** It is a LangGraph-based reference implementation. Adopt it
only if it reduces our code; two parallel agent runtimes is a non-goal.

**mem0 — port the design, skip the service.** Its extraction, consolidation and contradiction model
is the valuable part. Running it as an extra service with its own vector store on a 12 GB box
duplicates storage we already plan to put in Oracle AI Database. Write an adapter.

**opencode — integrate, never fork.** 228k stars and MIT. Point it at the Lyren gateway rather than
reimplementing repository exploration, patching and context management. Isolation and action
approval stay on our side of the boundary.

## Written here, not reused

| Component | Why it is ours |
|---|---|
| Pinned model registry with empirical availability | The specific OCI catalog-versus-reality gap is not something a library models |
| Record/replay cassette cache | Keyed on our pinned-version semantics; reproducibility is the product |
| `ChatProvider` port and alias policies | This is the routing identity of Lyren |
| Spend and authorisation gates | Must be ours to be trustworthy |

## Dependency rule

A new production dependency needs: a license read, ARM64 confirmation, a memory estimate against the
12 GB budget, a pinned version, and a line in this file saying why the alternatives did not suffice.
