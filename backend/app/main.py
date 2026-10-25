import asyncio
import io
import importlib
import ipaddress
import logging
import warnings
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, UnidentifiedImageError

from .auth import current_user
from .brief import build_brief
from .config import Settings
from .models import Gallery, ImageRef, Outfit, Product, Profile, ProfileInput, ReplaceInput, RequestInput, RequestState, SaveInput, SourceStatus
from .store import Store
from .providers import OpenRouterProvider, ProviderUnavailable

logger = logging.getLogger("velor")


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_https_url(url: str) -> bool:
    """URL syntax guard. Actual HTTP adapters must also pin/validate resolved IPs."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        if parts.scheme != "https" or not host or parts.username or parts.password or parts.port not in {None, 443}:
            return False
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or "." not in host:
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


class BodyLimit:
    def __init__(self, app, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        upload = scope.get("path") == "/api/uploads"
        limit = self.limit + 65536 if upload else 256 * 1024
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Invalid Content-Length"}, 400)(scope, receive, send)
        if length > limit:
            return await JSONResponse({"detail": "Request body too large"}, 413)(scope, receive, send)
        seen = 0

        async def limited_receive():
            nonlocal seen
            message = await receive()
            seen += len(message.get("body", b""))
            if seen > limit:
                raise HTTPException(413, "Request body too large")
            return message

        await self.app(scope, limited_receive, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    tasks: set[asyncio.Task] = set()
    locks: dict[tuple[str, str], asyncio.Lock] = {}
    style_tokens: dict[tuple[str, str], str] = {}
    render_tokens: dict[tuple[str, str, str], str] = {}

    def lock(owner: str, request_id: str) -> asyncio.Lock:
        return locks.setdefault((owner, request_id), asyncio.Lock())

    def spawn(coro):
        task = asyncio.create_task(coro)
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def queue_render(owner: str, request_id: str, outfit: Outfit):
        token = uuid4().hex
        render_tokens[(owner, request_id, outfit.id)] = token
        spawn(render_job(owner, request_id, outfit.id, outfit.revision, token))

    @asynccontextmanager
    async def lifespan(application):
        application.state.store = Store(settings.data_dir)
        application.state.provider = OpenRouterProvider(settings, application.state.store)
        # Persisted jobs are explicit failures after a restart. No silent re-run of
        # provider calls, charges, or transmission of user images on boot.
        for owner, state in application.state.store.all_requests():
            changed = False
            if state.status in {"searching", "styling"}:
                state.status = "failed"
                state.error = "Локальный сервер перезапущен. Создайте запрос заново."
                changed = True
            for outfit in state.outfits:
                if outfit.render_status == "pending":
                    outfit.render_status = "failed"
                    changed = True
            if changed:
                application.state.store.save_request(owner, state)
        yield
        for task in list(tasks):
            task.cancel()
        if tasks:
            await asyncio.gather(*list(tasks), return_exceptions=True)

    app = FastAPI(title="VÉLOR", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(BodyLimit, limit=settings.upload_max_bytes)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "X-Dev-User"])

    def store() -> Store:
        return app.state.store

    def owned_request(owner: str, request_id: str) -> RequestState:
        state = store().request(owner, request_id)
        if state is None:
            raise HTTPException(404, "Request not found")
        return state

    def owned_outfit(state: RequestState, outfit_id: str) -> Outfit:
        outfit = next((o for o in state.outfits if o.id == outfit_id), None)
        if outfit is None:
            raise HTTPException(404, "Outfit not found")
        return outfit

    def checked_images(owner: str, images: list[ImageRef]) -> list[ImageRef]:
        canonical = {}
        for image in images:
            saved = store().upload(owner, image.id)
            if saved is None:
                raise HTTPException(422, "Use an image uploaded by this user")
            ref, _ = saved
            if image.kind != ref.kind or image.url not in {None, ref.url} or image.local_path is not None:
                raise HTTPException(422, "Image URL, kind, and path cannot be overridden")
            canonical[ref.id] = ref
        return list(canonical.values())

    async def search_job(owner: str, request_id: str):
        async def progress(source: SourceStatus):
            async with lock(owner, request_id):
                state = owned_request(owner, request_id)
                if state.status != "searching":
                    return
                state.catalog.sources = [s for s in state.catalog.sources if s.source_id != source.source_id] + [source]
                store().save_request(owner, state)
        try:
            from .search import search_catalog
            state = owned_request(owner, request_id)
            catalog = await search_catalog(state.brief, on_source=progress)
            ids = [p.id for p in catalog.products]
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate catalog product IDs")
            for product in catalog.products:
                if not public_https_url(product.source_url):
                    raise ValueError("Unsafe product source URL")
                if product.image_url and not product.image_url.startswith("data:image/svg+xml") and not public_https_url(product.image_url):
                    raise ValueError("Unsafe product image URL")
                if settings.mode == "demo":
                    product.is_demo = True
                    product.verification = "demo"
                    product.verified_at = None
                    product.availability = "unknown"
            async with lock(owner, request_id):
                state = owned_request(owner, request_id)
                state.catalog, state.status = catalog, "selection"
                store().save_request(owner, state)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Search failed: %s", type(error).__name__)
            async with lock(owner, request_id):
                state = owned_request(owner, request_id)
                state.status, state.error = "failed", "Поиск не завершен. Провайдер недоступен или результат не прошел проверку."
                store().save_request(owner, state)

    async def render_job(owner: str, request_id: str, outfit_id: str, revision: int, token: str):
        try:
            from .stylist import render_outfit
            state = owned_request(owner, request_id)
            outfit = owned_outfit(state, outfit_id)
            if outfit.revision != revision or render_tokens.get((owner, request_id, outfit_id)) != token:
                return
            captured_ids = tuple(outfit.product_ids)
            products = [p for p in state.catalog.products if p.id in outfit.product_ids and p.id not in state.excluded_product_ids]
            disclaimer = outfit.render_disclaimer
            if app.state.provider.enabled:
                from .stylist import BackendImageProvider, render_outfit_result
                result = await render_outfit_result(outfit.model_copy(deep=True), products,
                    provider=BackendImageProvider(app.state.provider), allow_external=True, fallback=False, timeout_seconds=90)
                if result.status != "ready" or not result.image_url:
                    raise ProviderUnavailable("Catalog render failed without a fallback to demo")
                url, disclaimer = result.image_url, result.disclaimer
            else:
                url = await render_outfit(outfit.model_copy(deep=True), products)
            if not isinstance(url, str) or not (url.startswith(("data:image/svg+xml", "data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,")) or public_https_url(url)):
                raise ValueError("Unsafe render URL")
            async with lock(owner, request_id):
                state = owned_request(owner, request_id)
                current = next((o for o in state.outfits if o.id == outfit_id), None)
                # A late response can never overwrite an edited or removed outfit.
                if (current is None or current.revision != revision or tuple(current.product_ids) != captured_ids
                    or render_tokens.get((owner, request_id, outfit_id)) != token):
                    return
                current.render_url, current.render_revision, current.render_status = url, revision, "ready"
                current.render_disclaimer = disclaimer
                if all(o.render_status != "pending" for o in state.outfits):
                    state.status = "ready"
                store().save_request(owner, state)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Render failed: %s", type(error).__name__)
            async with lock(owner, request_id):
                state = owned_request(owner, request_id)
                current = next((o for o in state.outfits if o.id == outfit_id), None)
                if current is not None and current.revision == revision and render_tokens.get((owner, request_id, outfit_id)) == token:
                    current.render_status = "failed"
                    if all(o.render_status != "pending" for o in state.outfits):
                        state.status = "ready"
                    store().save_request(owner, state)

    async def style_job(owner: str, request_id: str, token: str):
        try:
            stylist = importlib.import_module("app.stylist")
            async with lock(owner, request_id):
                state = owned_request(owner, request_id)
                if state.status != "styling" or style_tokens.get((owner, request_id)) != token:
                    return
                remaining = [p for p in state.catalog.products if p.id not in state.excluded_product_ids and p.availability != "out_of_stock"]
                if hasattr(stylist, "compose_outfits_result"):
                    result = stylist.compose_outfits_result(request_id, state.brief, remaining)
                    outfits = result.outfits
                    for issue in result.issues[:5]:
                        state.catalog.warnings.append(issue.message)
                else:
                    outfits = stylist.compose_outfits(request_id, state.brief, remaining)
                if app.state.provider.enabled:
                    outfits = outfits[:1]
                allowed = {p.id for p in remaining}
                if len({o.id for o in outfits}) != len(outfits):
                    raise ValueError("Duplicate outfit IDs")
                for outfit in outfits:
                    if outfit.request_id != request_id or not outfit.product_ids or not set(outfit.product_ids) <= allowed or len(set(outfit.product_ids)) != len(outfit.product_ids):
                        raise ValueError("Stylist referenced unavailable catalog IDs")
                    outfit.revision, outfit.render_status = 1, "pending"
                    outfit.render_revision, outfit.render_url, outfit.saved = None, None, False
                state.outfits, state.status = outfits, "styling" if outfits else "ready"
                if not outfits:
                    state.catalog.warnings.append("Недостаточно подходящих товаров для аутфита. Измените запрос или выбор.")
                store().save_request(owner, state)
            for outfit in outfits:
                queue_render(owner, request_id, outfit)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Stylist failed: %s", type(error).__name__)
            async with lock(owner, request_id):
                state = owned_request(owner, request_id)
                if style_tokens.get((owner, request_id)) != token:
                    return
                state.status, state.error = "failed", "Стилист недоступен или вернул недопустимые ID товаров."
                store().save_request(owner, state)

    @app.get("/api/health")
    async def health():
        provider = app.state.provider.status()
        local = "demo_local" if settings.mode == "demo" else "unconfigured"
        return {"status": "ok", "mode": settings.mode, "environment": settings.environment,
                "providers": {"brief": provider, "search": local, "render": provider}, "search_workers": 3,
                "provider_budget": {"limit_usd": settings.provider_budget_usd, **store().provider_usage()}}

    @app.get("/api/profile", response_model=Profile | None)
    async def get_profile(owner: str = Depends(current_user)):
        return store().profile(owner)

    @app.put("/api/profile", response_model=Profile)
    async def put_profile(payload: ProfileInput, owner: str = Depends(current_user)):
        async with lock(owner, "profile"):
            previous = store().profile(owner)
            now = timestamp()
            profile = Profile(id=previous.id if previous else uuid4().hex, style_text=payload.style_text,
                              images=checked_images(owner, payload.images), created_at=previous.created_at if previous else now, updated_at=now)
            store().save_profile(owner, profile)
            return profile

    @app.post("/api/uploads", response_model=ImageRef, status_code=201)
    async def upload(file: UploadFile = File(...), kind: Literal["wardrobe", "reference"] = Form(...), owner: str = Depends(current_user)):
        try:
            content = await file.read(settings.upload_max_bytes + 1)
            if len(content) > settings.upload_max_bytes:
                raise HTTPException(413, "Image exceeds 10 MiB limit")
            count, used = store().upload_usage(owner)
            if count >= settings.upload_max_count or used + len(content) > settings.upload_total_max_bytes:
                raise HTTPException(413, "Local upload quota reached (100 files / 100 MiB)")
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(content)) as image:
                        image_format = image.format
                        if image_format not in {"JPEG", "PNG", "WEBP"}:
                            raise HTTPException(415, "Use JPEG, PNG, or WebP")
                        if image.width * image.height > settings.upload_max_pixels:
                            raise HTTPException(413, "Image exceeds 20 megapixels")
                        image.verify()
                    # Full decode catches truncated files that verify() can miss.
                    with Image.open(io.BytesIO(content)) as image:
                        image.load()
            except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                raise HTTPException(415, "Invalid or oversized image") from None
            extension, mime = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"), "WEBP": ("webp", "image/webp")}[image_format]
            image_id = uuid4().hex
            path = store().upload_dir / f"{image_id}.{extension}"
            path.write_bytes(content)
            ref = ImageRef(id=image_id, kind=kind, url=f"/api/uploads/{image_id}", mime_type=mime)
            store().save_upload(owner, ref, path)
            return ref
        finally:
            await file.close()

    @app.get("/api/uploads/{image_id}")
    async def get_upload(image_id: str, owner: str = Depends(current_user)):
        saved = store().upload(owner, image_id)
        if saved is None or not saved[1].is_file():
            raise HTTPException(404, "Image not found")
        ref, path = saved
        return FileResponse(path, media_type=ref.mime_type, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    @app.post("/api/requests", response_model=RequestState, status_code=201)
    async def new_request(payload: RequestInput, owner: str = Depends(current_user)):
        profile = store().profile(owner)
        if profile is None:
            raise HTTPException(409, "Create a persistent profile first")
        if not payload.text.strip():
            raise HTTPException(422, "Request text cannot be blank")
        payload.images = checked_images(owner, payload.images)
        brief = build_brief(profile, payload, settings.mode)
        if app.state.provider.enabled:
            try:
                brief = await app.state.provider.analyze_brief(profile, payload, brief)
            except ProviderUnavailable:
                raise HTTPException(503, "OpenRouter unavailable or shared budget exhausted; no automatic retry") from None
        elif settings.mode == "live":
            brief.unknowns.append("OpenRouter не настроен или платные запросы выключены; brief построен локально.")
        state = RequestState(id=uuid4().hex, profile_id=profile.id, text=payload.text, status="searching",
                             brief=brief, created_at=timestamp())
        store().save_request(owner, state)
        spawn(search_job(owner, state.id))
        return state

    @app.get("/api/requests/{request_id}", response_model=RequestState)
    async def get_request(request_id: str, owner: str = Depends(current_user)):
        return owned_request(owner, request_id)

    @app.delete("/api/requests/{request_id}/products/{product_id}", response_model=RequestState)
    async def exclude_product(request_id: str, product_id: str, owner: str = Depends(current_user)):
        async with lock(owner, request_id):
            state = owned_request(owner, request_id)
            if state.status == "searching":
                raise HTTPException(409, "Wait for search to finish")
            if product_id not in {p.id for p in state.catalog.products}:
                raise HTTPException(404, "Product not found")
            if product_id not in state.excluded_product_ids:
                state.excluded_product_ids.append(product_id)
                style_tokens.pop((owner, request_id), None)
                for outfit in state.outfits:
                    render_tokens.pop((owner, request_id, outfit.id), None)
                state.outfits = []
                state.status, state.error = "selection", None
                store().save_request(owner, state)
            return state

    @app.post("/api/requests/{request_id}/style", response_model=RequestState)
    async def style(request_id: str, owner: str = Depends(current_user)):
        async with lock(owner, request_id):
            state = owned_request(owner, request_id)
            if state.status != "selection":
                raise HTTPException(409, "Stylist requires a completed catalog selection")
            state.status, state.error = "styling", None
            token = uuid4().hex
            style_tokens[(owner, request_id)] = token
            store().save_request(owner, state)
        spawn(style_job(owner, request_id, token))
        return state

    @app.patch("/api/requests/{request_id}/outfits/{outfit_id}", response_model=Outfit)
    async def replace_product(request_id: str, outfit_id: str, payload: ReplaceInput, owner: str = Depends(current_user)):
        async with lock(owner, request_id):
            state = owned_request(owner, request_id)
            outfit = owned_outfit(state, outfit_id)
            if outfit.revision != payload.expected_revision:
                raise HTTPException(409, "Outfit revision changed; reload before editing")
            catalog = {p.id: p for p in state.catalog.products if p.id not in state.excluded_product_ids}
            old, new = catalog.get(payload.old_product_id), catalog.get(payload.new_product_id)
            if payload.old_product_id not in outfit.product_ids or old is None or new is None:
                raise HTTPException(422, "Replacement must use remaining catalog IDs")
            if old.category != new.category or new.availability == "out_of_stock" or new.id in outfit.product_ids:
                raise HTTPException(422, "Replacement must be a different available item in the same category")
            # The actual stylist validates aggregate budget, sizes, category slots,
            # and all supported hard constraints again after replacement.
            stylist = importlib.import_module("app.stylist")
            if hasattr(stylist, "replace_outfit_item"):
                try:
                    outfit = stylist.replace_outfit_item(outfit, state.brief, list(catalog.values()), old.id, new.id, payload.expected_revision)
                except ValueError:
                    raise HTTPException(422, "Replacement violates outfit constraints or lacks verified facts") from None
                state.outfits = [outfit if candidate.id == outfit.id else candidate for candidate in state.outfits]
            else:
                outfit.product_ids = [new.id if x == old.id else x for x in outfit.product_ids]
                outfit.revision += 1
            outfit.render_revision, outfit.render_url = None, None
            outfit.render_status, outfit.saved = "pending", False
            state.status = "styling"
            store().save_request(owner, state)
        queue_render(owner, request_id, outfit)
        return outfit

    @app.post("/api/requests/{request_id}/outfits/{outfit_id}/save", response_model=Outfit)
    async def save_outfit(request_id: str, outfit_id: str, payload: SaveInput, owner: str = Depends(current_user)):
        async with lock(owner, request_id):
            state = owned_request(owner, request_id)
            outfit = owned_outfit(state, outfit_id)
            if outfit.revision != payload.expected_revision:
                raise HTTPException(409, "Outfit revision changed; reload before saving")
            if outfit.render_status != "ready" or outfit.render_revision != outfit.revision:
                raise HTTPException(409, "Wait for the current revision render before saving")
            outfit.saved = True
            products = [p for p in state.catalog.products if p.id in outfit.product_ids]
            store().save_outfit(owner, outfit, products)
            store().save_request(owner, state)
            return outfit

    @app.get("/api/gallery", response_model=Gallery)
    async def gallery(owner: str = Depends(current_user)):
        return store().gallery(owner)

    return app


app = create_app()
