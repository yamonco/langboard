# Optional document processing

The API stores attachments and queues supported documents. Conversion runs in the
broker worker, whose image must install `document-processing`. The API itself
intentionally omits Docling; API-side package inspection must not disable a
separately provisioned worker. The repository compose configuration selects the
`with-document-processing` image target for that worker.

```sh
uv sync --locked --no-dev --extra document-processing
docker build --target with-document-processing -t langboard-document-worker .
```

A worker without Docling records a clear failed document-indexing state before
downloading the attachment or starting a converter. The attachment remains
stored and accessible. Installing the package does not silently retry prior
failures. A deployment without any worker cannot consume queued tasks; worker
availability and queue monitoring remain deployment responsibilities.

A loaded package is only a prerequisite. Conversion can still fail because of
invalid documents, parser dependencies, size limits, timeouts, or unavailable
resources. Existing metadata failure handling and temporary-file cleanup apply.
No company-specific runtime, identity service, or cloud storage is required by
this feature.

## Remote document vision

Docling remains the conversion engine and owns PDF rendering, page images,
Office/Web parsing, DoclingDocument construction, and Markdown export. PDF and
image inputs use its official `VlmPipeline` with `ApiVlmOptions`; only vision
inference runs at the configured OpenAI-compatible provider. Office/Web inputs
continue to use Docling's native format backends without a vision request.

In Settings → Internal AI, create a **Document Vision · document-vision** binding,
choose an OpenAI-compatible provider, set `base_url`, `model_name`, and its API key,
and select it as the default for that type. This global document binding is not
assigned to project chat bot lists. A model such as `glm-5.3-flash` is deployment
configuration, not a built-in vendor dependency. The endpoint must support images
and Chat Completions; text-only models cannot convert PDF/image pages.

Approve the exact provider base URL in `MODEL_PROVIDER_ALLOWED_BASE_URLS` on the
worker. This explicit deployment boundary also allows local Ollama, LM Studio,
or vLLM endpoints. The endpoint receives document images, so use only trusted
providers. The worker reads the binding from the existing internal AI store;
credentials are not passed in subprocess arguments. Missing bindings fail clearly
instead of falling back to downloading local inference weights. Partial/failed
conversion is not recorded as a successful document index.

The `document-processing` extra selects `docling-slim`'s conversion, PDF, Office,
and Web extras. It excludes `standard`, local model/OCR extras, Torch, torchvision,
CUDA/NVIDIA packages, and Docling IBM model weights. Transformers currently
provides import-time types required by the official VLM module; no local model
is loaded. CPU/RAM are still needed for rendering and parsing. Rebuild the worker
image to remove packages already installed by the old `standard` dependency;
applying source files alone does not shrink an existing container.

## Korean/CJK font fallback

The document worker image installs `fonts-noto-cjk` and `fontconfig`, refreshes
its font cache, and verifies a Korean font match during the build. This supplies
Korean, Japanese, and Chinese fallback glyphs when a PDF does not embed its
original font. It is scoped to the document worker, not every API image.
Embedded source fonts remain authoritative; installing fallback fonts cannot
repair already corrupted text mappings or glyphs saved into the source file.
Validate the page image sent to the model as well as the returned transcription.

### Deleted board fencing

Embedding tasks reject a deleted board before resolving providers. Publication
locks the current board before the card and attachment and refuses a deleted or
mismatched board. If deletion occurs during inference, publication fails and the
task removes its staged vectors; previously committed source history is retained.

### Optional converter upload regression

The optional-converter integration test runs with Docling genuinely absent. It
uses native JWT authentication, the HTTP upload endpoint, SQLite repositories,
and local file storage. An authenticated upload returns 201, preserves the file
and attachment, and emits one captured indexing task after commit. The native
worker records a failed conversion with installation guidance before downloading
the source; the attachment remains available. An unauthenticated request is 401.

The test substitutes card visibility and captures the Celery publisher. It does
not establish board ACL correctness, a live broker delivery, or deployed worker
readiness. Its PostgreSQL variant requires an available test database.

### Disabled retrieval editor

The retrieval form rejects submit events while disabled, before collecting its
fields or calling `onSave`. This also covers programmatic submit events, which
can bypass a disabled fieldset's buttons. The parent internal-bot editor and
server still apply their own current permission checks. The UI regression uses
a character splitter because disabled fields do not participate in FormData;
relying on separator validation to stop a disabled submission would leave that
mode unguarded. This guard does not establish deployed authorization behavior.

### Text-only SQLite embedding and explicit splitter reindex

The official `langgraph-checkpoint-sqlite` store uses `text_fields`, not `fields`,
to select indexed properties. Configure `text_fields: ["text"]` so only each
split chunk is embedded. The wrong option silently selects the entire serialized
record, adding source identifiers and metadata to inference input and diluting
the semantic content. Source metadata remains stored for filtering and readback.

The worker regression runs the actual snapshot resolver, LangChain splitter,
SQLite vector store and generation replacement. It indexes multilingual text
with a 128-character chunk limit, explicitly reindexes with a 64-character limit
under the same model fingerprint, and reopens the store to verify smaller chunks
and removal of the prior generation after publication. Later global model and
splitter edits do not change a queued request; credential rotation is retained.
Captured embedding input must equal persisted chunk text without source metadata.
The original transcription remains unchanged and duplicate delivery does not
repeat inference. Existing attachments are not automatically reindexed.

Inference is a recording test implementation and the metadata publication fence
is a test double. This establishes the local worker/splitter/store contract, not
live provider inference, PostgreSQL publication, broker delivery or deployed UI
acceptance. Previously indexed records require the user's explicit reindex action
to receive text-only vectors.

### Preserve readable vectors during reindex

An embedding pointer carries its own non-secret configuration snapshot in
`embedding.config`. The document's `embedding_config` describes the requested
next generation. Queuing explicit reindex preserves the previous pointer and
its settings; a successful worker publishes the new pointer and settings
together. Failure retains the prior pair. For older metadata without a pointer
snapshot, the explicit request captures the previous document configuration
before replacing it, and reads retain the legacy fallback.

Native document vector search resolves the pointer's settings, not the pending
request's new model or dimensions. It still rechecks current read permission,
attachment lifecycle, source generation, pointer/configuration equality,
provider endpoint and global retrieval enablement after querying. Retaining
old vectors never bypasses revocation or enables retrieval when switched off.
The local regression searches persisted vectors while the request is pending
or failed and rejects both flows when read permission is revoked during search.
Inference and ACL services are test doubles; PostgreSQL publication and live
provider acceptance remain separate gates.
