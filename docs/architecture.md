# Architecture

<!-- TODO(doc pass): every section below gets full prose; bullets are scaffolding. -->

## 1. Business context & success criteria

<!-- TODO: problem (execs queue on analysts), success metrics (time-to-insight,
% questions self-served, adoption), explicit non-goals. Write this BEFORE architecture. -->

## 2. System overview

Legend: solid teal = prototype (implemented), dashed amber = stretch, dashed gray = production design (v2).

```mermaid
flowchart TB
    classDef proto fill:#e1f5ee,stroke:#0f6e56,color:#04342c
    classDef stretch fill:#faeeda,stroke:#ba7517,color:#412402,stroke-dasharray:4 3
    classDef future fill:#f1efe8,stroke:#888780,color:#444441,stroke-dasharray:7 4

    MGR(["Store / regional manager"])

    subgraph IFACE[" Interfaces "]
        CLI["CLI chat REPL<br/>typed confirms · --user id"]
        WEB["Web app / Slack bot"]
    end

    subgraph CORE[" Agent service — LangGraph (Python) "]
        GUARD["Input guard<br/>scope policy + injection heuristics"]
        CTX["Context assembler<br/>base policy + persona + prefs<br/>+ schema cache + few-shots"]
        LOOP["Agent loop — tool-calling LLM<br/>recursion limit + per-turn SQL budget"]
        subgraph TOOLS[" Tools "]
            TSQL["run_sql"]
            TSCH["get_schema"]
            TREP["save_report / list_reports"]
            TDEL["delete_reports"]
            TPREF["remember_preference"]
        end
        SQLG["SQL guard — sqlglot<br/>SELECT-only · table allowlist ·<br/>LIMIT inject · dry-run · byte cap"]
        PIIM["PII masker — deterministic<br/>column denylist + regex sweep"]
        HITL{{"interrupt()<br/>preview matches → typed confirm<br/>ownership enforced in code"}}
        FINAL["Final report<br/>persona-styled + output PII sweep"]
    end

    subgraph LLM[" LLM plane "]
        GEM["Gemini 2.5 Flash<br/>AI Studio free tier · temp 0"]
        FALL["Retry w/ backoff → fallback model<br/>(2nd Gemini / OpenRouter)"]
        EMB["Embedding model"]
    end

    subgraph DATA[" Data plane "]
        BQ[("BigQuery — read-only<br/>thelook_ecommerce")]
        APPDB[("SQLite app store<br/>reports · prefs · personas · checkpoints")]
        FEWS["golden_examples.json<br/>static few-shot stand-in"]
        LAKE[("Golden bucket — GCS data lake<br/>system of record: trios + lineage")]
        VIDX[("Serving index — pgvector<br/>hot path · rebuildable from the lake")]
    end

    subgraph LEARN[" Learning loop — system level "]
        RETR["Hybrid retrieval<br/>dense + BM25 + rerank"]
        PROMO["Feedback → curation queue<br/>→ human approval → promote"]
        NIGHT["Nightly trio validation<br/>dry-run vs schema drift"]
    end

    subgraph OBSQA[" Observability & QA "]
        LOGS["Structured JSON traces<br/>trace_id · tokens · bytes · retries"]
        DASH["LangSmith / OTel<br/>dashboards · alerts · cost"]
        EVAL["Eval harness<br/>golden questions + LLM judge, CI gate"]
    end

    MGR --> CLI
    MGR -.-> WEB
    CLI --> GUARD
    GUARD --> CTX --> LOOP
    LOOP <--> TOOLS
    TSQL --> SQLG --> BQ
    BQ --> PIIM --> TSQL
    TDEL --> HITL -->|"confirmed — own rows only"| APPDB
    TREP --> APPDB
    TPREF --> APPDB
    CTX --- APPDB
    FEWS --> CTX
    LOOP --> FINAL --> CLI
    LOOP -.-> GEM --> FALL
    LAKE ==>|"hydrate · blue-green rebuild"| VIDX
    VIDX --- RETR
    RETR -.->|"top-k trios at query time"| CTX
    FINAL -.->|"accepted reports"| PROMO --> LAKE
    NIGHT --> LAKE
    EMB --- VIDX
    CORE -.-> LOGS
    CORE -.-> DASH
    EVAL -.->|"pre-deploy gate"| CORE

    class CLI,GUARD,CTX,LOOP,TSQL,TSCH,TREP,TDEL,TPREF,SQLG,PIIM,HITL,FINAL,GEM,FALL,BQ,APPDB,LOGS proto
    class FEWS,EVAL stretch
    class WEB,LAKE,VIDX,RETR,PROMO,NIGHT,EMB,DASH future
```

## 3. Requirement-by-requirement design

Each subsection: production design first, then what the prototype implements.

### 3.1 Hybrid intelligence — the golden bucket

<!-- TODO (the section they said they'll read closely): trio schema w/ lifecycle
metadata (tables_used, verified_by, embedding_version, retrieval_count, success_rate,
last_validated_at); storage = GCS source of truth + vector index (pgvector or BigQuery
VECTOR_SEARCH — 10k trios is SMALL, say so, ops-simplicity drives the choice + growth
path); retrieval = hybrid dense+BM25, metadata filters, top-k + rerank; injection as
few-shot exemplars; update-over-time = expert ingestion + feedback→curation→promotion,
nightly dry-run validation vs schema drift, re-embedding with version tags, held-out
slice as retrieval regression set. Prototype stand-in: golden_examples.json. -->

### 3.2 Safety & PII masking

<!-- TODO: compliance as architectural principle — capability constrained structurally
(tool allowlist, read-only IAM), PII masked deterministically at result boundary +
final-output sweep ("even if the SQL retrieves it"); spec names phones+emails, dataset
also has names/addresses/geo → configurable denylist; audit trail. -->

### 3.3 High-stakes oversight — saved-reports deletion

<!-- TODO: delete_reports is the single destructive tool; it accepts the user's own
vocabulary (search substring / created_on date) or explicit ids — the spec's inputs
("Delete all reports mentioning Client X", "we made today") resolve in ONE tool call
and the model never asks users for ids. Design evolution worth narrating: v1 was
ids-only for least authority + TOCTOU safety (LangGraph re-runs pre-interrupt code on
resume, so a filter would re-resolve after confirmation); v2 moved that guarantee into
the gate — the CLI echoes the previewed ids back in Command(resume={approved, ids}),
so the deleted set is pinned to what the human saw, by construction. Ownership ambient
from session (model cannot spoof user_id); typed-phrase confirm; cancel path.
REQUIREMENT CLARIFICATION (maintainer, Slack 2026-07-09): store and regional managers
have identical access — no RBAC tiers. Identity exists for report ownership and
personalization only; role-based data scoping is documented as a future extension
point, not designed for. -->

### 3.4 Continuous improvement

<!-- TODO: user level = preference memory injected per turn; system level = the golden
bucket promotion pipeline (same mechanism as 3.1 — say so explicitly). -->

### 3.5 Resilience & graceful error handling

<!-- TODO: error taxonomy → model-actionable tool returns; per-turn SQL budget +
recursion limit ("without inflating costs"); dry-run as free syntax check; retry w/
backoff → model fallback chain; REPL never crashes. -->

### 3.6 Quality assurance

<!-- TODO: write as a LAYERED strategy, each layer catching what the previous can't:
L0 deterministic unit tests (SQL guard, PII masker, confirm-gate UX, store ownership,
   prompt assembly) — exists, 43 tests, runs in <1s, zero API cost, CI on every push.
L1 prompt-level evals — `pytest -m live` (tests/test_policy_live.py) renders through
   the SAME production assembly seam (build_system_prompt, schema from a checked-in
   snapshot), so what's evaluated is what ships. Cases target tool-free policy
   adherence: injection refusal, scope refusal, PII non-compliance, persona changes
   tone but never rules. Stack-native (no extra toolchain — runs in the venv or the
   Docker image), excluded from default runs, and deliberately uses the weakest model
   in the fallback chain: policy must not depend on model size. Verified 4/4 live.
   Gate before any prompts/policy.md change ships. Because prompt assembly is a pure
   function over versioned prompt data, dedicated eval tooling (promptfoo for
   prompt×model matrices, Langfuse/LangSmith datasets) plugs into the same seam
   whenever matrix runs or non-developer case authoring justify it — we evaluated
   that path and kept the simpler stack-native runner for v1.
L2 agent-level evals — golden questions end-to-end: value assertions via
   independently written SQL + LLM judge for intent/grounding/no-PII (stretch
   harness in evals/).
L3 production — every trace turn carries prompt_version (content hash), so
   Langfuse/LangSmith can: manage prompts (load_policy() is the single adapter
   seam to swap file→service), build eval datasets from real traces, run judge
   samples, and correlate regressions to the exact prompt version. Prompts are
   data (prompts/policy.md, hot-reloaded per turn like personas) — the same
   property serves requirement 8 (non-dev edits) and eval tooling (versioning).
REQUIREMENT CLARIFICATION anchor: cite the 24% cancelled/returned revenue example
as what L2 value assertions exist to catch. -->

### 3.7 Observability

<!-- TODO: metrics — turn success rate, first-attempt SQL validity, retries/turn,
tokens+cost/turn, p95 latency, refusal rate, PII-mask hits, delete-confirm rate;
trace_id-linked structured logs → LangSmith/OTel; deep-dive debugging story. -->

### 3.8 Agility — persona management

<!-- TODO: prompts as data (personas table, hot-reload per turn, /persona command);
assembly order — immutable safety policy first, persona is additive style only. -->

## 4. Production topology & cloud services

<!-- TODO: GCP-default rationale (data gravity); Cloud Run service, Cloud SQL/pgvector,
GCS, Secret Manager, read-only BigQuery IAM service account; LLM gateway layer
(LiteLLM/OpenRouter) — llm.py is its single-process stand-in; model right-sizing. -->

## 5. Data flow

<!-- TODO: one query turn end-to-end; optional mermaid sequenceDiagram. -->

## 6. Error handling matrix

<!-- TODO: failure mode × detection × response × user experience table. -->

## 7. Prototype → production map

| Prototype stand-in | Production component |
|---|---|
| CLI REPL | API service (Cloud Run) + web/Slack clients |
| SQLite app store | Cloud SQL (Postgres), pgvector for the bucket |
| `llm.py` per-role model config | LLM gateway (LiteLLM / OpenRouter) — provider switch via config |
| `golden_examples.json` few-shots | Golden bucket: GCS + vector index + hybrid retrieval |
| JSON trace logs | LangSmith / OTel + dashboards + alerting |
| `--user` flag | SSO / IAM identity |
