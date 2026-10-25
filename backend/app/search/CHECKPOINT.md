# Search checkpoint · 2026-10-25 12:49 UTC / 15:49 Moscow

Ready for integration. Changed files are confined to `backend/app/search/**`.
No root dependencies, shared models/API/config, frontend, stylist or git state were
changed by the search team. Public interface matches `CONTRACTS.md`:
`async search_catalog(brief, on_source=None) -> ProductCatalog`.

## Actual verification

```text
PYTHONPATH=backend .venv/bin/python -m pytest backend/app/search/tests -q
115 passed, 62 subtests passed in 0.66s
```

This is an offline suite. It includes the complete path through twelve source
searches plus external discovery, extracted observed links, actual ProductVerifier
re-fetch and extraction, and final parser: **13 admitted fixture products**.
It also checks three shared-queue workers, one separate verifier, discovery,
partial results, errors, bounded waits, cancellation, blocked URLs/redirects/DNS,
price-size-stock coupling, same-offer city/delivery, condition, style unknowns,
dedupe and preservation of actual product URLs. Fixtures are not live evidence.

Default exported API demo smoke (actual command run separately): **24 demo
products**, **13 source statuses**, **0 verified live products**, all cards marked
`is_demo=True`, `verification=demo`, `availability=unknown`; twelve base statuses
complete, discovery explicitly unconfigured/offline. No network calls in demo
(also asserted with providers that fail if called).

## Live access limitation

- Twelve base source search GETs: **0 passed, 12 inaccessible with no HTTP response**.
- Product-card GETs: **not run**, because no source links could be extracted.
- Bing discovery: one request, **inaccessible with no HTTP response**, zero URLs.
- Seven niche seeds: **not run**; they are hints, never a permanent discovery allowlist.
- Ozon DNS-only diagnostic: `socket.gaierror [Errno 8]`.
- No CAPTCHA/403/proxy/geo bypass, alternate endpoint retry, credential creation,
  external user-image transmission, seller messages, login or purchase occurred.

Exact targets/timestamps: `SOURCE_ACCESS.md` and `DISCOVERY_ACCESS.md`. These are
execution-environment failures and do not prove merchant 403/CAPTCHA or current
endpoint correctness. No operation is awaiting user approval; live source
accessibility remains unverified until an allowed connected environment can run
the same ordinary requests.

Follow-up network-permission diagnosis: see `NETWORK_DIAGNOSTIC.md`. The approved
execution resolved both an official control and SELA to a non-public destination,
which the existing SSRF guard blocked before TLS/HTTP. No guard exception or
alternate route was attempted. Default sandbox DNS failed on both hosts.

Follow-up code checkpoint (2026-10-25 12:55 UTC): `FetchError` now exposes optional
backward-compatible `stage` and `error_code` for URL, DNS, connect, TLS, HTTP,
decode and resource errors. Raw OS exception strings/addresses are not exposed.
`diagnose_network.py` is an explicitly invoked bounded CLI, never part of API,
demo or automated tests. After these changes the actual full offline command
above returned **120 passed, 66 subtests passed in 0.71s**. No further live request
was made after the approved-execution public-IP guard block.

## Integration notes

Root pytest configuration currently discovers `backend/tests`; include
`backend/app/search/tests` explicitly in CI or the integrator-owned test config.
Source callbacks include twelve base records plus a `discovery` record. Internal
blocked/unsupported states map to the shared enum's inaccessible/unconfigured.
Condition, delivery, exact ordinary vs loyalty price and lexical style evidence
use `Product.evidence`/`price_note` because the shared model has no dedicated fields.
Unverified live cards are not admitted to ProductCatalog. Abstract style semantics
remain unknown with the local matcher; no semantic model provider is claimed.
