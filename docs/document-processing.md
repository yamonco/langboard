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
