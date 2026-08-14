# mpk

`mpk` searches the public [MPK Koulutuskalenteri](https://koulutuskalenteri.mpk.fi/Calendar/)
from a Textual TUI or a one-shot command line interface.

This is an unofficial project. It is not affiliated with or supported by MPK.
Use MPK's official services for registrations, accounts, payments, and course
support.

## Features

- Search by text, date, city, district, subject, target group, event type, and
  delivery mode.
- Finnish, English, and Swedish calendar content.
- TUI on a suitable terminal; Rich table with `--classic`; TSV when piped;
  JSON with `--json`.
- Fuzzy matching for human-readable filter values.
- Cached filter vocabulary with per-language freshness timestamps.
- Event detail view and external registration link.
- Local history for `mpk show N`.

## Installation

Requires Python 3.11 or newer. The distribution name is `mpk-cli`; the command
is `mpk`.

```bash
uv tool install git+https://github.com/hsmanninen/mpk-cli.git
```

Or run from a checkout:

```bash
git clone https://github.com/hsmanninen/mpk-cli.git
cd mpk-cli
uv sync --frozen
uv run mpk
```

`pipx install git+https://github.com/hsmanninen/mpk-cli.git` is also supported.

## Usage

```bash
mpk
mpk search ensiapu
mpk search --city Helsinki --topic Ensiapu
mpk search ensiapu --classic
mpk search --topic Ensiapu --json
mpk search --from 2026-09-01 --to 2026-11-30 --classic
mpk filters
mpk filters --refresh
mpk show 2
mpk show 2 --json
mpk config
```

Use `mpk --help` and `mpk COMMAND --help` for the complete command reference.

### Output selection

The TUI starts when stdin and stdout are TTYs, the terminal is at least 70x20,
and TUI use is enabled. The classic path is used when output is redirected or
when `--classic`, `--json`, `--open`, `--all`, or `MPK_NO_TUI=1` is present.

- TTY classic output: Rich table.
- Non-TTY output: TSV.
- `--json`: JSON.

Exit codes are `0` for success, `2` for invalid user input, and `3` for network
or server errors.

### TUI

Event details are fetched only after explicit selection and cached for the TUI
session. Moving the highlight does not make a network request.

| Key | Action |
|---|---|
| `/` | Focus search |
| `Enter` | Run search or load selected event |
| `Up`, `Down` | Move selection |
| `f` | Open filters |
| `x` | Clear filters |
| `r` | Repeat search |
| `l` | Cycle `fi`, `en`, `sv` |
| `o` | Open event URL |
| `i` | Open registration link after detail load |
| `y` | Copy event URL |
| `?`, `F1` | Help |
| `q`, `Ctrl+Q` | Quit |

The filter screen uses `Space` to toggle, `Ctrl+Enter` to apply, `Ctrl+S` to
save startup defaults, and `Ctrl+R` to remove saved defaults.

## Configuration

`mpk config` prints the resolved values and paths. Paths are provided by
`platformdirs` and honor XDG environment variables.

```toml
[cache]
filters_ttl_days = 30
allow_network_refresh = true

[defaults]
lang = "fi"
include_ongoing = true
limit = 50

[defaults.filters]
cities = ["Helsinki"]
districts = []
specializations = ["1002"]
target_groups = []
modes = ["1"]
types = []

[tui]
enabled = true
theme = "auto"
page_size = 50
show_registration_status = true
```

With `allow_network_refresh = false`, missing cache data produces an error
instead of a network request. `mpk filters --refresh` is an explicit refresh
and is not blocked by that setting.

## Local State

- `filters.json`: filter values and per-language fetch metadata.
- `last-results.json`: latest accepted search, used by `mpk show N`.
- `yank.txt`: clipboard fallback when no system clipboard is available.
- `config.toml`: optional configuration and saved TUI defaults.

Persistent writes use a temporary file, `fsync`, and atomic replacement.
`mpk config` and `mpk filters --show-path` print the resolved platform paths.

The filter cache is refreshed when missing, stale, explicitly refreshed, or
when a supplied filter value cannot be resolved. A failed refresh may fall back
to existing stale data. Filter labels are stored separately for each language.

## Responsible Use

On 2026-08-14, [`mpk.fi/robots.txt`](https://mpk.fi/robots.txt) allowed
crawling. The calendar subdomain returned no `robots.txt`. No public calendar
API or explicit automation terms were found in MPK's published
[privacy information](https://mpk.fi/tietosuojaseloste/),
[FAQ](https://mpk.fi/usein-kysytyt-kysymykset/), or calendar pages. These facts
may change and do not grant access rights.

The client identifies itself, serializes calendar requests, and pauses between
paginated requests. Do not use it for bulk collection, aggressive polling,
service degradation, or collection and republication of personal information.
Follow current MPK instructions and operator requests.

## Development

```bash
uv sync --frozen --extra dev
uv run pytest
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv lock --check
uv build --no-sources
```

Default tests are offline, exclude tests marked `live`, and block socket access.
Parser fixtures are synthetic and contain no production event tokens or personal
data.

For an explicit live smoke test, isolate local state:

```bash
MPK_TMP_XDG=$(mktemp -d)
XDG_CONFIG_HOME="$MPK_TMP_XDG/config" \
XDG_CACHE_HOME="$MPK_TMP_XDG/cache" \
  uv run mpk search ensiapu --limit 3 --classic
```

Keep changes covered by offline tests. Parser fixtures must use invented data
and reserved domains. Do not publish credentials, cookies, personal information,
or reusable event tokens. MPK service matters belong with
[MPK](https://mpk.fi/yhteystiedot/), not this project.

## License

[0BSD](LICENSE)
