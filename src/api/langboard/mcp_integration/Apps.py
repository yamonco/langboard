"""Portable native MCP views; domain tools remain useful without an Apps host."""

from pathlib import Path
from fastmcp.apps import AppConfig, ResourceCSP
from fastmcp.resources import Resource


WORK_PLAN_URI = "ui://langboard/work-plan-v1.html"
WORK_PLAN_TOOL_META = {"ui": AppConfig(resource_uri=WORK_PLAN_URI).model_dump(by_alias=True, exclude_none=True)}


def add_native_app_resources(provider):
    provider.add_resource(
        Resource.from_function(
            work_plan_view,
            uri=WORK_PLAN_URI,
            name="work_plan_view",
            mime_type="text/html;profile=mcp-app",
            meta={
                "ui": AppConfig(
                    csp=ResourceCSP(connect_domains=[], resource_domains=[]), prefers_border=False
                ).model_dump(by_alias=True, exclude_none=True)
            },
        )
    )


def work_plan_view() -> str:
    """Serve a static self-contained view; all private data arrives through the host."""
    return Path(__file__).with_name("work_plan.html").read_text(encoding="utf-8")
