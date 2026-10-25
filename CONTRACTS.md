# VÉLOR integration contracts · v1 · 2026-10-25

## Ownership (shared working tree; no overlapping writes)
- Integrator: root config/deps/docs, backend/app/{main,models,store,auth,brief,config}.py, backend/tests/test_api.py; contracts and API integration.
- Frontend worker: frontend/** only. React + TypeScript + Vite; proxy `/api` → http://127.0.0.1:8000. No root edits.
- Search worker: backend/app/search/**, backend/tests/test_search.py only. Own source queue, exactly 3 base workers + separate discovery, verification, parser, SSRF. No network in demo.
- Stylist worker: backend/app/stylist/**, backend/tests/test_stylist.py only. Outfit composition, revision-safe rendering, matte black mannequin demo SVG. No root edits.
- Parent owns existing Space update and coordination unless assigned otherwise. Do not touch /Users/alik/VibeHack/timing-bot.

## Shared Python contracts
Integrator defines Pydantic v2 models in `app.models`. Fields are snake_case. All models `extra='forbid'`.
- Category = `headwear|tops|bottoms|shoes|accessories`
- ImageRef: id:str, kind:`wardrobe|reference`, url:str|null, local_path:str|null, mime_type:str|null. User files remain local; no external transmission.
- Profile: id:str, style_text:str, images:list[ImageRef], created_at:str, updated_at:str.
- Constraint: text:str, strength:`hard|soft`, provenance:`profile|request|inferred`, confidence:float (0..1).
- StyleBrief: schema_version:'1.0', id:str, profile_id:str, original_profile_text:str, original_request_text:str, images:list[ImageRef], categories:list[Category], search_queries:list[str], constraints:list[Constraint], preferences:list[Constraint], exclusions:list[Constraint], budget_rub:float|null, sizes:dict[str,str]|null, city:str|null, unknowns:list[str], mode:`demo|live`.
- Product: id:str, title:str, category:Category, source_id:str, source_url:str, image_url:str|null, price_rub:float|null, price_note:str|null, sizes:list[str], availability:`in_stock|out_of_stock|unknown`, verified_at:str|null, verification:`verified|unverified|demo`, evidence:list[str], is_demo:bool.
- SourceStatus: source_id:str, name:str, state:`queued|searching|verifying|complete|inaccessible|unconfigured|failed`, found:int=0, detail:str|null.
- ProductCatalog: schema_version:'1.0', products:list[Product], sources:list[SourceStatus], warnings:list[str].
- Outfit: id:str, request_id:str, title:str, product_ids:list[str], revision:int=1, render_revision:int|null, render_status:`pending|ready|failed`, render_url:str|null, saved:bool=False, explanation:str, render_disclaimer:str.

Search module interface: `async def search_catalog(brief: StyleBrief, on_source: Callable[[SourceStatus], Awaitable[None]] | None = None) -> ProductCatalog` exported from `app.search`.
Stylist interface exported from `app.stylist`: `def compose_outfits(request_id: str, brief: StyleBrief, products: list[Product]) -> list[Outfit]`; `async def render_outfit(outfit: Outfit, products: list[Product]) -> str` returns data:image/svg+xml URL or configured render URL; no persistence. Backend applies result only if outfit revision still matches captured revision.

## HTTP API v1
Dev mode: header `X-Dev-User: demo` (frontend includes it); dev auth forbidden when VELOR_ENV=production. Production: `Authorization: tma <Telegram initData>` server HMAC and freshness validation. No secrets supplied by default.
- GET /api/health → {status, mode, environment, providers:{brief,search,render}, search_workers:3}
- GET /api/profile → Profile|null
- PUT /api/profile body {style_text, images:ImageRef[]=[]} → Profile; persistent independent from requests.
- POST /api/uploads multipart file + kind:wardrobe|reference → ImageRef (local storage, image size/type checks).
- GET /api/uploads/{image_id} → private image bytes; requires the same auth header. Frontend must fetch with auth then use a blob URL, or retain its local preview. ImageRef.local_path is always null in public responses. Foreign or fabricated IDs, overridden paths/URLs/kinds are rejected.
- POST /api/requests body {text, images:ImageRef[]=[], budget_rub?:number|null, sizes?:object|null, city?:string|null} → RequestState; starts async search.
- GET /api/requests/{id} → RequestState
- DELETE /api/requests/{id}/products/{product_id} → RequestState (exclude only in this request)
- POST /api/requests/{id}/style body {} → RequestState (explicit user trigger after selection; excluded IDs unavailable to stylist)
- PATCH /api/requests/{id}/outfits/{outfit_id} body {old_product_id,new_product_id,expected_revision} → Outfit; validates catalog, category, exclusions; increments revision and queues render. 409 on stale revision.
- POST /api/requests/{id}/outfits/{outfit_id}/save body {expected_revision} → Outfit (409 stale)
- GET /api/gallery → {outfits:list[Outfit], products:list[Product]}
RequestState = {id, profile_id, text, status:'searching|selection|styling|ready|failed', brief:StyleBrief, catalog:ProductCatalog, excluded_product_ids:list[str], outfits:list[Outfit], created_at, error:str|null}.
Poll request every 800ms while searching/styling/render pending. Request results remain isolated. Display demo badge whenever mode=demo or is_demo. Unknown fields are not verified facts. No auto stylist on search completion.

## Integrator implementation notes · 2026-10-25
- Shared models and routes above implemented. `ProfileInput` and `RequestInput` allow at most 24 images; uploads accept decoded JPEG/PNG/WebP, at most 10 MiB and 20 MP. Per owner quota is 100 uploaded files / 100 MiB. JSON body limit 256 KiB; multipart body limit 10 MiB + 64 KiB, including streamed bodies.
- Dev identity is `dev:<X-Dev-User>`; Telegram identity is `telegram:<validated numeric id>`. Missing auth is 401, foreign request/upload is 404. Invalid Telegram auth never falls back to dev. Production startup rejects missing token or enabled dev auth.
- Search completion transitions `searching → selection`; explicit style starts `styling`, then `ready` when renders finish. Replacing an item increments revision, clears old render and saved flag, and starts render. Applying a render requires matching the captured revision.
- Excluding a product invalidates current request outfits and returns to selection. Explicit gallery saves are independent snapshots and persist after later request edits; saving a newer revision updates the saved snapshot for that outfit ID.
- Restarted in-flight jobs become an explicit failed state; the server does not repeat provider calls automatically. Successful profiles, catalogs, requests, outfits and gallery snapshots persist in SQLite.
- Health provider values: `demo_local` in demo; `unconfigured` in live until adapters are wired. Current Boss1 is a conservative local text adapter, preserving original text, provenance and unknowns; it does not perform visual AI analysis.
- OpenRouter integration: `app.providers.OpenRouterProvider.analyze_brief(profile, request, local_brief)`; `render_image(prompt: str, cache_key: str, input_references: list[str]) -> str`. Public catalog references and a synthetic mannequin only, never profile/request image uploads. Renderer bridge is `BackendImageProvider(app.state.provider)` with actual result disclaimer, no demo fallback on failed live calls.
- Models default to `google/gemini-3.8-flash` and `google/gemini-3.1-flash-image`, configurable server-side. Paid permission, key, positive budget and per-call reserve are all required. Global persistent SQLite ledger/cache is shared across analysis/render, concurrency 1, no automatic retries. Health adds `provider_budget` and `configured_disabled`/`openrouter_enabled` status where relevant.
- Generic frontend size `{clothing: 'M'}` normalizes to `tops` and `bottoms` sizes. Replacements use stylist `replace_outfit_item` for full budget/size/hard constraint validation. The API exposes detailed composition diagnostics in catalog warnings when no safe outfit can be produced.

## Runtime
Python FastAPI + SQLite; uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000. React dev localhost:5173. Default explicit demo, no providers or keys inferred. Production rejects dev auth and missing Telegram token. Demo products must visibly remain demo with no claim of live stock.
