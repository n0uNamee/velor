# Source access evidence

Follow-up: `NETWORK_DIAGNOSTIC.md` records the official-control/SELA comparison in
default and explicitly approved network execution. Both runs stopped before HTTP
(default DNS failure, then non-public DNS destination blocked by SSRF guard).
These observations are execution-network failures, not merchant 403/CAPTCHA.

All twelve configured search attempts returned no HTTP response in this execution environment. A separate DNS-only diagnostic for `ozon.ru` failed with `socket.gaierror: [Errno 8] nodename nor servname provided, or not known`. No HTTP retry or alternate route was attempted. Do not interpret these observations as a merchant-side 403/CAPTCHA, or as confirmation that the configured search paths are current.

One ordinary, unauthenticated search GET per configured base endpoint; at most one extracted product-card GET. Timestamp: 2026-10-25T12:40:35.755902+00:00. Query: «худи». No CAPTCHA, HTTP restriction, regional restriction, or security bypass; no retry through another endpoint after denial. These observations are per-run, not guarantees of future accessibility. Product URLs below were extracted from fetched merchant content.

| Source | Search observation | Card observation | Detail |
|---|---|---|---|
| Ozon | inaccessible (HTTP —) | not_run (HTTP —) | HTTP connection or document decoding failed |
| Спортмастер | inaccessible (HTTP —) | not_run (HTTP —) | HTTP connection or document decoding failed |
| СТОКМАНН | inaccessible (HTTP —) | not_run (HTTP —) | HTTP connection or document decoding failed |
| O’STIN | inaccessible (HTTP —) | not_run (HTTP —) | HTTP connection or document decoding failed |
| LIME | inaccessible (HTTP —) | not_run (HTTP —) | HTTP connection or document decoding failed |
| Befree | inaccessible (HTTP —) | not_run (HTTP —) | HTTP connection or document decoding failed |
| SELA | inaccessible (HTTP —) | not_run (HTTP —) | HTTP connection or document decoding failed |
| ZARINA | inaccessible (HTTP —) | not_run (HTTP —) | HTTP connection or document decoding failed |
| LOVE REPUBLIC | inaccessible (HTTP —) | not_run (HTTP —) | HTTP connection or document decoding failed |
| Zolla | inaccessible (HTTP —) | not_run (HTTP —) | HTTP connection or document decoding failed |
| ТВОЁ | inaccessible (HTTP —) | not_run (HTTP —) | HTTP connection or document decoding failed |
| Finn Flare | inaccessible (HTTP —) | not_run (HTTP —) | HTTP connection or document decoding failed |

Exact evidence:

```json
[
  {
    "id": "ozon",
    "name": "Ozon",
    "search_url": "https://www.ozon.ru/search/?text=%D1%85%D1%83%D0%B4%D0%B8",
    "search": "inaccessible",
    "card": "not_run",
    "detail": "HTTP connection or document decoding failed",
    "search_http": null
  },
  {
    "id": "sportmaster",
    "name": "Спортмастер",
    "search_url": "https://www.sportmaster.ru/search/?text=%D1%85%D1%83%D0%B4%D0%B8",
    "search": "inaccessible",
    "card": "not_run",
    "detail": "HTTP connection or document decoding failed",
    "search_http": null
  },
  {
    "id": "stockmann",
    "name": "СТОКМАНН",
    "search_url": "https://stockmann.ru/search/?q=%D1%85%D1%83%D0%B4%D0%B8",
    "search": "inaccessible",
    "card": "not_run",
    "detail": "HTTP connection or document decoding failed",
    "search_http": null
  },
  {
    "id": "ostin",
    "name": "O’STIN",
    "search_url": "https://ostin.com/search/?text=%D1%85%D1%83%D0%B4%D0%B8",
    "search": "inaccessible",
    "card": "not_run",
    "detail": "HTTP connection or document decoding failed",
    "search_http": null
  },
  {
    "id": "lime",
    "name": "LIME",
    "search_url": "https://limestore.com/ru_ru/search?query=%D1%85%D1%83%D0%B4%D0%B8",
    "search": "inaccessible",
    "card": "not_run",
    "detail": "HTTP connection or document decoding failed",
    "search_http": null
  },
  {
    "id": "befree",
    "name": "Befree",
    "search_url": "https://befree.ru/search/?q=%D1%85%D1%83%D0%B4%D0%B8",
    "search": "inaccessible",
    "card": "not_run",
    "detail": "HTTP connection or document decoding failed",
    "search_http": null
  },
  {
    "id": "sela",
    "name": "SELA",
    "search_url": "https://www.sela.ru/search/?q=%D1%85%D1%83%D0%B4%D0%B8",
    "search": "inaccessible",
    "card": "not_run",
    "detail": "HTTP connection or document decoding failed",
    "search_http": null
  },
  {
    "id": "zarina",
    "name": "ZARINA",
    "search_url": "https://zarina.ru/search/?q=%D1%85%D1%83%D0%B4%D0%B8",
    "search": "inaccessible",
    "card": "not_run",
    "detail": "HTTP connection or document decoding failed",
    "search_http": null
  },
  {
    "id": "loverepublic",
    "name": "LOVE REPUBLIC",
    "search_url": "https://loverepublic.ru/search/?q=%D1%85%D1%83%D0%B4%D0%B8",
    "search": "inaccessible",
    "card": "not_run",
    "detail": "HTTP connection or document decoding failed",
    "search_http": null
  },
  {
    "id": "zolla",
    "name": "Zolla",
    "search_url": "https://zolla.com/search/?q=%D1%85%D1%83%D0%B4%D0%B8",
    "search": "inaccessible",
    "card": "not_run",
    "detail": "HTTP connection or document decoding failed",
    "search_http": null
  },
  {
    "id": "tvoe",
    "name": "ТВОЁ",
    "search_url": "https://tvoe.ru/search/?q=%D1%85%D1%83%D0%B4%D0%B8",
    "search": "inaccessible",
    "card": "not_run",
    "detail": "HTTP connection or document decoding failed",
    "search_http": null
  },
  {
    "id": "finnflare",
    "name": "Finn Flare",
    "search_url": "https://www.finn-flare.ru/search/?q=%D1%85%D1%83%D0%B4%D0%B8",
    "search": "inaccessible",
    "card": "not_run",
    "detail": "HTTP connection or document decoding failed",
    "search_http": null
  }
]
```

Offline fixture tests are separate from these live observations. `extracted` means structured facts were extracted; unknown price, size stock, condition, city, delivery, or style match is not a verified product. Search endpoint templates are configuration hints; 404/unsupported responses do not establish the current correct endpoint. No niche-seed or external-discovery live probe was run here.
