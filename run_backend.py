"""Local launcher. Reads only this project's explicitly authorized .env file.

It never evaluates shell syntax or prints config values; existing environment wins.
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
ALLOWED = {"OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN"}


def load_local_config():
    path = ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key in ALLOWED or key.startswith("VELOR_"):
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ.setdefault(key, value)


if __name__ == "__main__":
    load_local_config()
    sys.path.insert(0, str(ROOT / "backend"))
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
