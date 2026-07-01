# Post-CLI Adapter Planning

Status: planning gate; Phase 37.3 adapter intake gate documented
Date: 2026-07-02

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
| Wheel packaging | Easier install for platforms that support Python packages | Low | High: build/install/import smoke in a temp venv or isolated target install | Adds package artifact, no command behavior change | Best first implementation slice if distribution friction is the problem |
| `ragflow-query serve` | Local HTTP/tool endpoint for OpenClaw/Hermes-style integration | Medium | Medium: local server smoke, lifecycle and port handling | Adds optional long-running mode; must stay disabled by default | Design gate complete; implement only for a real host workflow |
| Remote conversion client | Integrate user-owned conversion services behind `ragflow-doc-to-md` | Medium | High with fake server fixtures | Adds backend behavior and config surface | Useful when a reachable converter exists; keep no default endpoint |
| Provider abstraction | Normalize model/embedding/rerank provider contracts | Medium | Medium with fake adapters | Adds adapter contracts and compatibility burden | Plan after a concrete provider integration is needed |
| Reranker adapter | Improve retrieval ranking with optional external rerank service | Medium-high | Medium with saved query fixtures and fake adapter | Affects query quality surfaces; must preserve direct retrieval defaults | Defer until route/fusion users need it |
| Web/API wrapper | Hosted UI/API around the suite | High | Medium-low without product requirements | Creates new deployment surface | Defer until product workflow is defined |

## Validated Host Workflow

Concrete workflow used for the current priority decision:

- A user gives the release archives or repository checkout to a controllable CLI agent such
  as Hermes, OpenClaw, Claude Code, or opencode.
- The host agent reads the public skill docs, prepares local config from user-provided
  RAGFlow/MinerU settings, and runs one-shot CLI commands that produce handoff artifacts.
- The host can preserve artifact paths between steps and can pass config through files,
  environment variables, or explicit CLI flags.

Decision:

- Keep the archive CLI path canonical. It has no daemon lifecycle, port allocation,
  shutdown, auth boundary, or background-log redaction problem, and it already matches the
  Hermes/OpenClaw/Claude Code/opencode handoff model.
- Keep runtime wheel packaging as an optional adapter gate. It helps hosts that can install
  Python packages or want to verify non-editable runtime installation, but it does not
  replace vendored runtime archives.
- Do not implement `ragflow-query serve` yet. A local service wrapper becomes justified
  only when a real host cannot efficiently spawn CLI commands, needs a persistent tool
  endpoint, or has request/response lifecycle requirements that the current artifact-based
  CLI cannot satisfy.
- Keep remote conversion, provider abstraction, reranker adapter, and web/API wrapper
  deferred until their endpoint/provider/fixture shapes are known.

## Recommended Track

The validated near-term track is runtime wheel packaging first, unless the user explicitly
chooses a host workflow that needs `ragflow-query serve`.

Wheel packaging is the lowest-risk first adapter because it can be validated offline:

- build a local wheel/sdist for `ragflow-skill-runtime`;
- install into a clean temporary venv or isolated target directory;
- run import and CLI bootstrap smoke without editable installs;
- keep public skill archives unchanged unless a later release explicitly publishes wheels.

`ragflow-query serve` is the second candidate after the wheel gate. It has higher
integration value, but implementation remains gated: the service contract is now defined,
while service code should start only when a host workflow needs a persistent local endpoint
instead of one-shot CLI commands.

## Phase 37.1: Wheel Packaging Design Gate

Implementation status: complete for the runtime-only design gate.

Wheel packaging starts with `ragflow-skill-runtime` only. Public skill archives remain the
canonical release artifact because they vendor the runtime and work without package
installation. Runtime wheel export is optional; public skill entrypoints, console scripts,
and package-index publication stay out of scope until a target platform explicitly needs
package-manager installation.

Implemented outputs:

- A packaging design section that decides wheel scope: runtime-only first, public skill
  entrypoints later.
- A no-network wheel build/install smoke command:
  `python3 tools/wheel_packaging_smoke.py --work-dir /tmp/ragflow-wheel-smoke --overwrite`.
- A no-network runtime wheel export command that copies only a smoke-validated wheel and
  emits `ragflow_runtime_wheel_export_v1`:
  `python3 tools/export_runtime_wheel.py --output-dir /tmp/ragflow-runtime-wheel-export --work-dir /tmp/ragflow-runtime-wheel-work --overwrite`.
- A release-governance rule that wheel artifacts are optional and do not replace public
  skill archives.
- Focused tests that prove no editable install is required:
  `packages/ragflow-skill-runtime/tests/test_wheel_packaging_smoke.py` and
  `packages/ragflow-skill-runtime/tests/test_export_runtime_wheel.py`.

The smoke command builds with `pip wheel --no-index --no-deps --no-build-isolation`, then
installs the produced wheel without an index and imports `ragflow_skill_runtime` from the
installed location. It prefers a temporary venv when `python3-venv` is available. On
minimal Ubuntu hosts without `ensurepip`, it falls back to `pip install --target` plus
`python -I` with an explicit temporary `sys.path` entry, which still avoids editable
installs and user-site imports during the runtime import smoke.

Exit criteria:

- Existing archive release gates remain green.
- Wheel smoke runs in a clean temporary environment.
- No new runtime dependency or host daemon is required.
- Public skill behavior remains unchanged.

Validation record (2026-07-01):

- `python3 tools/wheel_packaging_smoke.py --work-dir /tmp/ragflow-wheel-smoke-phase37-final --overwrite`
  passed. The current Ubuntu host lacks `python3-venv`, so the smoke used the isolated
  `--target` fallback and imported `ragflow_skill_runtime-0.1.0` from the installed wheel.
- `python3 tools/export_runtime_wheel.py --output-dir /tmp/ragflow-runtime-wheel-export --work-dir /tmp/ragflow-runtime-wheel-work --overwrite`
  passed and exported the smoke-validated runtime wheel plus `runtime-wheel-manifest.json`.
- The full offline release-facing chain passed after the Phase 37.1 wheel gate:
  `python3 -m pytest packages/ragflow-skill-runtime/tests -q`,
  `git diff --check`, `python3 tools/manifest_schema_check.py`,
  `python3 tools/release_hygiene_check.py`, `python3 tools/build_release.py --check`,
  `python3 tools/export_release_archives.py`,
  `python3 tools/consumer_acceptance.py --work-dir /tmp/ragflow-consumer-acceptance-20260701-phase37 --overwrite`,
  and `python3 tools/platform_smoke_matrix.py --profile strict-vendor-env --work-dir /tmp/ragflow-platform-strict-vendor-20260701-phase37`.

## Phase 37.2: Serve Design Gate

Implementation status: complete for the design gate only. No `serve` command, daemon,
HTTP listener, or background process is implemented by this phase.

Host workflow assumption:

- A controllable local host agent can already run one-shot CLI commands.
- A future service wrapper is useful only if that host needs repeated local tool calls,
  explicit health checks, or request/response lifecycle semantics that are awkward to
  express through process spawning and artifact paths.
- The first implementation must stay local-only, optional, no-network by default in tests,
  and compatible with the existing `ragflow-query ask` output shape.

Host workflow intake:

Before opening a `serve` implementation, record a concrete host workflow with enough
detail to prove that the one-shot CLI path is the wrong shape. Unanswered intake fields do
not block design discussion, but they do block service code.

| Field | Required evidence |
| --- | --- |
| Target host | Name the host surface, such as Hermes, OpenClaw, Claude Code, opencode, or a product-owned wrapper, and identify who owns process lifecycle. |
| CLI insufficiency | Explain which part of the current one-shot CLI handoff fails: process startup cost, repeated tool calls, health checks, request correlation, state reuse, artifact handoff, timeout handling, or another concrete constraint. |
| Request profile | Estimate expected request volume, concurrency, latency expectations, and whether requests are interactive, batch, or host-triggered background work. |
| Configuration and auth | Describe how RAGFlow endpoint, API key, dataset IDs, local bearer token, and optional config files are supplied without logging secrets. |
| Artifact and trace handling | Define whether responses are enough on stdout/HTTP, whether trace files must be written, and which host consumes those artifacts. |
| Lifecycle ownership | State who starts the process, how the port is discovered, how shutdown happens, and how stale processes are detected. |
| Security and redaction | List required log, trace, request, response, and config redaction expectations, including token handling and private endpoint/path handling. |
| Success criteria | Define the smallest endpoint subset, fake-client smoke result, consumer acceptance behavior, and platform smoke behavior needed to call the host workflow supported. |
| Failure criteria | Define what makes `serve` unacceptable for the host, such as leaked secrets, port conflicts, incomplete shutdown, missing direct-query parity, or unsupported host-assisted evidence shape. |

Non-goals:

- Do not replace the canonical archive CLI path.
- Do not add a hosted API, web UI, remote auth model, service supervisor, or public daemon
  requirement.
- Do not introduce script-owned LLM synthesis.
- Do not perform live RAGFlow mutation from `serve`.

Local service contract draft:

| Endpoint | Method | Purpose | Request | Response |
| --- | --- | --- | --- | --- |
| `/health` | `GET` | Check local server readiness. | None. | `{"ok": true, "schema": "ragflow_query_serve_health_v1", "version": "...", "uptime_ms": ...}` |
| `/v1/query/direct` | `POST` | Execute the same retrieval path as `ragflow-query ask --mode direct`. | `question`, one of `dataset_ids`/`kb_manifest`/`routing_config`, optional `top_k`, `similarity_threshold`, `retry_budget`, `include_trace`. | Existing `ask` JSON payload plus `served_by`, `request_id`, and no raw secrets. |
| `/v1/query/host-assisted` | `POST` | Execute `ask --mode agentic --host-assisted` without script-owned synthesis. | Direct-query fields plus optional `max_subqueries`, `rewrite`, `fusion`, and citation requirements. | Existing host-assisted payload with evidence, plan, trace, and host synthesis contract. |
| `/shutdown` | `POST` | Stop a local ephemeral server in smoke tests or host-managed runs. | Optional `request_id`. | `{"ok": true, "schema": "ragflow_query_serve_shutdown_v1"}` before orderly shutdown. |

Lifecycle and binding rules:

- Default bind address must be `127.0.0.1`.
- Default port should be `0` for an ephemeral OS-selected port in tests and smoke runs;
  user-supplied fixed ports are allowed only through explicit CLI flags.
- Startup output must include a local endpoint, process ID, and config source summary,
  with secrets redacted.
- Shutdown must be explicit through `/shutdown`, signal handling, or parent-process exit.
- A future implementation should support a foreground mode first; background supervision
  belongs to the host, not to public skill release artifacts.

Auth and redaction rules:

- Localhost-only smoke may run without auth when using an ephemeral port.
- Any non-ephemeral or non-test mode must support an explicit bearer token or equivalent
  local secret supplied by the host; the token must never appear in logs or traces.
- Request logs may include route, mode, status, timing, and request IDs, but not API keys,
  bearer tokens, full config paths, raw private endpoints, or full retrieved chunk text.
- Responses should reuse existing sanitizer sidecars when reports are written to disk.

No-network fake-client smoke plan:

1. Start `ragflow-query serve --base-url https://ragflow.example.test --api-key test-key`
   on `127.0.0.1:0` with a fake `RAGFlowClient`.
2. Read the startup JSON to discover the ephemeral port.
3. Call `/health` and assert schema, version, uptime, and `ok`.
4. Call `/v1/query/direct` and assert it matches `ask --mode direct` JSON semantics,
   including retrieval status and runtime resilience blocks.
5. Call `/v1/query/host-assisted` and assert no script-owned LLM call is made; returned
   evidence, plan, trace, and host synthesis contract remain audit-compatible.
6. Call `/shutdown` and assert the process exits cleanly without leftover listeners.
7. Verify generated logs and optional trace files pass redaction checks.

Implementation acceptance checklist:

The `serve` command can be marked implemented only when all of these are true:

- An approved host workflow intake is recorded in this document or a linked design note.
- The MVP endpoint subset is selected explicitly; it may be `/health` plus one query
  endpoint before the full draft contract is implemented.
- Fake-client tests cover startup, health, direct query, host-assisted query when in
  scope, shutdown, invalid auth, and port-conflict behavior.
- Local smoke starts on `127.0.0.1` with an ephemeral default port and exits without
  leftover listeners.
- The implementation does not perform live RAGFlow mutation and does not introduce
  script-owned LLM synthesis.
- Any non-test or fixed-port mode requires an explicit local auth secret, and logs/traces
  never expose bearer tokens, API keys, raw private endpoints, full config paths, or full
  retrieved chunk text.
- HTTP responses preserve the existing `ragflow-query ask` semantics so CLI and service
  results can be compared with neutral fixtures.
- Release hygiene covers generated logs/traces, consumer acceptance covers the documented
  optional surface, and strict-vendor platform smoke is updated before closing the command
  implementation.

Implementation gate:

- Open a code implementation only after a host workflow confirms that one-shot CLI
  commands are insufficient.
- Add fake-client unit tests, local server smoke, release hygiene coverage for generated
  logs/traces, and strict-vendor platform smoke before marking the `serve` command itself
  complete.
- Keep `ragflow-query serve` out of default release examples until the optional surface is
  implemented and validated.

Validation record (2026-07-01):

- Design gate documented with endpoint, lifecycle, auth, redaction, no-network smoke, and
  implementation-gate requirements.
- The public release path is unchanged; no command behavior or release artifact was
  modified by this design gate.
- The full release-facing validation chain passed after the design gate:
  `python3 -m pytest packages/ragflow-skill-runtime/tests -q`, `git diff --check`,
  `python3 tools/manifest_schema_check.py`, `python3 tools/release_hygiene_check.py`,
  `python3 tools/build_release.py --check`, `python3 tools/export_release_archives.py`,
  `python3 tools/consumer_acceptance.py --work-dir /tmp/ragflow-consumer-acceptance-20260701-phase37-serve-design --overwrite`,
  and `python3 tools/platform_smoke_matrix.py --profile strict-vendor-env --work-dir /tmp/ragflow-platform-strict-vendor-20260701-phase37-serve-design`.

## Phase 37.3: Product Adapter Intake Gate

Implementation status: complete for the intake gate only. No remote conversion client,
provider abstraction, reranker adapter, web/API wrapper, hosted endpoint, or new daemon is
implemented by this phase.

Purpose:

- Turn the remaining post-CLI product adapters into concrete intake decisions instead of
  generic abstraction work.
- Require endpoint, provider, product, fixture, and acceptance evidence before code starts.
- Keep the portable archive CLI path green while optional adapters stay behind explicit
  go/no-go gates.

Common intake:

Before opening code for any remaining post-CLI product adapter, record these fields in
this document or a linked design note:

| Field | Required evidence |
| --- | --- |
| Adapter candidate | Name exactly one candidate: remote conversion client, provider abstraction, reranker adapter, or web/API wrapper. |
| Product or host workflow | Identify the consuming product, host agent, or operator workflow and the user-visible problem it solves. |
| Endpoint or provider contract | Provide the concrete API shape, protocol, auth method, request/response examples, error model, and timeout expectations. |
| Current gap | Explain why existing CLI commands, generic remote conversion, OpenAI-compatible config, `rerank-ab`, release archives, or runtime wheels are insufficient. |
| Configuration and auth | Describe config keys, environment variables, local secret handling, endpoint redaction, and default behavior when config is absent. |
| Offline fixtures | Define fake server, fake provider, saved query, benchmark, or product-workflow fixtures that validate behavior without network access. |
| Public surface impact | State whether the adapter changes a public command, adds a new optional flag, emits a new report, or remains outside public release artifacts. |
| Release acceptance | Name the unit, CLI, release hygiene, consumer acceptance, and platform smoke gates required before closing the implementation. |
| Non-goals | State what the adapter must not do, such as default hosted endpoints, live mutation, implicit model calls, daemon supervision, or private product references. |

Candidate-specific gates:

| Candidate | Go condition | Minimum implementation slice | No-go condition |
| --- | --- | --- | --- |
| Remote conversion client | A user-owned conversion endpoint has a known sync or async protocol, auth scheme, file/result format, and fake-server fixture. | Add one optional `ragflow-doc-to-md` backend or backend mode, no default endpoint, fake HTTP coverage, config/auth redaction, and preserved `doc_manifest.json` semantics. | The request is only "support remote conversion" without a concrete endpoint, or the existing generic remote/MinerU backends already cover the workflow. |
| Provider abstraction | A concrete non-OpenAI-compatible model, embedding, evaluator, or provider contract is needed and has deterministic fake-provider fixtures. | Add request/review artifacts, config validation, or read-only probe first; defer script-owned model calls until explicit LLM config and citation/redaction gates exist. | The goal is a broad provider interface without a named provider, fixtures, and downstream acceptance criteria. |
| Reranker adapter | Saved-query or benchmark fixtures show a ranking-quality workflow that cannot be handled by current retrieval, fusion, rewrite, or `rerank-ab` comparison alone. | Add a fake reranker contract, optional rerank execution path or stricter `rerank-ab` adapter mode, metrics comparison, and direct retrieval fallback. | There is no quality fixture, no expected metric movement, or the adapter would silently alter default `ask` behavior. |
| Web/API wrapper | A product workflow defines users, auth model, deployment target, lifecycle owner, and which CLI/report artifacts become API responses. | Start with a wrapper design or product-owned external service boundary; only add public-skill code if it can be optional, local/testable, and release-hygiene clean. | The request is a generic UI/API wish, or it would make hosted services, daemon management, or product auth mandatory for the portable suite. |

Priority guidance:

1. Remote conversion client is the best first code candidate only when a real converter
   endpoint exists because it can be fake-server tested without affecting query defaults.
2. Reranker adapter is the next candidate when saved-query or benchmark fixtures define
   ranking acceptance.
3. Provider abstraction should wait for a named provider contract; start with
   request/review or probe boundaries before any script-owned backend call.
4. Web/API wrapper should usually stay outside the public skill suite until product
   workflow, auth, lifecycle, and deployment responsibilities are known.

Remote conversion intake status (2026-07-02):

| Intake field | Current finding |
| --- | --- |
| Adapter candidate | Remote conversion client. |
| Product or host workflow | Current host-agent workflows still fit `ragflow-doc-to-md` one-shot CLI conversion. No separate product-owned conversion API has been identified. |
| Existing coverage | The suite already supports generic JSON remote conversion, MinerU Agent API task polling, synchronous multipart `/parse`, local MinerU CLI, backend probe, backend warmup, redaction sidecars, consumer acceptance coverage, and strict-vendor platform smoke coverage. |
| Current gap | No uncovered converter protocol is known yet. A new client would need a concrete contract not covered by the existing generic remote or MinerU backends, such as an async job protocol with different task URLs, custom multipart fields, signed upload/download flow, archive result package, or extra OCR/layout metadata contract. |
| Offline fixtures | Not ready. A future implementation must start with a fake server that covers success, HTTP error, timeout, malformed response, auth failure, and redacted reports. |
| Public surface impact | Not ready. The smallest likely impact would be one optional backend mode or a stricter protocol option on `ragflow-doc-to-md`; defaults must remain unchanged. |
| Gate decision | No-go for code implementation until a user-owned endpoint and fixture shape are recorded. Keep the existing `remote`, `mineru`, `mineru-sync`, and `mineru-cli` paths as the supported conversion adapters. |

Implementation acceptance checklist:

- A completed intake identifies one adapter, one concrete contract, and one owner workflow.
- Neutral offline fixtures cover success, timeout/error, auth failure, malformed response,
  and redaction behavior.
- Defaults preserve the current CLI/archive behavior when the adapter is not configured.
- No default hosted endpoint, real secret, private product name, or private path is added
  to public examples or release artifacts.
- Public command or report changes include focused tests plus release hygiene updates.
- Consumer acceptance and strict-vendor platform smoke are updated before marking the
  adapter implementation complete.

## Deferred Tracks

- Remote conversion client: start only when Phase 37.3 intake records a user-owned
  converter endpoint and fake-server fixture shape.
- Provider abstraction: start only when Phase 37.3 intake records at least one concrete
  provider contract and deterministic fake-provider fixtures.
- Reranker adapter: start only after Phase 37.3 intake records saved-query or benchmark
  fixtures that define ranking acceptance.
- Web/API wrapper: start only when Phase 37.3 intake records a product workflow, auth
  model, lifecycle owner, and deployment target.
