import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    mode: str = "demo"
    data_dir: Path = ROOT / "data"
    enable_dev_auth: bool = True
    telegram_bot_token: str | None = field(default=None, repr=False)
    telegram_max_age_seconds: int = 3600
    upload_max_bytes: int = 10 * 1024 * 1024
    upload_max_pixels: int = 20_000_000
    upload_max_count: int = 100
    upload_total_max_bytes: int = 100 * 1024 * 1024
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    openrouter_api_key: str | None = field(default=None, repr=False)
    openrouter_brief_model: str = "google/gemini-3.8-flash"
    openrouter_render_model: str = "google/gemini-3.1-flash-image"
    allow_paid_requests: bool = False
    provider_budget_usd: float = 0.0
    analysis_reserve_usd: float = 0.0
    render_reserve_usd: float = 0.0

    @classmethod
    def from_env(cls) -> "Settings":
        environment = os.getenv("VELOR_ENV", "development")
        return cls(
            environment=environment,
            mode=os.getenv("VELOR_MODE", "demo"),
            data_dir=Path(os.getenv("VELOR_DATA_DIR", str(ROOT / "data"))),
            enable_dev_auth=os.getenv("VELOR_DEV_AUTH", "1" if environment == "development" else "0") == "1",
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_max_age_seconds=int(os.getenv("VELOR_TELEGRAM_MAX_AGE", "3600")),
            cors_origins=tuple(x.strip() for x in os.getenv("VELOR_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY") or None,
            openrouter_brief_model=os.getenv("VELOR_OPENROUTER_BRIEF_MODEL", "google/gemini-3.8-flash"),
            openrouter_render_model=os.getenv("VELOR_OPENROUTER_RENDER_MODEL", "google/gemini-3.1-flash-image"),
            allow_paid_requests=os.getenv("VELOR_ALLOW_PAID_REQUESTS", "0") == "1",
            provider_budget_usd=float(os.getenv("VELOR_PROVIDER_BUDGET_USD", "0")),
            analysis_reserve_usd=float(os.getenv("VELOR_ANALYSIS_RESERVE_USD", "0")),
            render_reserve_usd=float(os.getenv("VELOR_RENDER_RESERVE_USD", "0")),
        )

    def validate(self) -> None:
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("VELOR_ENV must be development, test, or production")
        if self.mode not in {"demo", "live"}:
            raise ValueError("VELOR_MODE must be demo or live")
        if self.environment == "production" and (self.enable_dev_auth or not self.telegram_bot_token):
            raise ValueError("Production requires Telegram auth and forbids dev auth")
        if self.telegram_max_age_seconds <= 0:
            raise ValueError("Telegram auth lifetime must be positive")
        if not 0 <= self.provider_budget_usd <= 5:
            raise ValueError("Provider session budget must be between 0 and the user's total $5 ceiling")
        if not 0 <= self.analysis_reserve_usd <= 5 or not 0 <= self.render_reserve_usd <= 5:
            raise ValueError("Provider reservations must be finite, nonnegative, and within total budget")
