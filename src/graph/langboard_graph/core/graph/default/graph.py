from typing import Any
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from ...schema import GraphInterrupt, GraphRunResult
from ..checkpoint import open_graph_checkpointer
from .context import create_runtime_context_state
from .nodes import collect_default_history_context, run_default_agent
from .state import DefaultGraphState


def build_default_graph(checkpointer: BaseCheckpointSaver | None = None):
    graph = StateGraph(DefaultGraphState)
    graph.add_node("history", collect_default_history_context)
    graph.add_node("agent", run_default_agent)
    graph.add_edge(START, "history")
    graph.add_edge("history", "agent")
    graph.add_edge("agent", END)
    return graph.compile(checkpointer=checkpointer)


async def run_default_graph(
    input_value: str | None,
    tweaks: dict[str, Any] | None,
    session_id: str,
    thread_id: str,
    resume: Any | None = None,
) -> GraphRunResult:
    requires_checkpoint = _requires_checkpoint(tweaks, resume)
    async with open_graph_checkpointer(enabled=requires_checkpoint) as checkpointer:
        if requires_checkpoint and checkpointer is None:
            raise RuntimeError("Graph checkpoint storage requires a PostgreSQL MAIN_DATABASE_URL.")

        graph = build_default_graph(checkpointer)
        graph_input: Command[Any] | DefaultGraphState
        if resume is not None:
            graph_input = Command(resume=resume)
        else:
            input_tweaks = tweaks or {}
            state: DefaultGraphState = {
                "input_value": input_value or "",
                "tweaks": input_tweaks,
                "session_id": session_id,
                "thread_id": thread_id,
                **create_runtime_context_state(input_tweaks),
            }
            graph_input = state

        result = await graph.ainvoke(graph_input, config={"configurable": {"thread_id": thread_id}})
        graph_result = _create_graph_run_result(result)
        if checkpointer is not None and resume is None and not graph_result.interrupts:
            await checkpointer.adelete_thread(thread_id)
        return graph_result


async def get_default_graph_status(thread_id: str) -> dict[str, Any]:
    async with open_graph_checkpointer() as checkpointer:
        if checkpointer is None:
            return {"thread_id": thread_id, "interrupts": [], "values": {}, "next": []}

        graph = build_default_graph(checkpointer)
        snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
        return _create_graph_status_response(thread_id, snapshot)


async def delete_default_graph_thread(thread_id: str) -> None:
    async with open_graph_checkpointer() as checkpointer:
        if checkpointer is not None:
            await checkpointer.adelete_thread(thread_id)


def _create_graph_status_response(thread_id: str, snapshot: Any) -> dict[str, Any]:
    values = getattr(snapshot, "values", {}) or {}
    return {
        "thread_id": thread_id,
        "interrupts": _serialize_interrupts(getattr(snapshot, "interrupts", []) or []),
        "values": {
            key: values[key]
            for key in ("session_id", "thread_id", "approval_requests", "approval_result", "response")
            if key in values
        },
        "next": list(getattr(snapshot, "next", []) or []),
    }


def _requires_checkpoint(tweaks: dict[str, Any] | None, resume: Any | None) -> bool:
    if resume is not None:
        return True

    graph_config = (tweaks or {}).get("Graph")
    if not isinstance(graph_config, dict):
        return False
    if graph_config.get("approval_request") is not None:
        return True

    approval_policy = graph_config.get("api_approval_policy")
    if isinstance(approval_policy, dict) and "ask" in {str(value) for value in approval_policy.values()}:
        return True

    return bool(graph_config.get("api_names"))


def _create_graph_run_result(result: dict[str, Any]) -> GraphRunResult:
    interrupts = _serialize_interrupts(result.get("__interrupt__") or [])
    return GraphRunResult(
        message=result.get("response") or _get_interrupt_message(interrupts),
        interrupts=[GraphInterrupt(**item) for item in interrupts],
    )


def _serialize_interrupts(interrupts: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
    serialized_interrupts = []
    for item in interrupts:
        serialized_interrupts.append(
            {
                "id": getattr(item, "id", None),
                "value": getattr(item, "value", item),
            }
        )
    return serialized_interrupts


def _get_interrupt_message(interrupts: list[dict[str, Any]]) -> str:
    if not interrupts:
        return ""
    value = interrupts[0].get("value")
    if isinstance(value, dict):
        message = value.get("message")
        return message if isinstance(message, str) else "Graph interrupted."
    return str(value)
