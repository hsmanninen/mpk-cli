# TODO

Items are ordered by dependency.

## P0 - Protocol And Contracts

- [ ] **Enforce request budgets and cooperative cancellation.** Cap CLI results,
  including `--all`, at 200. Cap TUI `page_size` at 100 and pagination at 200
  page requests. Stop a superseded TUI search after its current response and
  before another pagination request. Keep requests sequential and preserve the
  0.4 second pagination pause.
- [ ] **Add bounded retries for safe GETs.** Allow at most two total attempts for
  bootstrap, vocabulary, and detail GETs on selected transport failures and
  502/503/504 responses. Honor a bounded `Retry-After` on 429. Do not replay
  `LoadNextEvent` after an ambiguous failure. Do not retry parser or response
  validation failures.
- [ ] **Classify failures.** Distinguish invalid user input, timeout/transport,
  HTTP status, rate limiting, and invalid response shape. Keep exit code `2` for
  user input and `3` for site/network failures. Offer manual retry only where the
  operation is safe to repeat.
- [ ] **Lock machine-output contracts.** Test exact TSV columns and escaping;
  search, detail, and filter JSON fields; null and datetime encoding; empty
  stdout on failure; stderr isolation; and additive-only JSON changes.

## P1 - Core UX

- [ ] **Add date and ongoing controls to the TUI filter screen.** Show current
  values, validate text dates, reject an end date before the start date, and
  include the values in active-filter status.
- [ ] **Make `i` load registration details on demand.** Perform one deduplicated
  detail request, show progress, and open only a validated official registration
  URL. Never submit registration data.
- [ ] **Add `mpk show TARGET --registration-url`.** Print the validated external
  registration URL. Return a clear result when no link exists. Do not open a
  browser or imply that registration is performed.
- [ ] **Normalize registration status for display.** Centralize multilingual
  mapping to `OPEN`, `CLOSED`, `FULL`, or `UNKNOWN`; retain the original status
  string unchanged. Keep temporal state such as an ongoing event separate.
- [ ] **Add sanitized diagnostics.** Use standard logging for endpoint name,
  status, elapsed time, pagination counts, cache outcomes, and retry decisions.
  Never log query strings, event tokens, cookies, headers, form bodies, search
  text, contacts, scraped prose, or full exception URLs. Keep stdout clean.
- [ ] **Report configuration and vocabulary outcomes.** Make `mpk config` show
  malformed TOML/type fallbacks. Return structured vocabulary outcomes for cache
  hit, refresh, and stale fallback so the TUI can display them.
- [ ] **Verify monochrome behavior.** Test `NO_COLOR`, monochrome terminals, and
  status symbols before considering another theme mode.
- [ ] **Add local result sorting.** Support `--sort start|city|title|status` and
  `--reverse` for the finite fetched set. Preserve server order by default and
  keep history row order identical to rendered output.

## P2 - Optional Features

- [ ] **Add config-defined saved searches.** Parse typed `[queries.NAME]`
  entries and add `mpk run NAME`. Queries are manually edited in TOML; do not
  add CLI or TUI CRUD. Apply the same 200-result cap and document that names and
  search text are stored locally.
- [ ] **Add minimal single-event ICS export.** Export one explicitly selected
  event using floating local times and a non-reversible UID. Exclude contacts,
  raw prose, registration URLs, and event tokens. Do not export result sets or
  fetch details in bulk.
- [ ] **Add cache-only shell completion.** Complete filter labels from an
  existing vocabulary cache. Missing or invalid cache data must produce no
  completions and no network or write operations.
- [ ] **Defer incremental TUI results until cancellation is implemented.** After
  request caps and cooperative cancellation exist, evaluate current-generation
  page updates. Partial rows must not be persisted; define selection and failure
  behavior before implementation.

## Verification

- [ ] Add synthetic multilingual fixtures when a parser change or newly observed
  response shape requires them. Keep fixture data invented and minimal.
- [ ] Add tests with each item above. Remaining search coverage includes limit
  truncation, callback exceptions, history write failures, stale page callbacks,
  cancellation, and retry exhaustion.
- [ ] Review branch coverage for meaningful failure paths without a percentage
  gate.
- [ ] Run one low-limit live smoke with isolated XDG directories before a
  release and after HTTP-facing changes.

## Non-Goals

- Recurring polling, `watch`, desktop notifications, or scheduled collection.
- Persistent event-detail caches. Full details remain in memory for the current
  process only.
- Bulk detail enrichment, result-set ICS export, or detail-based bulk filters.
- Interface translation. Calendar content remains available in Finnish,
  English, and Swedish; interface text is not a localization commitment.
- Proximity search, geocoding, or bundled geographic datasets.
- PyPI, Homebrew, man-page, standalone executable, or platform-specific release
  work. Distribution remains GitHub source installation.
- Registration submission, cancellation, authentication, browser automation,
  telemetry, analytics, parallel pagination, or bundled vocabulary snapshots.
