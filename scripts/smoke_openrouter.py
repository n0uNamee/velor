"""Explicit operator-run paid smoke test, synthetic data only.

Never prints credentials, environment, provider bodies, or auth headers.
Use --analysis once, then --render with a JSON file of real public products.
The shared SQLite ledger retains all reservations, including uncertain calls.
"""
import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
from run_backend import load_local_config
from app.brief import build_brief
from app.config import Settings
from app.models import Outfit, Product, Profile, RequestInput
from app.providers import OpenRouterProvider, ProviderUnavailable
from app.store import Store


async def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--analysis", action="store_true")
    group.add_argument("--render", type=Path)
    args = parser.parse_args()
    load_local_config()
    config = replace(Settings.from_env(), mode="live", allow_paid_requests=True, provider_budget_usd=2.0)
    config.validate()
    if not config.openrouter_api_key:
        print(json.dumps({"status": "blocked", "reason": "project key is absent or empty"}))
        return 1
    store = Store(config.data_dir)
    provider = OpenRouterProvider(config, store)
    before = store.provider_actual_cost()
    try:
        if args.analysis:
            profile = Profile(id="synthetic-smoke", style_text="Спокойный минимализм, свободный крой.", images=[], created_at="synthetic", updated_at="synthetic")
            request = RequestInput(text="Образ для прогулки в городе", budget_rub=15000)
            result = await provider.analyze_brief(profile, request, build_brief(profile, request, "live"))
            evidence = {"schema_version": result.schema_version, "categories": result.categories, "constraints_count": len(result.constraints), "images_transmitted": 0}
        else:
            products = [Product.model_validate(item) for item in json.loads(args.render.read_text())]
            outfit = Outfit(id="synthetic-public-smoke", request_id="synthetic-public", title="Public catalog reference test", product_ids=[p.id for p in products], explanation="Synthetic smoke test", render_disclaimer="AI test; not a fit guarantee")
            url = await provider.render_catalog_outfit(outfit, products)
            import base64
            output = config.data_dir / "smoke-render.png"
            output.write_bytes(base64.b64decode(url.split(",", 1)[1]))
            evidence = {"output": str(output), "product_ids": outfit.product_ids, "reference_count": len(products) + 1, "personal_photos_transmitted": 0}
        status = "passed"
    except ProviderUnavailable as error:
        status, evidence = "failed", {"reason": str(error)}
    usage = store.provider_usage()
    report = {"timestamp": datetime.now(timezone.utc).isoformat(), "status": status, "operation": "analysis" if args.analysis else "render", "actual_cost_usd_this_test": store.provider_actual_cost() - before,
              "actual_known_cost_usd_total": store.provider_actual_cost(), **usage,
              "conservative_budget_remaining_usd": max(0, 2.0 - usage["reserved_or_charged_usd"]), **evidence}
    evidence_path = config.data_dir / ("smoke-analysis-report.json" if args.analysis else "smoke-render-report.json")
    evidence_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
