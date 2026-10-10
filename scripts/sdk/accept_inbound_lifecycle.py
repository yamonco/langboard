"""Disposable native HTTP acceptance: no pytest fixtures or runtime patches."""

import asyncio
import importlib.util
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time


ROOT = pathlib.Path(__file__).resolve().parents[2]
EXAMPLES = pathlib.Path(os.environ["LANGBOARD_SDK_EXAMPLES_DIR"]).resolve()

if os.environ.get("SDK_ACCEPTANCE_SERVER") == "1":
    # Import native route modules for their registration side effects.
    for module in (
        "langboard.routes.board.BoardSettingApi",
        "langboard.routes.settings.AppRegistrySettingsApi",
        "langboard.routes.settings.AppCardCreationApi",
        "langboard.routes.settings.AppInboundConnectionApi",
        "langboard.routes.settings.AppConnectionCredentialApi",
    ):
        importlib.import_module(module)
    import uvicorn
    from fastapi import FastAPI
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity
    from langboard_shared.core.types import SafeDateTime, SnowflakeID
    from langboard_shared.domain.models import (
        Project,
        ProjectColumn,
        User,
        WorkflowStageDefinition,
    )
    from langboard_shared.Env import Env
    from sqlalchemy.orm import Session

    engine = DbEngine.get_main_engine()
    from langboard_shared.core.db import BaseDbModel
    from langboard_shared.helpers import ensure_models_imported
    from sqlalchemy import text

    ensure_models_imported()
    from sqlalchemy import inspect

    if engine.url.host not in ("127.0.0.1", "localhost") or inspect(engine).get_table_names():
        raise RuntimeError("Acceptance requires an empty disposable loopback PostgreSQL database")
    BaseDbModel.metadata.create_all(engine)
    with engine.begin() as db:
        db.execute(text("CREATE SEQUENCE content_change_seq"))
    with Session(engine, expire_on_commit=False) as db:
        actor = User(
            id=SnowflakeID(),
            firstname="Acceptance",
            lastname="Admin",
            email="admin@example.invalid",
            password="disposable-only",
            activated_at=SafeDateTime.now(),
            is_admin=True,
        )
        project = Project(id=SnowflakeID(), owner_id=actor.id, title="Independent SDK acceptance")
        db.add(actor)
        db.commit()
        db.add(project)
        db.commit()
        column = ProjectColumn(
            id=SnowflakeID(), project_id=project.id, name="Localized queue", workflow_stage="backlog"
        )
        stage = WorkflowStageDefinition(id=SnowflakeID(), key="backlog", name="Backlog", is_builtin=True)
        db.add_all([column, stage])
        db.commit()
    access, refresh = AuthSecurity.authenticate(actor.id)
    pathlib.Path(os.environ["SDK_ACCEPTANCE_AUTH"]).write_text(
        json.dumps(
            {
                "access": access,
                "refresh": refresh,
                "cookie": Env.REFRESH_TOKEN_NAME,
                "board": project.get_uid(),
                "column": column.get_uid(),
            }
        )
    )
    pathlib.Path(os.environ["SDK_ACCEPTANCE_AUTH"]).chmod(0o600)
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["SDK_ACCEPTANCE_PORT"]), log_level="warning")
    sys.exit()


async def acceptance(base, auth):
    import httpx
    from langboard_sdk import AppManager, AppRegistry, HttpTransport, NativeApiError

    spec = importlib.util.spec_from_file_location("external_issue", EXAMPLES / "external_issue.py")
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    source_spec = importlib.util.spec_from_file_location("inbound_source", EXAMPLES / "inbound_source.py")
    source = importlib.util.module_from_spec(source_spec)
    source_spec.loader.exec_module(source)
    async with httpx.AsyncClient(
        base_url=base,
        timeout=30,
        trust_env=False,
        headers={"Authorization": "Bearer " + auth["access"]},
        cookies={auth["cookie"]: auth["refresh"]},
    ) as client:
        transport = HttpTransport(client)
        registry = AppRegistry(transport)
        manager = AppManager(transport, auth["board"])
        declared = {
            "schema_version": 1,
            "key": "example-erp",
            "version": "1.0.0",
            "name": "Example ERP",
            "description": "Independent external issue service",
            "capabilities": ["resources.read", "cards.create", "cards.presentation"],
            "resource_types": ["project"],
            "workflow_requirements": {"required": ["backlog"], "optional": []},
        }
        approved = await registry.approve(declared)
        catalog_app = next(a for a in (await manager.catalog())["apps"] if a["key"] == "example-erp")
        assert catalog_app["inbound_connection_management"] is True
        prepared = await source.prepare_source(transport, auth["board"], "example-erp", approved["revision"])
        inbound = prepared["connection"]
        auth["connection"] = inbound["connection_uid"]
        workflow = prepared["workflow"]
        recovered = await source.list_sources(transport, "example-erp")
        assert recovered["items"] == [inbound] and recovered["next_cursor"] is None
        binding = workflow["binding"]
        saved = await manager.save_workflow(
            "example-erp", binding["uid"], binding["revision"], {"backlog": auth["column"]}
        )
        consent = await transport.request(
            "PUT",
            f"/board/{auth['board']}/settings/apps/example-erp/consent",
            json={
                "app_revision": approved["revision"],
                "binding_uid": binding["uid"],
                "expected_revision": saved["binding"]["revision"],
                "capabilities": declared["capabilities"],
            },
        )
        current = next(a for a in (await manager.catalog())["apps"] if a["key"] == "example-erp")["binding"]
        assert current["state"] == "enabled" and current["revision"] == consent["revision"]
        selected = await source.select_resource(
            transport,
            auth["board"],
            "example-erp",
            auth["connection"],
            app_revision=approved["revision"],
            binding_uid=binding["uid"],
            expected_revision=consent["revision"],
            resource_type="project",
            external_resource_id="erp-project",
        )
        resource_path = f"/board/{auth['board']}/settings/apps/example-erp/inbound-connections/{auth['connection']}/resources"
        resource_snapshot = await transport.request("GET", resource_path)
        assert resource_snapshot["binding_uid"] == binding["uid"]
        assert resource_snapshot["resource_types"] == ["project"]
        assert resource_snapshot["items"][0]["resource_uid"] == selected["resource_uid"]
        assert resource_snapshot["items"][0]["access_revision"] == selected["access_revision"]
        auth["resource"] = selected["resource_uid"]
        credential = await transport.request(
            "POST", f"/settings/apps/connections/{auth['connection']}/credentials", json={"expires_in_seconds": 3600}
        )
        credential_path = f"/settings/apps/connections/{auth['connection']}/credentials"
        receipts = await transport.request("GET", credential_path)
        assert receipts["items"][0]["credential_uid"] == credential["credential_uid"]
        assert "token" not in receipts["items"][0] and "token_hash" not in receipts["items"][0]
        temporary = await transport.request("POST", credential_path, json={"expires_in_seconds": 60})
        revoked = await transport.request("POST", f"{credential_path}/{temporary['credential_uid']}/revoke", json={})
        assert revoked["revoked"]
        recovered_receipts = await transport.request("GET", credential_path)
        assert next(item for item in recovered_receipts["items"] if item["credential_uid"] == temporary["credential_uid"])["revoked_at"]
        async with httpx.AsyncClient(
            base_url=base, timeout=30, trust_env=False, headers={"Authorization": "Bearer " + credential["token"]}
        ) as app_client:
            app_transport = HttpTransport(app_client)
            presentation = {
                "version": 1,
                "key": "app.example-erp.issue",
                "axis": "type",
                "name": "ERP issue",
                "description": "Issue reported by the independent ERP service.",
                "icon": "📋",
            }
            args = (app_transport, auth["board"], auth["resource"], "erp-issue-1", "ERP native HTTP issue")
            first = await example.create_issue(*args, description="Native PostgreSQL source", presentation=presentation)
            replay = await example.create_issue(
                *args, description="Native PostgreSQL source", presentation=presentation
            )
            assert first["created"] and not replay["created"] and first["card_uid"] == replay["card_uid"]
            assert replay["effects_state"] == "dispatched", replay
            updated = await registry.approve(
                {**declared, "version": "1.0.1", "description": "Independent external issue service, updated"},
                expected_revision=approved["revision"],
            )
            assert updated["generation"] == approved["generation"] + 1 and updated["is_enabled"]
            listed = next(a for a in await registry.list() if a["declaration"]["key"] == "example-erp")
            assert listed["revision"] == updated["revision"] and listed["declaration"]["version"] == "1.0.1"
            after_update = next(a for a in (await manager.catalog())["apps"] if a["key"] == "example-erp")
            assert set(after_update["binding"]["granted_capabilities"]) == set(declared["capabilities"])
            updated_replay = await example.create_issue(
                *args, description="Native PostgreSQL source", presentation=presentation
            )
            assert updated_replay["card_uid"] == first["card_uid"] and not updated_replay["created"]
            app_disabled = await registry.disable("example-erp", updated["revision"])
            assert not app_disabled["is_enabled"]
            assert not next(a for a in await registry.list() if a["declaration"]["key"] == "example-erp")["is_enabled"]
            try:
                await example.create_issue(*args, description="Native PostgreSQL source", presentation=presentation)
            except NativeApiError as exc:
                assert exc.status_code == 403
            else:
                raise AssertionError("Disabled app could replay source receipt")
            approved = app_disabled
            recovered = await source.list_sources(transport, "example-erp")
            inbound = recovered["items"][0]
            current = next(a for a in (await manager.catalog())["apps"] if a["key"] == "example-erp")["binding"]
            await transport.request(
                "PUT",
                f"/board/{auth['board']}/settings/apps/example-erp/consent",
                json={
                    "app_revision": approved["revision"],
                    "binding_uid": binding["uid"],
                    "expected_revision": current["revision"],
                    "capabilities": [],
                },
            )
            try:
                await example.create_issue(*args, description="Native PostgreSQL source", presentation=presentation)
            except NativeApiError as exc:
                assert exc.status_code == 403
            else:
                raise AssertionError("Revoked app could replay source receipt")
            disconnected = await transport.request(
                "POST",
                f"/settings/apps/inbound-connections/{auth['connection']}/disconnect",
                json={"expected_revision": inbound["revision"]},
            )
            assert disconnected["state"] == "disconnected"
            recovered = await source.list_sources(transport, "example-erp")
            assert recovered["items"] == [{**inbound, **disconnected}]
            try:
                await transport.request(
                    "POST",
                    f"/settings/apps/connections/{auth['connection']}/credentials",
                    json={"expires_in_seconds": 3600},
                )
            except NativeApiError as exc:
                assert exc.status_code == 403
            else:
                raise AssertionError("Disconnected connection issued credentials")
            print(
                json.dumps(
                    {
                        "native_http": True,
                        "created_once": True,
                        "same_card_replay": True,
                        "effects": replay["effects_state"],
                        "revocation_denied": True,
                        "inbound_connection_via_http": True,
                        "resource_selection_via_http": True,
                        "seeded_app_state": False,
                        "registry_update_readback": True,
                        "registry_disable_denied": True,
                    }
                )
            )


with tempfile.TemporaryDirectory(prefix="langboard-sdk-http-") as tmp:
    tmp = pathlib.Path(tmp)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    env = dict(
        os.environ,
        SDK_ACCEPTANCE_SERVER="1",
        SDK_ACCEPTANCE_PORT=str(port),
        SDK_ACCEPTANCE_AUTH=str(tmp / "auth.json"),
        PROJECT_NAME="langboard",
        PROJECT_SHORT_NAME="lb",
        MAIN_DATABASE_URL=os.environ["LANGBOARD_ACCEPTANCE_DATABASE_URL"],
        READONLY_DATABASE_URL=os.environ["LANGBOARD_ACCEPTANCE_DATABASE_URL"],
        CARD_INTERNAL_ACCESS_MODE="project_members",
        JWT_SECRET_KEY="disposable-acceptance-" + os.urandom(32).hex(),
        CACHE_TYPE="in-memory",
        BROADCAST_TYPE="in-memory",
        PYTHONPATH=str(ROOT / "src/sdk/vendor/langboard_sdk-0.2.11-py3-none-any.whl"),
    )
    broadcast = ROOT / "local/broadcast"
    broadcast.mkdir(parents=True, exist_ok=True)
    prior = set(broadcast.glob("*"))
    with (tmp / "server.log").open("w") as log:
        server = subprocess.Popen([sys.executable, __file__], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
        try:
            import httpx

            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError((tmp / "server.log").read_text())
                try:
                    if (
                        httpx.get(f"http://127.0.0.1:{port}/openapi.json", timeout=0.5, trust_env=False).status_code
                        == 200
                    ):
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Native HTTP server did not become ready")
            asyncio.run(acceptance(f"http://127.0.0.1:{port}", json.loads((tmp / "auth.json").read_text())))
            emitted = set(broadcast.glob("*")) - prior
            events = [json.loads(p.read_text()) for p in emitted]
            publications = []
            for e in events:
                if e.get("event") != "socket_publish":
                    continue
                models = e["data"]["publish_models"]
                publications.extend(models if isinstance(models, list) else [models])
            invalidations = [p for p in publications if p["event"] == "apps:changed"]
            assert len(invalidations) >= 5, [p["event"] for p in publications]
            assert any("card:created" in p["event"] for p in publications), [p["event"] for p in publications]
            assert any("metadata" in p["event"] for p in publications), [p["event"] for p in publications]
            print("Native broadcasts:", [p["event"] for p in publications])
        finally:
            log.flush()
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
            for path in set(broadcast.glob("*")) - prior:
                path.unlink()
    print("Disposable server, credentials and emitted broadcast files cleaned; caller owns database removal")
