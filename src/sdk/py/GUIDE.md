# Langboard Python SDK guide

## Install and choose a transport

Python 3.12 or later is required. From a reviewed repository checkout:

```sh
python -m pip install ./src/sdk/py
```

For a deployed application, use a reviewed wheel and pin its digest. The
[README distribution section](README.md#verified-ci-distribution) explains the
CI artifact and provenance checks. This package is not yet published to PyPI;
`pip install langboard-sdk` is not a supported distribution claim.

The SDK has no runtime dependencies. Install your chosen transport separately:

```sh
python -m pip install httpx       # native REST management
python -m pip install fastmcp     # native MCP work commands
```

`HttpTransport` accepts an already authenticated async HTTP client.
`McpTransport` accepts an already connected MCP client. Neither owns login,
token refresh, OAuth persistence, cookies, client shutdown or server-side roles.
Use the deployment's supported authentication flow. Do not construct identities
or use provider tokens as Langboard API credentials. Some deployments require
both an API access token and the associated refresh session cookie; reuse that
authenticated session. OAuth support on the MCP transport does not imply that
the same token has the REST API audience.

## Board App management

The native API origin is separate from the UI origin in some deployments.
Use the API origin supplied by your administrator; no company URL is built in.

```python
import asyncio
import httpx
from langboard_sdk import AppManager, HttpTransport, WorkflowStage

async def manage(api_origin, authenticated_headers, project_uid, selected_active_column_uid):
    async with httpx.AsyncClient(
        base_url=api_origin, headers=authenticated_headers,
        timeout=30, follow_redirects=False,
    ) as session:
        apps = AppManager(HttpTransport(session), project_uid)
        catalog = await apps.catalog()
        snapshot = await apps.workflow("github")
        if snapshot["binding"] is None:
            snapshot = await apps.prepare_workflow("github")

        # Show choices to the user. Resolve missing/ambiguous columns explicitly.
        # Use a column UID from this board, not a translated name.
        mapping = {WorkflowStage.ACTIVE: selected_active_column_uid}
        saved = await apps.save_workflow(
            "github", snapshot["binding"]["uid"],
            snapshot["binding"]["revision"], mapping,
            enable_transitions=False,
        )
        reread = await apps.workflow("github")
        assert reread["binding"]["revision"] == saved["binding"]["revision"]
```

`selected_active_column_uid` represents the user's choice. A complete mapping
must satisfy every required type returned by the server before transitions can
be enabled. A saved draft may be incomplete with transitions disabled.
`mapping=None` asks the host to resolve current saved/default choices;
`mapping={}` clears explicit choices. The host remains authoritative.

The SDK exposes only Langboard's built-in `WorkflowStage` enum. An app declares
`WorkflowRequirements` using those types. It must not create app-owned stages.
Names, translations, policy, activation and board-column eligibility are managed
by the host registry. Multiple columns with one type require an explicit choice.

To disable a board binding, first read its current UID and revision:

```python
current = await apps.workflow("github")
result = await apps.disable(
    "github", current["binding"]["uid"], current["binding"]["revision"]
)
assert result["state"] == "disabled"
```

Disabling a binding revokes the board's capabilities and transition enablement.
It does not delete the external provider's installation, delete a credential,
or erase historic signals. Read back before claiming completion.

## Instance connections and resource selection

GlitchTip and Dokploy expose native instance connection contracts. GitHub uses
installation OAuth and repository deltas, so this connection manager is not a
GitHub installation client. No unsupported route is silently substituted.

```python
from langboard_sdk import GlitchTipProject, DokployResource

connections = apps.connections("glitchtip", selection_collection="projects")
input_request = await connections.request_secret_input()
# Open input_request["input_url"] for the user to enter the provider token.
# Later, explicitly poll input_request["input_uid"]; no SDK polling loop.
status = await connections.secret_input_status(input_request["input_uid"])
if status["state"] != "completed":
    raise RuntimeError("Secret input is not completed")

connection = await connections.create(instance_url, status["secret_ref"])
page = await connections.discover(connection["connection_uid"], organization="org")
selected = await connections.select(
    connection["connection_uid"], connection["revision"],
    GlitchTipProject(organization="org", project_slug="selected-project"),
)
current = await connections.selected(connection["connection_uid"])
assert any(item["resource_uid"] == selected["resource_uid"] and item["selected"]
           for item in current["items"])
```

The instance must satisfy the host's configured external-address policy. Raw
tokens and DSNs are never accepted as `credential_reference`; use the canonical
`secret://ref/<uid>` returned by Langboard. A DSN is for error ingestion, not
provider metadata authorization. Provider credential visibility can be broader
than the selected board resource; selection is not provider-side isolation.

For Dokploy:

```python
connections = apps.connections("dokploy", selection_collection="selected")
page = await connections.discover(connection_uid, external_project_id="project")
result = await connections.select(
    connection_uid, current_connection_revision,
    DokployResource(
        resource_type="application", external_id="application",
        external_project_id="project", environment_id="environment",
    ),
)
```

On reselection, supply `expected_resource_revision` from the current stored
resource. One board may select multiple resources from multiple connections;
retain both identities. Pages are bounded. Use `list(after=next_cursor)` or
`selected(connection_uid, after=next_cursor)` explicitly. GlitchTip discovery
uses `cursor`; Dokploy discovery uses project/environment filters.

To remove a selection and disconnect:

```python
removed = await connections.remove(connection_uid, resource_uid, access_revision)
assert removed["selected"] is False
current = await connections.list()
# Resolve the exact connection from the bounded page; follow its cursor if needed.
record = next(item for item in current["items"] if item["connection_uid"] == connection_uid)
disconnected = await connections.disconnect(connection_uid, record["revision"])
assert disconnected["state"] == "disconnected"
```

The selected-resources endpoint includes previously deselected entries with
`selected=false`. Do not treat every entry as active. Disconnect retains audit
history and does not delete the provider's data or native SecretRef. Disconnected
connections are excluded from the active connection list; the receipt reports
`state=disconnected`.

## Native MCP work commands

```python
from fastmcp import Client
from langboard_sdk import LangboardClient, McpTransport

async with Client(mcp_url, auth="oauth") as session:
    board = LangboardClient(McpTransport(session))
    context = await board.get_connection_context(project_uid)
    preview = await board.preview_work_plan(plan)
    # Keep the exact plan, reviewed revision and stable request ID together.
    receipt = await board.apply_work_plan(plan, preview["revision"], request_id)
```

OAuth requires the server's opt-in OAuth endpoint. An extension catalog only
selects host-owned commands; it cannot supply a principal, repository or role
override. Host developers can use
`langboard.mcp_integration.Extensions.create_native_extension_provider` with
the native wrapper and authentication middleware. This server API is separate
from the standalone client package. It is trusted command composition, not a
sandbox for arbitrary plugin code. Existing card presentation and atomic work
plan examples are in [README.md](README.md).

## Error handling and recovery

| Result | Action |
|---|---|
| `NativeApiError` 401 | Restore the caller's authenticated session. |
| 403 or masked 404 | Re-read current board/member/binding rights; do not bypass. |
| 409 | Fetch the current revision and review the changed state before a new write. |
| Other 4xx | Correct the request using the native server schema. |
| `MutationOutcomeUnknown` | Read back current state; never automatically repeat the mutation. |
| `NativeCommandError` | Inspect its native result and current state; it is not a retry instruction. |

Transport exceptions and 5xx after a write can leave its outcome unknown.
No automatic retry, redirect, token refresh or cursor traversal is performed.
Do not install a retrying underlying HTTP transport. Error messages omit native
payloads; structured error details remain available on `NativeApiError.result`.
Treat those details as potentially sensitive when logging. Cancellation remains
under the caller's control.

## Support and verification boundaries

| Surface | Supported now |
|---|---|
| Common App management | Catalog, workflow inspect/prepare/save, binding disable |
| Native instance connections | List/create/discover/select/remove/disconnect, secret-input request/status |
| Work commands | Work-plan preview/apply, card presentation, bounded resource context |
| Common types | Built-in workflow types and typed provider resource selections |
| Provider registration | Host-installed manifests; no client-side plugin upload/install API |
| GitHub installation OAuth | Existing native UI/API; not covered by `ConnectionManager` |
| Signal refresh/webhook setup | Existing native UI/API; not covered by this client yet |
| Global settings/admin, complete board/card CRUD | Not claimed by this SDK version |

Standalone SDK tests require only Python. Native HTTP integration tests exercise
the real authentication middleware and database, with external provider traffic
mocked. Deployment acceptance, real provider calls and production OAuth remain
separate gates. The SDK's API responses are native dictionaries so unknown
additive server fields are retained; identifiers/revisions are not invented.
