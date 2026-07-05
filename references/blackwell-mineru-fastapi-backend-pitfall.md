# Blackwell GPU + MinerU FastAPI Backend Pitfall

Status: observed compatibility warning
Date: 2026-07-05

## Summary

A representative local field trial observed MinerU FastAPI 3.2.1 failing when the
high-accuracy `hybrid-auto-engine` backend was selected on a Blackwell-class NVIDIA GPU.
The standard `pipeline` backend completed the same scanned-PDF conversion path.

Treat this as a versioned compatibility warning, not a permanent hardware rule. Re-test
high-accuracy backends when MinerU, CUDA, drivers, or backend probes change.

## Observed Failure

The high-accuracy backend failed during engine initialization and the client-facing task
remained processing or ended as failed before the conversion completed. A representative
error class was:

```text
Engine core initialization failed.
```

## Trigger Pattern

The risk is present when a run selects a high-accuracy MinerU FastAPI backend family, for
example:

- explicit `--mineru-fastapi-backend hybrid-auto-engine`;
- `--table-quality high` without an explicit compatible backend override;
- `--table-quality auto` when table candidate detection promotes to a high-accuracy
  backend.

## Safe Workaround

For affected hosts, explicitly pin the standard backend and use a standard table-quality
strategy unless a fresh backend warmup proves the high-accuracy path is healthy:

```bash
convert.py pipeline ... \
  --backend mineru-fastapi \
  --mineru-base-url <mineru-fastapi-base-url> \
  --mineru-fastapi-backend pipeline \
  --table-quality standard
```

When using adaptive mode, the user-specified FastAPI backend must be preserved:

```bash
convert.py adaptive ... \
  --backend mineru-fastapi \
  --mineru-base-url <mineru-fastapi-base-url> \
  --table-quality high \
  --mineru-fastapi-backend pipeline \
  --decision-only
```

The decision report should keep:

```json
{
  "recommendation": {
    "table_quality": "high",
    "mineru_fastapi_backend": "pipeline"
  }
}
```

## Verification

Use a small non-sensitive fixture before a representative document:

```bash
convert.py backend warmup \
  --backend mineru-fastapi \
  --mineru-base-url <mineru-fastapi-base-url> \
  --mineru-fastapi-backend pipeline \
  --fixture <fixture.pdf>
```

Successful workaround evidence should show:

- `runtime_report.json` records `mineru_fastapi_backend: pipeline`;
- the task completes without timeout;
- the quality report is not blocked by empty or missing Markdown;
- if chunk markers are used, postprocess and quality reports agree on marker counts.

## Follow-Up Rule

Do not hard-ban high-accuracy backends by GPU model alone. Prefer backend probe/warmup,
runtime failure classification, explicit user backend preservation, and fallback reports.
