from os.path import dirname
from pathlib import Path
from sys import executable
from langboard_shared.Env import Env


# Directory
BASE_DIR = Path(dirname(__file__ if not Env.IS_EXECUTABLE else executable))

# URL
HOST = Env.get_from_env("API_HOST", "localhost")

# App Config
APP_CONFIG_FILE = Env.DATA_DIR / "api_config.json"

EMAIL_REGEX = r"^.+@.+\..+$"
