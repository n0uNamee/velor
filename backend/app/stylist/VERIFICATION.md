# Tested checkpoint · 2026-10-25

Only implementation/documentation files under `backend/app/stylist/**` were
written by this worker. No shared models/API/root dependencies/frontend/search
were edited. No git index/branch/commit/push operation was performed.

## Passed

- `.venv/bin/python -m pytest backend/app/stylist/tests -q -o cache_dir=backend/app/stylist/.pytest_cache`
  — **137 passed in 0.39s**.
- `.venv/bin/python -m pytest backend/tests -q -o cache_dir=backend/app/stylist/.pytest_cache`
  — **18 passed in 0.65s**. One existing Starlette/AnyIO deprecation warning.
- `.venv/bin/python -m compileall -q backend/app/stylist` — exit 0.
- Local offline integration smoke using `search_catalog(StyleBrief(mode='demo'))`
  then `compose_outfits_result` then `render_outfit_result`: **24 products, all
  five categories, 3 outfits, no composition issues, render_status
  `provider_unconfigured`, preview_kind `schematic`, preview URL present**.

Coverage includes membership/removed IDs, duplicated IDs, unknown and mismatched
sizes, aggregate budgets/unknown cost, slots, owned/pinned products, unsupported
hard constraints, fact uncertainty, replacements, saved-object immutability,
model proposal validation, nested provider-data isolation, OpenRouter mock
wire contracts, mandatory shared budget reservations, cost settlement, errors,
timeouts, no automatic retries, input/revision caches, cancel/stale jobs.

## Not run / integration actions

- No actual OpenRouter call, paid inference, credential configuration, external
  user-image transmission, deployment or UI action was run. Live provider status
  remains unconfirmed; only integrator may run a paid smoke after user approval.
- The API replacement handler must use `replace_outfit_item` (or
  `replace_and_render`) to enforce the full outfit's constraints after every edit.
  Category-only mutation does not enforce aggregate budget or requested sizes.
- Persist rendering only with the API's atomic revision guard. Return/use the
  actual `RenderResult.disclaimer` and `preview_kind`; a ready schematic is not
  an AI garment render.
- Existing app-wide budget integration can use
  `BackendImageProvider(app.state.provider)` with the integrator-owned backend.
  Separate transports also require the same centralized `BudgetGuard` across
  app providers, plus explicit action approval and call cap. No extra deps.

No remaining implementation test failures. Actual variant IDs are absent from
the shared Product model; only provided product IDs and confirmed sizes are used,
and no SKU/variant ID is fabricated. Free-text hard constraints beyond the
documented conservative parser return a diagnostic instead of an invented match.
