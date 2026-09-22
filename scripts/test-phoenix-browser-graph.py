import asyncio
import json
import os
from hashlib import sha256
from pathlib import Path
from re import search as re_search
from typing import Any
from uuid import uuid4
from fastapi import File, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from langboard_graph.AppInstance import app
from langboard_graph.core.graph.default import nodes, tooling
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import StructuredTool


__all__ = ["app"]


original_call = tooling._call_api_tool
langflow_files: dict[str, dict[str, Any]] = {}


def require_langflow_api_key(value: str | None) -> None:
    expected = os.environ.get("PHOENIX_BROWSER_LANGFLOW_API_KEY")
    if not expected or value != expected:
        raise HTTPException(status_code=401)


@app.post("/api/v2/files")
async def upload_langflow_file(
    file: UploadFile = File(),
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> dict[str, str]:
    require_langflow_api_key(x_api_key)
    filename = file.filename or "attachment"
    if filename.startswith("concurrency-hold-"):
        await asyncio.sleep(2)
        raise HTTPException(status_code=503)

    content = await file.read()
    file_id = str(uuid4())
    path = f"diagnostic/{file_id}/{filename}"
    langflow_files[file_id] = {
        "id": file_id,
        "path": path,
        "filename": filename,
        "sha256": sha256(content).hexdigest(),
        "deleted": False,
    }
    return {"id": file_id, "path": path}


@app.delete("/api/v2/files/{file_id}", status_code=204)
async def delete_langflow_file(
    file_id: str,
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> None:
    require_langflow_api_key(x_api_key)
    record = langflow_files.get(file_id)
    if record is None:
        raise HTTPException(status_code=404)
    record["deleted"] = True


@app.get("/diagnostic/langflow/files")
async def get_langflow_files(
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> dict[str, list[dict[str, Any]]]:
    require_langflow_api_key(x_api_key)
    return {"files": list(langflow_files.values())}


@app.post("/api/v1/run/diagnostic")
async def run_langflow(
    body: dict[str, Any],
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> StreamingResponse:
    require_langflow_api_key(x_api_key)
    tweaks = body.get("tweaks")
    file_component = tweaks.get("LangboardFile") if isinstance(tweaks, dict) else None
    file_path = file_component.get("path") if isinstance(file_component, dict) else None
    record = next(
        (value for value in langflow_files.values() if value["path"] == file_path and value["deleted"] is False),
        None,
    )

    async def stream():
        if record is None:
            yield json.dumps({"event": "error", "data": {"message": "Attachment was not uploaded"}}) + "\n\n"
            return
        if str(body.get("input_value", "")).startswith("fail:"):
            yield json.dumps({"event": "error", "data": {"message": "Requested diagnostic failure"}}) + "\n\n"
            return
        if str(body.get("input_value", "")).startswith("hold:"):
            Path("/tmp/phoenix-held-langflow").write_text(record["filename"])
            while True:
                await asyncio.sleep(1)
        text = f"Attachment {record['filename']} received with SHA-256 {record['sha256']}"
        yield json.dumps({"event": "add_message", "data": {"sender": "AI", "text": text}}) + "\n\n"
        yield json.dumps({"event": "end", "data": {}}) + "\n\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


class DiagnosticChatModel:
    def bind_tools(self, _tools: list[StructuredTool]) -> "DiagnosticChatModel":
        return self


def create_diagnostic_chat_model(_agent_llm: str | None, _settings: dict[str, Any]) -> Any:
    return DiagnosticChatModel()


async def invoke_diagnostic_chat_model(_chat_model: Any, messages: list[BaseMessage]) -> BaseMessage:
    if any(isinstance(message, ToolMessage) for message in messages):
        return AIMessage(content="The requested card update has been processed.")

    prompt = "\n".join(message.content for message in messages if isinstance(message.content, str))
    hold_marker = os.environ.get("PHOENIX_BROWSER_HOLD_MODEL_MARKER")
    if hold_marker and hold_marker in prompt:
        Path("/tmp/phoenix-held-editor-model").write_text(hold_marker)
        async with asyncio.timeout(180):
            while not Path("/tmp/phoenix-release-editor-model").exists():
                await asyncio.sleep(0.1)

    match = re_search(
        r"card (?P<card>[0-9A-Za-z]{11}) in project (?P<project>[0-9A-Za-z]{11}) "
        r'to exactly "(?P<description>[^"]+)"',
        prompt,
    )
    if match:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "change_card_details",
                    "args": {
                        "project_uid": match.group("project"),
                        "card_uid": match.group("card"),
                        "form_description": {"content": match.group("description")},
                    },
                    "id": "diagnostic-change-card-details",
                    "type": "tool_call",
                }
            ],
        )

    return AIMessage(content="committed work remains recoverable.")


async def traced_call(api_name, schema, base_url, headers, variables, field_sources, kwargs):
    arguments = json.dumps(kwargs)
    before_marker = os.environ.get("PHOENIX_BROWSER_HOLD_BEFORE_TOOL_MARKER")
    if api_name == "change_card_details" and before_marker and before_marker in arguments:
        Path("/tmp/phoenix-held-before-tool").write_text(before_marker)
        async with asyncio.timeout(180):
            while not Path("/tmp/phoenix-release-before-tool").exists():
                await asyncio.sleep(0.1)
    result = await original_call(api_name, schema, base_url, headers, variables, field_sources, kwargs)
    parsed = json.loads(result)
    responses = parsed.get("responses", []) if isinstance(parsed, dict) else parsed
    if isinstance(responses, dict):
        responses = list(responses.values())
    summary = (
        [
            {
                "status": entry.get("status"),
                "message": entry.get("body", {}).get("message"),
                "skipped": entry.get("body", {}).get("skipped"),
                "title": entry.get("body", {}).get("card", {}).get("title"),
            }
            for entry in responses
            if isinstance(entry, dict)
        ]
        if isinstance(responses, list)
        else []
    )
    print(
        "PROBE_TOOL " + json.dumps({"name": api_name, "arguments": json.loads(arguments), "results": summary}),
        flush=True,
    )
    marker = os.environ.get("PHOENIX_BROWSER_HOLD_MARKER")
    if api_name == "change_card_details" and marker and marker in arguments:
        if not summary or any(entry["status"] != 200 for entry in summary):
            raise RuntimeError("The diagnostic edit did not succeed before the response barrier")
        Path("/tmp/phoenix-held-tool").write_text(marker)
        async with asyncio.timeout(180):
            while not Path("/tmp/phoenix-release-tool").exists():
                await asyncio.sleep(0.1)
    return result


tooling._call_api_tool = traced_call

if os.environ.get("PHOENIX_BROWSER_DETERMINISTIC_EDITOR_AI") == "true":
    nodes.create_default_chat_model = create_diagnostic_chat_model
    nodes._invoke_chat_model = invoke_diagnostic_chat_model
