import asyncio
from json import dumps as json_dumps
from json import loads as json_loads
from typing import AsyncGenerator, Literal
from langboard_shared.core.caching import Cache
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.logger import Logger
from langboard_shared.domain.models import Bot, BotLog, InternalBot, Project
from langboard_shared.domain.models.BotLog import BotLogType
from langboard_shared.domain.services import DomainService
from langboard_shared.publishers import (
    CardPublisher,
    GraphApprovalPublisher,
    ProjectBotPublisher,
    ProjectColumnPublisher,
)
from ..schema import GraphInterrupt, GraphRequestModel, RunResponse
from .registry import run_default_graph


class GraphRunner:
    BOT_STATUS_MAP_CACHE_PREFIX = "bot.status.map"
    BOT_STATUS_MAP_INDEX_CACHE_KEY = "bot.status.map:index"

    def __init__(
        self,
        input_request: GraphRequestModel,
        stream: bool = False,
        raw_project: dict | None = None,
        raw_bot: tuple[Literal["bot", "internal_bot"], dict] | None = None,
        raw_bot_log: tuple[dict | None, dict | None] | None = None,
    ):
        self.input_request = input_request
        self.stream = stream
        self.raw_project = raw_project
        self.raw_bot = raw_bot
        self.raw_bot_log = raw_bot_log

    async def run_stream(self):
        main_task = asyncio.create_task(self.run())

        async def response_generator() -> AsyncGenerator[str, None]:
            try:
                result = await main_task
                if result.message:
                    yield self._create_stream_event("token", {"chunk": result.message})
                for graph_interrupt in result.interrupts:
                    yield self._create_stream_event("interrupt", graph_interrupt.model_dump())
                yield self._create_stream_event("end", {"result": result.model_dump()})
            except Exception as e:
                Logger.main.exception(e)
                yield self._create_stream_event("error", {"error": str(e)})
            finally:
                if not main_task.done():
                    main_task.cancel()
                    try:
                        await main_task
                    except asyncio.CancelledError:
                        pass

        return main_task, response_generator()

    async def run(self) -> RunResponse:
        return await self.__simple_run_graph()

    @classmethod
    def clear_bot_status_cache(cls) -> None:
        project_uids: list[str] = Cache.get(GraphRunner.BOT_STATUS_MAP_INDEX_CACHE_KEY) or []
        for project_uid in project_uids:
            Cache.delete(cls._get_bot_status_cache_key(project_uid))

        Cache.delete(GraphRunner.BOT_STATUS_MAP_INDEX_CACHE_KEY)
        Cache.delete(GraphRunner.BOT_STATUS_MAP_CACHE_PREFIX)

    async def __simple_run_graph(self) -> RunResponse:
        await self._update_log(BotLogType.Info, "Running graph...", "running")
        await self._publish_status("running")
        try:
            tweaks = self._create_graph_tweaks()
            graph_result = await run_default_graph(
                self.input_request.input_value,
                tweaks,
                self.input_request.session_id,
                self.input_request.thread_id or self.input_request.session_id,
            )
            if graph_result.interrupts:
                approval_count = await self._persist_approval_requests(graph_result.interrupts)
                message = "Graph interrupted for human input"
                if approval_count:
                    message = f"Graph approval requested ({approval_count})"
                await self._update_log(BotLogType.Info, message, "stopped")
            else:
                await self._update_log(BotLogType.Success, "Graph successfully completed", "stopped")
            return RunResponse.from_graph_result(
                graph_result,
                session_id=self.input_request.session_id,
                thread_id=self.input_request.thread_id or self.input_request.session_id,
            )
        except Exception as e:
            Logger.main.exception(e)
            await self._update_log(BotLogType.Error, str(e), "stopped")
            raise
        finally:
            await self._publish_status("stopped")

    def _create_graph_tweaks(self) -> dict:
        tweaks = dict(self.input_request.tweaks or {})
        if tweaks.get("Graph") or not self.raw_bot:
            return tweaks

        _, bot_data = self.raw_bot
        raw_value = bot_data.get("value")
        if not isinstance(raw_value, str) or not raw_value:
            return tweaks

        try:
            bot_value = json_loads(raw_value)
        except Exception:
            return tweaks

        if not isinstance(bot_value, dict):
            return tweaks

        agent_llm = bot_value.pop("agent_llm", "")
        if not agent_llm:
            return tweaks

        system_prompt = bot_value.pop("system_prompt", "")
        api_names = bot_value.pop("api_names", [])
        bot_value.pop("comfort_tool_names", None)
        bot_value.pop("comfort_tool_descriptions", None)
        bot_value.pop("comfort_tool_definitions", None)
        approval_request = bot_value.pop("approval_request", None)

        tweaks["Graph"] = {
            "agent_llm": agent_llm,
            "settings": bot_value,
            "system_prompt": system_prompt if isinstance(system_prompt, str) else "",
            "api_names": api_names if isinstance(api_names, list) else [],
        }
        if approval_request:
            tweaks["Graph"]["approval_request"] = approval_request

        return tweaks

    def _create_stream_event(self, event: str, data: dict) -> str:
        return json_dumps({"event": event, "data": data}, ensure_ascii=False) + "\n\n"

    async def _persist_approval_requests(self, interrupts: list[GraphInterrupt]) -> int:
        if not self.raw_project or not self.raw_bot_log or not self.raw_bot:
            return 0

        raw_log, _ = self.raw_bot_log
        if not raw_log:
            return 0

        project = Project(**self.raw_project)
        bot_type, bot_data = self.raw_bot
        bot = Bot(**bot_data) if bot_type == "bot" else None
        internal_bot = InternalBot(**bot_data) if bot_type == "internal_bot" else None
        bot_log = BotLog(**raw_log)
        approval_count = 0

        with DomainService.use() as service:
            for graph_interrupt in interrupts:
                value = graph_interrupt.value
                if not isinstance(value, dict) or value.get("type") != "approval_request":
                    continue

                interrupt = dict(value)
                if not interrupt.get("run_id") and graph_interrupt.id:
                    interrupt["run_id"] = graph_interrupt.id

                approval = service.graph_approval_request.create_from_interrupt(
                    project,
                    interrupt,
                    bot=bot,
                    internal_bot=internal_bot,
                    bot_log=bot_log,
                )
                if not approval:
                    continue

                approval_count += 1
                approval_response = service.graph_approval_request.get_api_response(approval)
                GraphApprovalPublisher.requested(project, approval_response)

        return approval_count

    async def _update_log(self, log_type: BotLogType, stack: str, status: Literal["running", "stopped"]) -> None:
        if not self.raw_bot_log:
            return
        log, scope_log = self.raw_bot_log
        if not log:
            return

        log = BotLog(**log)
        with DbSession.use(readonly=True) as db:
            latest_log = db.exec(SqlBuilder.select.table(BotLog).where(BotLog.id == log.id).limit(1)).first()
            if latest_log:
                log = latest_log

        log.log_type = log_type
        log_stack = log.append_message(stack, log_type)

        with DbSession.use(readonly=False) as db:
            db.update(log)

        if self.raw_project and scope_log:
            project = Project(**self.raw_project)
            ProjectBotPublisher.log_stack_added(project, log, log_stack, status)

    async def _publish_status(self, status: Literal["running", "stopped"]) -> None:
        if not self.raw_project or not self.input_request.tweaks or not self.raw_bot:
            return

        rest_data = self.input_request.tweaks.get("rest_data")
        if not rest_data:
            variables = self.input_request.tweaks.get("LangboardCalledVariablesComponent")
            if isinstance(variables, dict):
                rest_data = variables.get("rest_data")
        if not rest_data:
            return

        column_uid = rest_data.get("project_column_uid")
        card_uid = rest_data.get("card_uid")
        if not column_uid and not card_uid:
            return

        project = Project(**self.raw_project)
        project_uid = project.get_uid()
        bot_type, bot_data = self.raw_bot
        bot = Bot(**bot_data) if bot_type == "bot" else InternalBot(**bot_data)
        bot_uid = bot.get_uid()

        if card_uid:
            target_type = "card"
            publisher = CardPublisher
            target_uid = card_uid
        elif column_uid:
            target_type = "project_column"
            publisher = ProjectColumnPublisher
            target_uid = column_uid
        else:
            return

        cache_key = self._get_bot_status_cache_key(project_uid)
        status_map: dict = Cache.get(cache_key) or {}
        type_map = status_map.setdefault(target_type, {})
        status_list = list(type_map.setdefault(target_uid, []))

        if status == "running":
            if bot_uid not in status_list:
                status_list.append(bot_uid)
            type_map[target_uid] = status_list
        else:
            type_map[target_uid] = [uid for uid in status_list if uid != bot_uid]
            if not type_map[target_uid]:
                del type_map[target_uid]
            if not type_map:
                del status_map[target_type]

        Cache.set(cache_key, status_map, ttl=24 * 60 * 60)
        self._sync_bot_status_cache_index(project_uid, has_status=bool(status_map))
        publisher.bot_status_changed(project_uid, bot_uid, target_uid, status)

    @classmethod
    def _sync_bot_status_cache_index(cls, project_uid: str, has_status: bool) -> None:
        project_uids: list[str] = Cache.get(GraphRunner.BOT_STATUS_MAP_INDEX_CACHE_KEY) or []

        if has_status:
            if project_uid not in project_uids:
                project_uids.append(project_uid)
                Cache.set(GraphRunner.BOT_STATUS_MAP_INDEX_CACHE_KEY, project_uids, ttl=24 * 60 * 60)
            return

        updated_project_uids = [uid for uid in project_uids if uid != project_uid]
        Cache.delete(cls._get_bot_status_cache_key(project_uid))
        if updated_project_uids:
            Cache.set(GraphRunner.BOT_STATUS_MAP_INDEX_CACHE_KEY, updated_project_uids, ttl=24 * 60 * 60)
        else:
            Cache.delete(GraphRunner.BOT_STATUS_MAP_INDEX_CACHE_KEY)

    @classmethod
    def _get_bot_status_cache_key(cls, project_uid: str) -> str:
        return f"{GraphRunner.BOT_STATUS_MAP_CACHE_PREFIX}:{project_uid}"
