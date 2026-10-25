# Bounded network diagnosis · 2026-10-25

This follow-up distinguishes execution-network failures from merchant responses.
Only synthetic text `худи` was used. No image, account data or credentials were
sent; no proxy/VPN, TLS settings or SSRF guards were changed.

The same explicit command ran twice, first with the default sandbox and then
through the tool's normal `require_escalated` network-execution permission. The
escalated action was approved and executed; no approval is pending or uncertain.

```sh
PYTHONPATH=backend .venv/bin/python -m app.search.diagnose_network
```

Targets:

- Official HTTPS control: `https://www.python.org/`.
- Configured SELA search: `https://www.sela.ru/search/?q=%D1%85%D1%83%D0%B4%D0%B8`.
- At most one genuine product-card link would be fetched after a successful
  search response. None was found/fetched in these runs.

| Execution | UTC timestamp | Official control | SELA search | TLS/HTTP/card |
|---|---|---|---|---|
| Default sandbox | 2026-10-25T12:53:10.912944+00:00 | DNS `gaierror`, errno 8 | DNS `gaierror`, errno 8 | Not reached / not run |
| Approved network execution | 2026-10-25T12:53:33.275442+00:00 | DNS returned one answer; blocked by public-IP guard | DNS returned one answer; blocked by public-IP guard | Not reached / not run |

Exact default-sandbox resolver error for both hosts:
`[Errno 8] nodename nor servname provided, or not known`.

Exact approved-execution transport result for both hosts:
`state="blocked"`, `detail="DNS includes a non-public destination"`,
`http_status=null`. The transport validates every DNS answer before opening a
socket, so these runs did not reach a TLS handshake or receive any merchant
HTTP response. The observed DNS addresses were not recorded; their exact value
or the runtime's reason for returning them cannot be inferred from this record.

**Stopped action:** HTTPS fetching of the official control and SELA search/card
in this runtime. **Reason:** default execution cannot resolve public names;
approved execution resolves names to a destination rejected as non-public by
the existing SSRF guard. **Status:** blocked before connection, not a website
403/CAPTCHA/geo denial and not a policy-approval rejection. No retry, alternate
route, literal-IP override, DNS override or guard exception followed that result.

The earlier twelve source failures must not be labelled merchant restrictions.
No current source endpoint or live product-card path has been validated. A
normally connected runtime returning public DNS destinations is required to
validate the same ordinary search-to-card implementation without weakening its
security checks. Demo and offline tests remain usable independently.

## Authorized read-only follow-up

A separately approved DNS-only/local-state inspection made **no HTTP request**.
Both `www.python.org` and `www.sela.ru` resolved into **198.18.0.0/15**, with
`is_global=False`, `is_private=True`. No individual internal address was retained.
Running executable basenames included `clash-verge`, `clash-verge-service` and
`verge-mihomo`. HTTP/HTTPS/SOCKS system proxy flags were 0; automatic proxy
configuration/discovery flags were 1. There were nine `utun` interfaces and no
Connected entry in the system VPN list. No PAC URLs, process arguments,
credentials or configuration contents were exposed. No settings were changed.

This supports fake-IP DNS as the explanation and confirms Clash/Mihomo processes
are running; the actual DNS mode was not read, so fake-IP mode itself is not
conclusively established. The confirmed blocker is the non-public DNS destination,
rejected before connect/TLS/HTTP.

Minimal manual step: temporarily disable Clash Verge's DNS/TUN interception, or
run the backend in a connected environment returning public DNS answers, then
explicitly rerun the bounded diagnostic. No automatic retry or network change
will occur. Guards and TLS validation remain unchanged.

Current checks: **120 search tests + 66 subtests passed**, and **19 backend
integration tests passed**. The reported evidence-negation failure did not
reproduce. Merchant title/description negation rejects products; generated
diagnostic evidence does not participate in style matching. No verifier edit
was needed in this follow-up. Search ownership is released to the integrator.
