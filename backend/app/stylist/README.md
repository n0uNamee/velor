# VÉLOR stylist / renderer integration

Owned files are entirely inside this package. No new dependencies. Uses shared
`app.models`, the existing Pydantic models, and existing `httpx` for OpenRouter.

## Stable API

```python
from app.stylist import compose_outfits, render_outfit

# Only pass the post-user-filter approved catalog. No automatic styling on search.
outfits = compose_outfits(request_id, brief, approved_products)
preview_url = await render_outfit(outfits[0], approved_products)
```

These match CONTRACTS.md. The default is deterministic rules plus a **Schematic
preview**: matte black shop mannequin beside actual selected product cards. It
does not pretend the schematic clothes the mannequin or simulates garment fit.
Only local same-origin / embedded raster product pictures appear in the SVG;
remote pictures are never fetched. Missing photographs remain explicitly missing.
Demo catalog items show DEMO; rules are explicitly distinguished from an LLM.

`compose_outfits_result(...)` returns `CompositionResult(outfits, issues, strategy,
provider_status, is_demo)` for a useful empty-state reason. `validate_outfit(...)`
returns `ValidationReport`. Their optional `options=StylingOptions(...)` carries:

- `excluded_product_ids`: additional removed-ID guard; excluded items never enter
  an LLM payload. The caller must still supply the current approved catalog.
- `owned_product_ids`: explicitly verified owned IDs that still exist in that
  catalog. Their purchase cost is zero, not their reported retail price. Local
  wardrobe images alone do not create owned products.
- `pinned_product_ids`: exact IDs that must remain; one per category.
- `item_slots`: requested categories, one product per slot; defaults to the brief's
  categories. No partial outfits silently omit unavailable categories.
- `facts`: `dict[id, ProductFacts(colors=..., materials=..., tags=...)]` supplied
  by normalized trusted catalog evidence. None means unknown, empty means known
  empty. Colors/materials are never invented from photographs or absent text.
- `max_outfits`: default 3; capped at 6; deduplicated ID combinations. Bounded beam
  search keeps 128 candidates per slot, so it is not an exhaustive optimizer.

Hard budget is the aggregate cost of new purchases. Unknown new-item cost cannot
pass a specified budget. Requested sizes must exactly match a catalog size after
case/whitespace normalization; no conversion between ambiguous size systems.
The shared Product has sizes but no variant IDs: this module cannot invent a
variant selection. Live products require verified status and confirmed stock.
Explicit demo fixtures may have unknown stock only in mode=demo, and their
explanations preserve that the assortment/stock is fictional and unverified.

Free-text hard constraints are deliberately fail-closed: canonical single-color
or material requirements/exclusions such as `только чёрный`, `без кожи`, `only
black`, `without leather` work with explicit ProductFacts. Unsupported hard prose
returns `unsupported_hard_constraint`; missing facts return
`unknown_hard_attribute`. Budget/size constraints synthesized by brief.py are
recognized only when their structured fields agree. Soft matches use supplied
description words/facts and explain matches and unknowns, with no factual claims
about unobserved style, fit, weather suitability, or materials.

## Editing / rendering / persistence

`replace_outfit_item(outfit, brief, approved_products, old_id, new_id,
expected_revision, options=...)` preserves every other product ID and order,
validates same category and the full resulting outfit, creates revision + 1,
clears old render fields and marks the new revision unsaved/pending. It never
mutates the old saved object. `OutfitValidationError.code` supports 409 for
`stale_revision`, and 422 for validation failures.

`replace_and_render(..., coordinator=shared_coordinator)` performs that change
then immediately renders its new revision. `RenderCoordinator.render(...)`
checks request ID, outfit ID, revision, product IDs and latest job token before
applying a result. `cancel(outfit)` invalidates its active token. An old job has
`status='stale'`, `image_url=None`, `applied=False`; it cannot overwrite latest.
Coordinator is event-loop scoped. **Database writes still need an atomic
expected-revision compare-and-set**; do not persist an old object after an await.
Gallery/save remains integrator-owned. Reject save if render_revision differs
from revision, and preserve the actual render disclaimer.

`render_outfit_result(...)` reports `provider_unconfigured`,
`external_permission_required`, `provider_error`, `invalid_input`, `cancelled`,
`stale`, or `ready`. When fallback is enabled these can include a labelled
schematic URL. UI should use `preview_kind`/`disclaimer` rather than infer real
image generation from a URL or `Outfit.render_status='ready'` alone. Imagegen is
an approximation even after successful provider return, not product fidelity proof.

## OpenRouter: injected, server-side, no default paid call

`providers.py` defines `StylistProvider`, immutable `OutfitProposal`, and
`compose_with_provider(...)`. Default provider=None uses local rules. External
calls require `allow_external=True`. All proposals undergo independent local
membership/constraint validation; no model tool execution is available. Payloads
omit profile IDs, profile images, wardrobe photos, source URLs and local paths.
Catalog/brief text remains untrusted data under fixed instructions.

`OpenRouterStylistProvider(OpenRouterStylistSettings(...), budget_guard=...)`
uses `POST /api/v1/chat/completions`, strict structured JSON plus local validation.
Model is configurable (default `google/gemini-3.8-flash`).
`OpenRouterImageProvider` uses `POST /api/v1/images` with public catalog image
references only, model configurable (default `google/gemini-3.1-flash-image`),
1K, 3:4, n=1. The image adapter does not receive personal photos or local files.
No actual OpenRouter inference was run for this package.

Both transports require an explicit server key, paid action approval, a positive
max_calls gate **and** an injected `BudgetGuard`. Defaults cannot send an HTTP
request. Root `.env`/configuration is integrator-owned; package `.env.example`
contains only empty/disabled illustrative values and is not loaded by this module.
Keys never enter repr, prompts, frontend, returned errors or logs.

`spending.py` defines the central guard boundary. Integrator must share ONE guard
across brief/stylist/render, reserve a known conservative price atomically before
every request and deny when price or remaining budget is unknown. Settle actual
`usage.cost` when present; on errors/timeouts/missing usage retain full reservation.
No retry happens automatically. Successful identical requests are cached in the
adapter instance; caller must retain instances rather than recreate per request.
Only the integrator runs paid smoke tests after explicit approval of the shared
cap; this package's tests use mock transports only. Call-count gating is not a
guaranteed vendor billing cap, and a missing price estimate must block calls.

The integrator already owns `app.providers.OpenRouterProvider.render_image(...)`.
To use that existing app-wide budget/cache instead of a second transport,
`BackendImageProvider(app.state.provider)` implements ImageRenderProvider. Pass
it to `render_outfit_result(..., allow_external=app.state.provider.enabled)`;
preserve result.disclaimer/status when applying a matching revision. The backend
retains all cost/key control. Use `replace_outfit_item` in the API edit handler
rather than category-only mutation, so budget, sizes and hard rules are rechecked.

## Verification

Run explicitly (root pytest configuration defaults to backend/tests):

```sh
.venv/bin/python -m pytest backend/app/stylist/tests -q
```

Tests exercise catalog membership/removal, size/budget/slots, unknown hard facts,
owned/pinned items, revisions, provider failure/privacy/strict output, concurrent
and cancelled render jobs, and OpenRouter mocked wire contracts. No credential
setup, external image transmission, paid request, frontend or root edit is needed.
