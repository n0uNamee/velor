# VÉLOR Mini App · frontend

React 19, TypeScript, Vite. All application files and dependencies are confined to `frontend/`. Git operations belong to the integrator.

## Run locally

```sh
cd frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. `/api` proxies to `http://127.0.0.1:8000` by default, following `CONTRACTS.md`. For an isolated local test server only, `VELOR_API_TARGET=http://127.0.0.1:8001 npm run dev` overrides that target. No runtime provider key is required by the frontend.

The backend controls demo/live mode. There is no fixture fallback when the API fails. Development without Telegram sends `X-Dev-User: demo`; signed Telegram sessions send `Authorization: tma <initData>` instead. Production builds require Telegram for authenticated calls. The signed payload is never logged or stored.

## Implemented flow

1. Persistent profile: taste text, wardrobe photos and reference photos.
2. Separate request: text/photos, optional budget, size and city.
3. Async source status polling every 800 ms; catalog by headwear, tops, bottoms, shoes and accessories. Removal affects only this request.
4. Explicit **AI-стилист** action after selection. Searching does not generate or render outfits.
5. Outfit gallery in two columns, including on mobile; saved filter uses persistent gallery snapshots.
6. Editor: mannequin render on the left, square product thumbnails and details on the right. Mobile stacks these regions at readable sizes.
7. Replace one item with a same-category item from the current non-excluded catalog. Revision headers/body and response epochs protect edits; stale render images stay hidden. 409 refreshes current state without repeating the mutation.
8. Save and return to gallery. Editing a saved older snapshot opens the latest request version and explains that the saved variant is retained until the next save.

JPEG/PNG/WebP inputs use actual multipart upload. Profile photos and request photos remain separate. Restored private images are fetched with auth and displayed through revocable blob URLs; raw private URLs are never put in `<img src>`. Only local backend uploads are used; no user photo is sent to an external model. Uploads are limited to 10 MiB per file and 24 references per form, matching the server contract.

## Verification

```sh
npm run lint
npm run build
npm run test:e2e
```

The default Playwright suite uses clearly marked DEMO contract fixtures, generated dummy PNG bytes and the existing local Chrome executable. It does not verify live providers. It covers uploads/private previews, persistent profile, isolated request photos/removals, source polling, no automatic stylist, 2-column gallery, replacement revisions/stale renders, save, 409, offline API, Telegram headers, runtime errors and a 390 px mobile editor. Artifacts go to `/tmp`, not the repository.

The Browser plugin is unavailable in this session; regular Playwright uses installed Chrome. No browser was downloaded. `index.html` loads the official Telegram Web App SDK; UI fonts use local fallbacks, without a remote font dependency.

## Design evidence

Both supplied Library whiteboard photographs were materialized onto this Mac and visually inspected. They prescribe a catalog grid → 2×2 gallery → large mannequin left / narrow item column right, with save/return. The crossed-out vertical gallery list was not implemented.

Local references and the generated design concept live in ignored `frontend/references/`; they are not application assets or repository deliverables. Product images and outfit renders come from API data. A design concept image never substitutes for a backend outfit render. Demo renders may be schematic and are explicitly labelled.
