# VÉLOR search integration

Public interface (unchanged from `CONTRACTS.md`):

```python
from app.search import search_catalog
catalog = await search_catalog(brief, on_source=async_source_callback)
```

`brief.mode` is explicit. `demo` never calls the network, emits fictional cards on
the reserved `demo.velor.invalid` domain, sets `verification="demo"`, `is_demo=True`,
`availability="unknown"`, and supplies a visible demo title/price note. No stock,
merchant association, or real product URL is implied by these fixtures.

`live` runs exactly three async base-search tasks against one dynamic queue of the
twelve sources in `sources.py`. A separate discovery task performs one ordinary
public Bing HTML request, outside the base hosts, with no API key or browser
evasion. A single separate verifier consumes candidate URLs as producers deliver
them, refetches actual cards, and rejects unknown mandatory facts. The final
parser normalizes categories/titles/sizes, removes duplicate product identities,
and preserves the actual fetched URL, including its variant/signature query.

No dependencies, provider credentials, root configuration, models, or API files
were added or changed by the search implementation. `Product` has no dedicated
fields for condition, delivery, style confidence or conditional price, so these
are stated explicitly in `evidence`/`price_note`. The ordinary price is coupled to
an in-stock size. Available size buttons do not establish inventory. Used,
refurbished and damaged goods require explicit corresponding request text.

The lexical verifier is intentionally conservative: colors, garment types,
materials and other recognized terms need supporting product facts. Abstract
styles and unsupported hard requirements remain unknown and are rejected; no
external semantic/image model is implied. Outfit total budget validation remains
the stylist's responsibility; search rejects any single item exceeding it.

Defaults: 45s total, 8s per source, 6s per verification, 8s discovery, 0.2s per
progress callback, four candidate cards per base source, twelve discovery cards,
forty admitted products. `SearchPipeline` and `SearchBudgets` allow dependency and
budget injection without root config changes. External cancellation propagates
and cancels owned tasks; total budget expiry returns only already verified partial
results. Source failures never discard other sources' verified results.

Source progress includes twelve base sources plus a separate `discovery` entry.
The common SourceStatus enum maps internal `blocked` → `inaccessible` and
`unsupported` → `unconfigured`, preserving the reason in `detail`. `found` counts
admitted cards. A provider denial gets no proxy, alternate access route, retry,
CAPTCHA solving, login or security change.

The transport rejects non-public DNS/IP destinations, embedded credentials,
non-HTTP(S) schemes, nonstandard ports, redirect HTTPS downgrades and invalid URLs.
Every redirect is re-resolved and checked. Connections pin the checked address,
while TLS validates the original hostname. Request time, document/decompression
size, redirect count and concurrent daemon workers are bounded. Thread limits
apply per fetcher and per process, including stalled OS DNS lookups.

## Verification

Run search tests explicitly because the root pytest configuration may list only
`backend/tests` (the task confines new tests to the search ownership zone):

```sh
PYTHONPATH=backend .venv/bin/python -m pytest backend/app/search/tests -q
```

The tests use offline documents and injected transports; they do not establish
merchant accessibility. Actual one-shot live observations are recorded separately
in [SOURCE_ACCESS.md](SOURCE_ACCESS.md) and [DISCOVERY_ACCESS.md](DISCOVERY_ACCESS.md).
The follow-up [NETWORK_DIAGNOSTIC.md](NETWORK_DIAGNOSTIC.md) distinguishes default
sandbox DNS failure from non-public DNS answers blocked before TLS/HTTP during
approved network execution. `FetchError.stage` and `error_code` preserve this
distinction without treating execution failures as merchant responses.
All twelve source attempts and discovery returned no HTTP response in this
execution environment. Card fetching was not run, and current search endpoint
correctness is not established by those failures. See those records for exact
timestamps, paths and diagnostic evidence.
