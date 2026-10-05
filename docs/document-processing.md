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
