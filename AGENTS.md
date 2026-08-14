# AGENTS.md

Instructions for coding agents working on `mpk`. User documentation is in
`README.md`; pending work is in `TODO.md`.

## Scope

`mpk` is a Python 3.11+ CLI and Textual TUI for the public MPK
Koulutuskalenteri. It reads server-rendered HTML. It has no authentication or
write operations.

## Required Invariants

- Keep default tests offline. Live tests require `@pytest.mark.live` and explicit
  selection.
- Keep calendar requests sequential. Preserve the 0.4 second pagination pause.
- Do not add registration, cancellation, authentication, telemetry, or browser
  automation.
- Keep persistent files under `platformdirs`; write through a same-directory
  temporary file, `fsync`, and `os.replace`.
- Preserve output modes: Rich table on TTY, TSV on non-TTY, JSON with `--json`.
- Ask before adding a dependency.
- Use `from __future__ import annotations`, public type hints, and ASCII unless
  source data or existing content requires Unicode.

## Modules

| Path | Responsibility |
|---|---|
| `cli.py` | Typer commands and output-mode selection |
| `client.py` | HTTP session, headers, cookies, bootstrap |
| `search.py` | form encoding, pagination, detail fetch |
| `parse.py` | search, detail, and vocabulary HTML parsing |
| `vocab.py` | vocabulary cache, refresh, fuzzy resolution |
| `config.py` | TOML configuration and saved defaults |
| `history.py` | latest accepted search |
| `render.py` | Rich, TSV, and JSON output |
| `tui/requests.py` | serialization of TUI site access |
| `tui/screens/` | browse, detail, filter, and help screens |

## HTTP And Parser Constraints

- Bootstrap `/Calendar/` before search or detail requests. Pagination state is
  stored in session cookies.
- Encode `SearchQuery.to_form_data()` with `urlencode()` and send it through
  `content=`. `httpx` 0.28 rejects `data=list[tuple]`.
- `/Calendar/LoadNextEvent` is stateful. Do not fetch pages concurrently.
- Event tokens may be double URL encoded. Preserve encoded tokens rather than
  decoding and re-encoding them.
- Total counts come from localized `Koulutuksia (N)`, `Events (N)`, or
  `Utbildningar (N)` text.
- Event titles come from `og:title` or `<title>`, not `h1.calendar_title`.
- `selectolax` grouped selectors do not preserve document order. Detail field
  pairing must iterate all `label` nodes and inspect classes.
- The site emits non-standard `<br \>`. Keep `<br>` matching liberal:
  `r"<br\b[^>]*>"`.
- Preserve paragraph and list structure in prose fields.
- Keep formal target-group values separate from target-group prose.
- Preserve duplicate city labels and casing; backend values are exact.
- Validate search, detail, vocabulary, event, and registration response shapes
  and URLs before accepting them.
- Treat scraped strings as untrusted terminal content. Use `Text` or
  `markup=False`; sanitize every TSV field.

## TUI Constraints

- Run blocking site access in `run_worker(..., thread=True)` through the shared
  `RequestCoordinator`.
- Update widgets only on the Textual thread through `app.call_from_thread(...)`.
- Keep the initial search in `BrowseScreen.on_mount`.
- Load details only after explicit selection. Do not add background detail
  enrichment.
- Persist history only after the current search generation is accepted.
- Preserve selected filter values while filtering option labels.
- Do not name a `Screen` method `_render`; Textual reserves it.
- Keep Textual `BINDINGS`, `SCREENS`, and `DEFAULT_CSS` as class literals. The
  TUI Ruff configuration intentionally ignores `RUF012`.
- In tests, patch imports at their use site, such as
  `mpk.tui.screens.browse.run_search`.

## Fixtures And Tests

- Parser changes require synthetic fixture coverage in `tests/fixtures/`.
- Fixtures must use invented names, reserved domains, and non-reusable tokens.
  Do not commit production responses or personal data.
- Tests block sockets by default in `tests/conftest.py`.
- Cache schema changes require a `SCHEMA_VERSION` bump.
- CLI errors use exit code `2` for user input and `3` for network/server errors.

Run before completion:

```bash
uv run pytest
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv lock --check
```

Run `uv build --no-sources` for packaging changes. For HTTP-facing changes, run
one low-limit live smoke with isolated XDG directories as documented in
`README.md`.
