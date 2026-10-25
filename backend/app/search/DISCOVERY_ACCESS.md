# Discovery access check · 2026-10-25

At `2026-10-25T12:42:55.302206+00:00` (15:42 Moscow), ran one
ordinary public Bing HTML search through `PublicWebDiscoveryProvider` and the
guarded `AsyncFetcher(timeout_seconds=6)` using only the synthetic text query
`черный худи`. No profile text, user images, local paths, credentials or cookies
were sent.

- Target: `https://www.bing.com/search` with the provider's encoded synthetic
  query, `count=6`, and `setlang=ru`.
- Observed provider state: `inaccessible`.
- Exact detail: `HTTP connection or document decoding failed`.
- Product URL candidates returned: **0**.
- No retry, alternate endpoint, proxy, CAPTCHA handling or access bypass ran.
- This confirms an attempted bounded request and an unavailable result from
  this execution environment. It does not establish that Bing's public endpoint
  itself is unavailable elsewhere.

The live provider reports this state to the pipeline; it never substitutes
fixtures. Offline provider tests cover parsing direct external links, excluding
the 12 base hosts, refusing opaque Bing redirects, bounded candidate counts,
explicit unsupported/unconfigured states and no retry after denial.
