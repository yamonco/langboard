"""Server-authenticated collaboration transport; never read from client headers."""

from enum import Enum


class CollaborationChannel(str, Enum):
    HumanUI = "human_ui"
    Mcp = "mcp"
    Api = "api"
    Bot = "bot"
