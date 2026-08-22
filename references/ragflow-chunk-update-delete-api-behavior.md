# RAGFlow Chunk Update and Document Delete API Behavior Notes

Observed against a local RAGFlow deployment during the 2026-08-22 curated
image-text update live validation. Treat these as deployment-behavior evidence, not
as guaranteed upstream contract; re-verify before relying on them elsewhere.

## Chunk content updates are not immediately readable

### Symptom

`curated-image-update` PUTs new chunk content, receives `code: 0`, and an immediate
`GET /datasets/{dataset_id}/documents/{document_id}/chunks` still returns the old
content. The new content becomes visible seconds later.

### Guidance

Always read back with retries instead of a single immediate GET. The
`curated-image-update` command polls the chunk list up to 10 times at
`--poll-interval` spacing and only then declares a read-back mismatch. A successful
`code: 0` PUT response alone is not proof that a subsequent read will observe the
new content.

## Document delete payload field differs by deployment

### Symptom

`DELETE /api/v1/datasets/{dataset_id}/documents` with `{"document_ids": [...]}`
is rejected with application code 101:

```
Field: <document_ids> - Message: <Extra inputs are not permitted>
```

The same endpoint accepts `{"ids": [...]}` and returns `{"code": 0, "data":
{"deleted": 1}}`.

### Guidance

The runtime's `delete_document` helper currently sends `document_ids`. Deployments
that reject it need an operator-attested capability adjustment or a payload change;
do not assume either field name is universal.

## Image parse rejects very small images

### Symptom

The picture parser fails for tiny images. The VLM backend rejected a 1x1 PNG with:

```
The image length and width do not meet the model restrictions.
[height:1 or width:1 must be larger than 10]
```

The document then ends with `run: DONE` but `chunk_count: 0` and a
`No chunk built` progress message, which the runtime classifies as a failed parse.

### Guidance

Fixtures and curated image-text assets must exceed the VLM minimum dimensions
(both sides larger than 10 pixels on the observed deployment). A 240x140 PNG
parsed successfully end to end.
