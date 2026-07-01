# Post-CLI Adapter Planning

Status: planning gate
Date: 2026-07-01

## Objective

Choose the next post-CLI adapter only after ranking concrete host workflows, release
impact, testability, and operational risk. The portable archive CLI path is already the
stable public baseline; adapters must extend that baseline without making daemon, package
manager, model-provider, or web-service assumptions mandatory.

## Decision Principles

- Preserve the current CLI archive release as the default supported path.
- Keep the first adapter slice no-network and deterministic.
- Add a public surface only when it has a clear host workflow and release gate.
- Do not make long-running services, package installation, hosted conversion, local model
  services, or web servers required for existing skills.
- Keep live RAGFlow mutation and script-owned LLM/RAGAS execution on their existing gated
  tracks.

## Candidate Matrix

| Candidate | Primary user value | Risk | Testability | Release impact | Current recommendation |
| --- | --- | --- | --- | --- | --- |
| Wheel packaging | Easier install for platforms that support Python packages | Low | High: build/install/import smoke in temp venv | Adds package artifact, no command behavior change | Best first implementation slice if distribution friction is the problem |
| `ragflow-query serve` | Local HTTP/tool endpoint for OpenClaw/Hermes-style integration | Medium | Medium: local server smoke, lifecycle and port handling | Adds optional long-running mode; must stay disabled by default | Design next, implement only for a real host workflow |
| Remote conversion client | Integrate user-owned conversion services behind `ragflow-doc-to-md` | Medium | High with fake server fixtures | Adds backend behavior and config surface | Useful when a reachable converter exists; keep no default endpoint |
| Provider abstraction | Normalize model/embedding/rerank provider contracts | Medium | Medium with fake adapters | Adds adapter contracts and compatibility burden | Plan after a concrete provider integration is needed |
| Reranker adapter | Improve retrieval ranking with optional external rerank service | Medium-high | Medium with saved query fixtures and fake adapter | Affects query quality surfaces; must preserve direct retrieval defaults | Defer until route/fusion users need it |
| Web/API wrapper | Hosted UI/API around the suite | High | Medium-low without product requirements | Creates new deployment surface | Defer until product workflow is defined |

## Recommended Track

Start with a docs-and-test design for wheel packaging unless the user explicitly chooses a
host workflow that needs `ragflow-query serve`.

Wheel packaging is the lowest-risk first adapter because it can be validated offline:

- build a local wheel/sdist for `ragflow-skill-runtime`;
- install into a clean temporary virtual environment;
- run import and CLI bootstrap smoke without editable installs;
- keep public skill archives unchanged unless a later release explicitly publishes wheels.

`ragflow-query serve` should be treated as the second candidate. It has higher integration
value, but the design must settle lifecycle, port selection, auth boundary, request/response
schemas, shutdown behavior, and no-network defaults before implementation.

## Phase 37.1: Wheel Packaging Design Gate

Planned outputs:

- A packaging design section that decides wheel scope: runtime-only first, public skill
  entrypoints later.
- A no-network wheel build/install smoke command.
- A release-governance rule that wheel artifacts are optional and do not replace public
  skill archives.
- Focused tests that prove no editable install is required.

Exit criteria:

- Existing archive release gates remain green.
- Wheel smoke runs in a clean temporary environment.
- No new runtime dependency or host daemon is required.
- Public skill behavior remains unchanged.

## Phase 37.2: Serve Design Gate

Planned outputs:

- A `ragflow-query serve` contract draft with health, direct query, host-assisted query,
  and shutdown endpoints.
- A local-only fake-client smoke plan with ephemeral port handling.
- Redaction and trace rules for request/response logs.
- A clear statement that `serve` is optional and never required by release artifacts.

Exit criteria before implementation:

- A real host workflow needs the local service wrapper.
- Request and response schemas are stable enough for tests.
- Server lifecycle can be exercised without live RAGFlow.
- The default CLI path stays unchanged.

## Deferred Tracks

- Remote conversion client: start only when a user-owned converter endpoint and fixture
  shape are known.
- Provider abstraction: start only when at least one concrete provider contract is needed.
- Reranker adapter: start only after saved-query or benchmark fixtures define acceptance.
- Web/API wrapper: start only with a product workflow, auth model, and deployment target.
