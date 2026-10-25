"""Single-origin Telegram launcher; no tunnel or external setup is performed.

Requires an existing separately authorized Telegram bot token. Exposes loopback
only; an independently approved HTTPS proxy/tunnel may target port 8000.
"""
import os
from pathlib import Path
import sys
import json

from run_backend import load_local_config


if __name__ == "__main__":
    load_local_config()
    root = Path(__file__).resolve().parent
    os.environ["VELOR_ENV"] = "production"
    os.environ["VELOR_DEV_AUTH"] = "0"
    os.environ["VELOR_FRONTEND_DIST"] = str(root / "frontend" / "dist")
    # Public profiles/jobs cannot interfere with the local demo process/database.
    os.environ["VELOR_DATA_DIR"] = str(root / "data" / "public")
    # Public-demo launch is not authorization to spend the reserved test budget.
    os.environ["VELOR_ALLOW_PAID_REQUESTS"] = "0"
    os.environ["VELOR_MODE"] = "live"
    os.environ["VELOR_SEARCH_SOURCE"] = "okno"
    # Without approved bot credentials, publish only a locked static entry.
    os.environ["VELOR_AUTH_MODE"] = "web"
    os.environ["VELOR_LOCKED_PREVIEW"] = "0"
    tunnel = json.loads((root / "data/runtime/tunnel.json").read_text())["url"].rstrip("/")
    os.environ["VELOR_WEB_ALLOWED_ORIGINS"] = tunnel + ",http://127.0.0.1:8000,http://localhost:8000"
    sys.path.insert(0, str(root / "backend"))
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, workers=1)
