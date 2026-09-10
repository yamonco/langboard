from os.path import dirname
from pathlib import Path
from sys import executable
from typing import Annotated
from langboard_shared.Env import Env
from pydantic import Field


# Directory
BASE_DIR = Path(dirname(__file__ if not Env.IS_EXECUTABLE else executable))

# URL
HOST = Env.get_from_env("API_HOST", "localhost")

# App Config
APP_CONFIG_FILE = Env.DATA_DIR / "api_config.json"

EMAIL_REGEX = r"^.+@.+\..+$"

MCP_DEFAULT_LIST_LIMIT = 50
MCP_MAX_LIST_LIMIT = 100
TMcpListLimit = Annotated[int, Field(ge=1, le=MCP_MAX_LIST_LIMIT)]
