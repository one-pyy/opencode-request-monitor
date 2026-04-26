from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
MISC_DIFF_PATH = Path("/root/_/misc/diff/diff.html")

DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 30500
DEFAULT_PROXY_HOST = "127.0.0.1"
DEFAULT_PROXY_PORT = 30499
DEFAULT_UPSTREAM_PROXY = "http://127.0.0.1:30084"
