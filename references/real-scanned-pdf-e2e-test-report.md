# Real Scanned PDF Adaptive Pipeline Report

Status: sanitized representative-document evidence
Date: 2026-07-05

## Purpose

This report records public-safe findings from a local representative scanned-PDF field
trial. Raw source documents, service endpoints, task upload copies, and run roots are
kept outside the public repository.

The sample was a small scanned Chinese product PDF with images, HTML tables, page-like
layout, and Chinese headings after OCR. The run used a local MinerU FastAPI service and
the formal adaptive pipeline path.

## Environment Summary

| Item | Public-safe value |
| --- | --- |
| Operating system | Ubuntu Linux |
| GPU class | NVIDIA Blackwell-class desktop GPU |
| CUDA generation | CUDA 12.x |
| MinerU version | 3.2.1 |
| MinerU API type | FastAPI task API |
| Source class | scanned/image-backed Chinese PDF |
| Source size | about 1 MB |
| Page count | 5 pages |

## Command Shape

The representative run used this sanitized command shape:

```bash
convert.py adaptive \
  --input <source.pdf> \
  --output <handoff-root> \
  --backend mineru-fastapi \
  --mineru-base-url <mineru-fastapi-base-url> \
  --mineru-language ch \
  --adaptive-policy table-atomic \
  --postprocess-profile chunk-markers-dense \
  --table-quality standard \
  --mineru-fastapi-backend pipeline \
  --mineru-asset-mode markdown_assets
```

The related decision-only regression shape pins the explicit backend while requesting
high table quality:

```bash
convert.py adaptive \
  --input <source.pdf> \
  --output <handoff-root> \
  --backend mineru-fastapi \
  --mineru-language ch \
  --adaptive-policy table-atomic \
  --table-quality high \
  --mineru-fastapi-backend pipeline \
  --decision-only
```

## Observed Results

| Check | Result |
| --- | --- |
| MinerU service health | available |
| Full adaptive pipeline exit code | 0 |
| Runtime | about 18 seconds |
| Effective MinerU FastAPI backend | `pipeline` |
| Saved image assets | 21 |
| Markdown image references | 15 semantic local references |
| HTML tables | 6 |
| Markdown characters | about 12k |
| Chunk markers | 32 |
| Chunk markers inside HTML tables | 0 |
| Quality gate | `PASS_WITH_REVIEW` |
| Ingest readiness | `ready_with_review` |

## Review Findings

The run supports these conclusions:

- explicit `--mineru-fastapi-backend pipeline` must be preserved when the user supplies
  it, even if `--table-quality high` is also present;
- scanned/low-text PDF detection should raise conversion confidence to review level;
- postprocess chunk markers can preserve HTML table blocks for this sample;
- raw binary PDF preview text must not be trusted as English language evidence;
- postprocess-sensitive quality metrics must be computed from the final postprocessed
  Markdown.

The remaining review items are expected for scanned-PDF OCR output:

- all six HTML tables required header review;
- two tables had suspected column alignment issues;
- one table was large enough to require parent-chunk review;
- some saved image assets had no stable semantic filename source and retained safe
  opaque names in sidecars.

## Public Hygiene

Do not commit the raw run root, source PDF, uploaded task copies, private service URL,
task IDs, or host paths. Public summaries may retain only sanitized metrics like the
counts and statuses above.
