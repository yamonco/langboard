from inspect import Parameter, signature
from typing import Callable, Literal, TypedDict, get_args
from langboard_shared.core.utils.decorators import class_instance, thread_safe_singleton
from pydantic import ConfigDict, create_model


_TAccessibleType = Literal["all", "user", "bot"]


class McpToolMetadata(TypedDict):
    description: str
    handler: Callable
    input_schema: dict
    accessible_type: _TAccessibleType
    exclude: list[str]


@class_instance()
@thread_safe_singleton
class McpTool:
    def __init__(self):
        self._tools: dict[str, McpToolMetadata] = {}

    def add(
        self, accessible_type: _TAccessibleType = "all", description: str | None = None
    ) -> Callable[[Callable], Callable]:
        """Register a model-visible MCP tool and derive its input schema."""

        def decorator(func: Callable) -> Callable:
            sig = signature(func)
            params = sig.parameters
            exclude = [name for name, param in params.items() if self._is_injected_parameter(param)]

            visible_params = {name: param for name, param in params.items() if name not in exclude}
            fields = {
                name: (
                    str if param.annotation is Parameter.empty else param.annotation,
                    ... if param.default is Parameter.empty else param.default,
                )
                for name, param in visible_params.items()
            }
            input_model = create_model(
                f"{func.__name__}Input",
                __config__=ConfigDict(extra="forbid"),
                **fields,
            )
            input_schema = input_model.model_json_schema()
            input_schema.pop("title", None)

            self._tools[func.__name__] = {
                "description": description or func.__doc__ or func.__name__,
                "handler": func,
                "input_schema": input_schema,
                "accessible_type": accessible_type,
                "exclude": exclude,
            }

            return func

        return decorator

    def get_tools(self) -> dict[str, McpToolMetadata]:
        """Return all registered MCP tool metadata."""

        return self._tools

    def get_tool(self, tool_name: str) -> McpToolMetadata | None:
        """Return one registered MCP tool, if present."""

        return self._tools.get(tool_name)

    @staticmethod
    def _is_injected_parameter(param: Parameter) -> bool:
        """Identify parameters supplied by the Langboard MCP runtime."""

        annotation = param.annotation
        if annotation is Parameter.empty:
            return False

        annotations = {item for item in get_args(annotation) if item is not type(None)} or {annotation}
        names = {getattr(item, "__name__", "") for item in annotations}
        return bool(names) and (names <= {"User", "Bot"} or names <= {"DomainService", "Repository"})
