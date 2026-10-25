# Фактическая проверка VÉLOR

## Финальный локальный видео-checkpoint ·17:37 МСК

- PASS: 313 tests,73 subtests; frontend build/lint.
- PASS: Chrome http://127.0.0.1:5173/ → «Демо для жюри» → реальная OKNO card4200RUB/S → «AI-стилист» → schematic outfit → save/gallery,0 page errors. Скриншоты /tmp/velor-video-{catalog,editor,gallery}.png.
- PASS: настоящий guarded live fetch homepage https://okno.store/ → наблюдённая https://okno.store/item/bryuki-miss-sixty → SSRitem price4200/availabletrue/singlesizeS; is_demo=false, condition/city-specific deliveryunknown. Не универсальныйпоиск12сайтов. Для видео используется честно датированный снимок17:20 МСК этой карточки, не fixtures.
- PASS: после разрешённогоrestart новыйQuickTunnel surfaces-gras-transport-golden.trycloudflare.com externalhealth200 production/web/okno. По последнему указанию пользователя public работыне продолжались, основнойрезультатlocalhostдлявидео.
- Billing:2 provider attempts,0.30 USD conservative retained; actual knownanalysis0.00255825. Render POST outcome uncertain, Models GET403, no retries/bypass. PaidAPIinappoff. $3 reservedemoнерасходовался.

25 октября 2026. Локальная среда: Python 3.12, Node 22.

- PASS: установка Python-зависимостей из `requirements.txt` в `.venv`.
- PASS: `python -m compileall -q backend/app`.
- PASS latest: `.venv/bin/python -m pytest -q` — 299 passed, 66 subtests passed, 1 deprecation warning Starlette/AnyIO. Includes root/search/stylist, single-origin production/allowlist/locked-entry guards and20 fake-only Telegram setup tests. Regression: old render cannot overwrite a recomposed outfit with the same ID/revision1.
- API-тесты используют явно подменённые search/stylist adapters, чтобы проверить auth, Telegram HMAC/срок действия, изоляцию пользователей, постоянный профиль, schema/provenance/nulls, ручной stylist, исключённые ID, ревизии, поздний render, сохранение gallery snapshot, persistence, uploads/ownership/типы/квоты/body limits.
- PASS: real local modules integration — профиль → 24 demo products/13 source statuses → удаление → 3 outfits → revision 2 replacement/render → save → SQLite restart/gallery. No network.
- PASS: local uvicorn bind on 127.0.0.1:8000 and HTTP health check (explicit demo).
- PASS: one actual OpenRouter structured analysis with synthetic text, model `google/gemini-3.8-flash`. Local schema validated. `usage.cost=$0.00255825`, reserved `$0.10`, conservative test budget left `$1.90`. No photos transmitted. Evidence: local `data/smoke-analysis-report.json` (not in Git).
- PASS: public SELA card and observed catalog image returned HTTP 200 by ordinary GET. This confirms image availability only, not stock, fit, city or delivery. Card: https://www.sela.ru/eshop/men/futbolki-i-longslivy/SL6809110213_50/ .
- BLOCKED before paid HTTP: render reference DNS resolves to non-global 198.18.0.x in this local network. No render reservation or paid render request created. SSRF guard retained; VPN unchanged. Current ledger: 1 call, actual known `$0.00255825`, conservative charge `$0.10` of approved `$2`. `$3` demo reserve untouched.
- PASS after reconnect: common UI :5173 and API :8000 restarted; HTTP 200 from both `127.0.0.1:5173` and `localhost:5173`, health demo. No process was listening on 5173/8000/8001 before recovery.
- PASS: `npm run build` and `npm run lint`, no lint warnings.
- PASS: headless installed Chrome against the common Vite→FastAPI application, isolated synthetic dev identity: profile → request → 24 real demo catalog cards → explicit stylist → loaded schematic render → gallery save. No `/api` fixtures. Zero console/page errors; provider call count stayed 1→1. Desktop 1440×1000 and mobile 390×844 screenshots: `/tmp/velor-common-editor-desktop.png`, `/tmp/velor-common-editor-mobile.png`. Browser plugin unavailable; regular Playwright used. Only Telegram SDK was stubbed for local non-Telegram execution.
- Frontend worker separately reported 8/8 Chrome tests (7 contract fixtures + 1 real isolated FastAPI), with multipart PNG, replacement/409, persistence and mobile. This is worker evidence, not a second integrator run of that suite.
- NOT RUN: Telegram production, real image generation, live inventory. Deployment examples are prepared locally only; no host, TLS, bot, menu or service configuration applied.

## Subsequent authorized integration checkpoint

- PASS: detached local demo launcher; API8001 and UI5173 healthy. macOS native Python argv canonicalization was corrected without weakening exact project script/start-time checks. Root data/ledger preserved; paid0 forced.
- PASS: common Chrome flow repeated against UI5173→real FastAPI8001;24 demo cards, editor image/save,0 page/console errors, provider calls1→1. No API fixtures.
- PASS: frontend build and lint after locked entry message.
- PASS: production built frontend + authenticated API on8000, separate data/public. Without token/allowlist, health auth_status=locked, private APIs401, dev/fake Telegram rejected, .env/data/docs/openapi404. Browser locked UI has no editable input and0 page errors.
- PASS: explicitly authorized accountless Quick Tunnel registered with existing cloudflared2026.6.0; ordinary external HTTPS GET returned root200, health200 with production/locked, profile401, .env404. This is a real public locked entry, not a working authenticated Telegram session. Existing Cloudflare Worker was not modified. Cloud browser's separate request path was blocked and not bypassed.
- PASS: manually supplied token verified by real getMe as @velorr_bot; no existing webhook. Token only in ignored local backend files, never output. getUpdates returned0 updates; allowlist and menu have not been changed. A later attempted allowlist mutation was denied by automatic approval review for lack of trusted confirmation of the new nonce; it did not execute.
- PASS: authorized network executor backed up configs, appended21 target fake-IP suffixes preserving31 existing entries, validated Mihomo and reloadedHTTP204; other DNS/routes/security unchanged. SELA/OpenRouter public IPs observed. Remaining CDN CNAME cl-1d1e5523.edgecdn.ru resolves fakeIP through macOS and requires separate exact-host approval. No broad wildcard added.
- Paid render remains NOT SENT: both post-change attempts stopped in DNS validation before HTTP/reservation. Ledger still1 successful analysis, actual$0.00255825, reserved$0.10, conservative remaining$1.90 of$2. $3 reserve untouched.

Обычная установка PyPI сначала не прошла из-за сетевого ограничения sandbox; установка через разрешённый механизм завершилась успешно. Секреты не использовались.
