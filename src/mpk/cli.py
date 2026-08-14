"""Command-line interface for mpk."""

from __future__ import annotations

import os
import re
import sys
import webbrowser
from datetime import date
from enum import StrEnum
from typing import Annotated

import typer
from dateutil import parser as dateparser
from rich.console import Console

from . import __version__
from .config import load_config
from .history import resolve_row as resolve_last_row
from .paths import config_file, filters_cache_file, last_results_file
from .render import (
    make_console,
    render_event_detail,
    render_event_detail_json,
    render_events_json,
    render_events_table,
    render_events_tsv,
    render_filter_vocab,
    render_filter_vocab_json,
)
from .search import SearchQuery, fetch_event_detail, run_search
from .vocab import (
    VocabError,
    VocabRefreshError,
    get_vocab,
    load_cache,
    refresh_cache,
    resolve_with_auto_refresh,
    save_cache,
)


class Lang(StrEnum):
    fi = "fi"
    en = "en"
    sv = "sv"


class Mode(StrEnum):
    verkko = "verkko"
    lähi = "lähi"
    lahi = "lahi"
    monimuoto = "monimuoto"


class EventType(StrEnum):
    koulutus = "koulutus"
    tukeminen = "tukeminen"


app = typer.Typer(
    name="mpk",
    help="Interactive TUI and command-line search for the MPK Koulutuskalenteri.",
    no_args_is_help=False,
    add_completion=True,
    rich_markup_mode="rich",
)


def _version_cb(value: bool) -> None:
    if value:
        typer.echo(f"mpk {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_cb, is_eager=True, help="Show version and exit."
        ),
    ] = False,
) -> None:
    """MPK Koulutuskalenteri CLI.

    Run without arguments to launch the interactive TUI. Use subcommands
    for scripted / non-interactive usage.
    """
    if ctx.invoked_subcommand is None:
        # Bare `mpk` launches the TUI. Falls back to help when TUI is disabled.
        if _tui_available():
            try:
                cfg = load_config()
                _launch_tui(lang=cfg.defaults.lang, config=cfg)
            except Exception as e:
                _err(make_console(), f"TUI failed to start: {e}")
                raise typer.Exit(3) from e
        else:
            typer.echo(ctx.get_help())


# ---- helpers ---------------------------------------------------------------


def _parse_date_opt(s: str | None) -> date | None:
    if not s:
        return None
    try:
        # Prefer dayfirst=True for Finnish-friendly dd.mm.yyyy input.
        return dateparser.parse(s, dayfirst=True, fuzzy=False).date()
    except (ValueError, dateparser.ParserError) as e:
        raise typer.BadParameter(f"Could not parse date {s!r}: {e}") from e


def _err(console: Console, message: str) -> None:
    Console(stderr=True).print(f"[red]error:[/red] {message}")


def _print_suggestions(console: Console, field: str, suggestions: list[str]) -> None:
    if not suggestions:
        return
    Console(stderr=True).print(
        f"[yellow]tip:[/yellow] closest matches for {field}: {', '.join(suggestions)}"
    )


def _tui_available() -> bool:
    """Decide whether the TUI can/should be launched right now."""
    if os.environ.get("MPK_NO_TUI"):
        return False
    if not sys.stdout.isatty() or not sys.stdin.isatty():
        return False
    try:
        cfg = load_config()
    except Exception:
        return False
    if not cfg.tui.enabled:
        return False
    # Terminal size sanity — Textual will look broken below this.
    try:
        size = os.get_terminal_size()
        if size.lines < 20 or size.columns < 70:
            return False
    except OSError:
        pass
    return True


def _launch_tui(
    *,
    initial_query: str = "",
    initial_filters=None,
    lang: str = "fi",
    begin: date | None = None,
    end: date | None = None,
    include_ongoing: bool = True,
    config=None,
    vocab=None,
    cache=None,
) -> None:
    from .tui import launch as tui_launch  # local import: keeps CLI startup snappy

    tui_launch(
        initial_query=initial_query,
        initial_filters=initial_filters,
        lang=lang,
        begin=begin,
        end=end,
        include_ongoing=include_ongoing,
        config=config,
        vocab=vocab,
        cache=cache,
    )


# ---- search ----------------------------------------------------------------


@app.command("search")
def search_cmd(
    query: Annotated[
        list[str] | None,
        typer.Argument(help="Free-text query. Multiple words are joined with spaces."),
    ] = None,
    from_: Annotated[
        str | None,
        typer.Option(
            "--from", "-f", help="Start date (default: today). Accepts dd.mm.yyyy or ISO."
        ),
    ] = None,
    to: Annotated[
        str | None,
        typer.Option("--to", "-t", help="End date (inclusive)."),
    ] = None,
    city: Annotated[
        list[str] | None,
        typer.Option("--city", "-c", help="Filter by city. Repeatable."),
    ] = None,
    district: Annotated[
        list[str] | None,
        typer.Option("--district", "-d", help="Filter by district / MPK-piiri. Repeatable."),
    ] = None,
    topic: Annotated[
        list[str] | None,
        typer.Option("--topic", help="Filter by subject (aihe). Repeatable."),
    ] = None,
    target: Annotated[
        list[str] | None,
        typer.Option("--target", help="Filter by target group (kohderyhmä). Repeatable."),
    ] = None,
    mode: Annotated[
        list[Mode] | None,
        typer.Option("--mode", help="Filter by delivery mode. Repeatable."),
    ] = None,
    type_: Annotated[
        list[EventType] | None,
        typer.Option("--type", help="Filter by event type. Repeatable."),
    ] = None,
    include_ongoing: Annotated[
        bool | None,
        typer.Option(
            "--include-ongoing/--no-include-ongoing",
            help="Show ongoing events that are still open for registration.",
        ),
    ] = None,
    lang: Annotated[Lang | None, typer.Option("--lang", "-l", help="Site language.")] = None,
    limit: Annotated[
        int | None, typer.Option("--limit", "-n", help="Maximum results to fetch.")
    ] = None,
    all_: Annotated[
        bool,
        typer.Option("--all", help="Fetch every match (ignores --limit)."),
    ] = False,
    json_out: Annotated[bool, typer.Option("--json", help="Emit JSON to stdout.")] = False,
    classic: Annotated[
        bool,
        typer.Option(
            "--classic/--no-classic",
            help="Force the classic one-shot table output instead of the TUI.",
        ),
    ] = False,
    open_: Annotated[
        int | None,
        typer.Option("--open", help="After listing, open the Nth result in the default browser."),
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Log to stderr.")] = False,
) -> None:
    """Search training courses & events.

    With a TTY and no scripting flags (--json, --open, --all), this launches
    the interactive TUI pre-populated with the given query and filters.
    Pass --classic to force the old one-shot table output.
    """
    console = make_console()
    cfg = load_config()
    lang_str = lang.value if lang is not None else cfg.defaults.lang
    include_ongoing_value = (
        include_ongoing if include_ongoing is not None else cfg.defaults.include_ongoing
    )
    limit_value = limit if limit is not None else cfg.defaults.limit
    if limit_value < 1:
        raise typer.BadParameter("--limit must be at least 1", param_hint="--limit")

    begin = _parse_date_opt(from_)
    end = _parse_date_opt(to)
    if begin is not None and end is not None and end < begin:
        raise typer.BadParameter("--to must be on or after --from", param_hint="--to")

    saved_filters = cfg.defaults.filters
    resolved: dict[str, list[str]] = {
        "cities": list(saved_filters.cities),
        "districts": list(saved_filters.districts),
        "specializations": list(saved_filters.specializations),
        "target_groups": list(saved_filters.target_groups),
        "types": list(saved_filters.types),
        "implementation_modes": list(saved_filters.modes),
    }
    resolved_options: dict[str, list] = {k: [] for k in resolved}
    inputs = [
        ("cities", city or [], "city"),
        ("districts", district or [], "district"),
        ("specializations", topic or [], "topic"),
        ("target_groups", target or [], "target group"),
        ("types", [t.value for t in (type_ or [])], "type"),
        ("implementation_modes", [m.value for m in (mode or [])], "mode"),
    ]
    scripting_flags = json_out or all_ or (open_ is not None)
    launch_tui = not classic and not scripting_flags and _tui_available()
    needs_vocab = launch_tui or any(values for _, values, _ in inputs)
    vocab = cache = None
    if needs_vocab:
        try:
            vocab, cache = get_vocab(lang_str, config=cfg, verbose=verbose)
        except Exception as e:
            _err(console, f"failed to load filter vocabulary: {e}")
            raise typer.Exit(3) from e

        for field, vocab_field in (
            ("cities", "cities"),
            ("districts", "districts"),
            ("specializations", "specializations"),
            ("target_groups", "target_groups"),
            ("types", "types"),
            ("implementation_modes", "implementation_modes"),
        ):
            wanted = set(resolved[field])
            resolved_options[field] = [
                option for option in getattr(vocab, vocab_field) if option.value in wanted
            ]

    for field, values, human_name in inputs:
        if not values:
            continue
        resolved[field] = []
        resolved_options[field] = []
        try:
            opts, vocab, cache = resolve_with_auto_refresh(
                vocab, cache, field, values, lang=lang_str, config=cfg, verbose=verbose
            )
        except VocabError as e:
            _err(console, str(e))
            _print_suggestions(console, human_name, e.suggestions)
            raise typer.Exit(2) from e
        except VocabRefreshError as e:
            _err(console, str(e))
            raise typer.Exit(3) from e
        resolved[field] = [o.value for o in opts]
        resolved_options[field] = list(opts)

    if launch_tui:
        from .tui.screens.browse import ActiveFilters

        filters = ActiveFilters(
            cities=resolved_options["cities"],
            districts=resolved_options["districts"],
            specializations=resolved_options["specializations"],
            target_groups=resolved_options["target_groups"],
            modes=resolved_options["implementation_modes"],
            types=resolved_options["types"],
        )
        _launch_tui(
            initial_query=" ".join(query) if query else "",
            initial_filters=filters,
            lang=lang_str,
            begin=begin,
            end=end,
            include_ongoing=include_ongoing_value,
            config=cfg,
            vocab=vocab,
            cache=cache,
        )
        return

    q = SearchQuery(
        text=" ".join(query) if query else None,
        begin=begin,
        end=end,
        include_ongoing=include_ongoing_value,
        lang=lang_str,
        cities=resolved["cities"],
        districts=resolved["districts"],
        specializations=resolved["specializations"],
        target_groups=resolved["target_groups"],
        types=resolved["types"],
        implementation_modes=resolved["implementation_modes"],
    )

    try:
        result = run_search(
            q,
            limit=None if all_ else limit_value,
            fetch_all=all_,
            verbose=verbose,
        )
    except Exception as e:
        _err(console, f"search failed: {e}")
        raise typer.Exit(3) from e

    if json_out:
        render_events_json(result.events, total=result.total)
    elif not sys.stdout.isatty():
        render_events_tsv(result.events)
    else:
        render_events_table(result.events, total=result.total, console=console)
        if result.events:
            console.print(
                "[dim]tip: [bold]mpk show N[/bold] to view row N • "
                "[bold]--open N[/bold] to open in browser • "
                "[bold]--json[/bold] for scripting[/dim]"
            )

    if open_ is not None:
        idx = open_ - 1
        if idx < 0 or idx >= len(result.events):
            _err(console, f"--open {open_} out of range (1..{len(result.events)})")
            raise typer.Exit(2)
        webbrowser.open(result.events[idx].url)


@app.command("tui")
def tui_cmd(
    lang: Annotated[Lang | None, typer.Option("--lang", "-l", help="Site language.")] = None,
) -> None:
    """Launch the interactive TUI explicitly."""
    if not _tui_available():
        typer.echo(
            "TUI cannot start: not a TTY, disabled in config, or terminal too small.\n"
            "Use `mpk search --classic` for the one-shot table output.",
            err=True,
        )
        raise typer.Exit(2)
    try:
        cfg = load_config()
        _launch_tui(lang=lang.value if lang is not None else cfg.defaults.lang, config=cfg)
    except Exception as e:
        _err(make_console(), f"TUI failed to start: {e}")
        raise typer.Exit(3) from e


# ---- show ------------------------------------------------------------------


@app.command("show")
def show_cmd(
    target: Annotated[
        str,
        typer.Argument(
            metavar="N | URL",
            help=(
                "One of: a row number from the last `mpk search` (e.g. 2), "
                "a full /Calendar/Event URL, or a raw event id token."
            ),
        ),
    ],
    lang: Annotated[Lang | None, typer.Option("--lang", "-l", help="Site language.")] = None,
    json_out: Annotated[bool, typer.Option("--json", help="Emit JSON to stdout.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Log to stderr.")] = False,
) -> None:
    """Show a single event's full details.

    The argument can be:

      • an integer row number from the most recent `mpk search` output,
      • the full event URL (https://koulutuskalenteri.mpk.fi/Calendar/Event?d=…),
      • or the raw `d=` token (as emitted by `mpk search --json`).
    """
    console = make_console()
    cfg = load_config()
    lang_str = lang.value if lang is not None else cfg.defaults.lang

    id_or_url = target
    # If it's a bare positive integer, resolve against the last search cache.
    if re.fullmatch(r"\d+", target.strip()):
        try:
            ev = resolve_last_row(int(target.strip()))
        except LookupError as e:
            _err(console, str(e))
            raise typer.Exit(2) from e
        id_or_url = ev.url

    try:
        detail = fetch_event_detail(id_or_url, lang=lang_str, verbose=verbose)
    except ValueError as e:
        _err(console, str(e))
        raise typer.Exit(2) from e
    except Exception as e:
        _err(console, f"failed to fetch event: {e}")
        raise typer.Exit(3) from e

    if json_out:
        render_event_detail_json(detail)
    else:
        render_event_detail(detail, console=console)


# ---- filters ---------------------------------------------------------------


@app.command("filters")
def filters_cmd(
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Force refresh the cached filter vocabulary.")
    ] = False,
    lang: Annotated[Lang | None, typer.Option("--lang", "-l", help="Site language.")] = None,
    json_out: Annotated[bool, typer.Option("--json", help="Emit JSON to stdout.")] = False,
    show_path: Annotated[
        bool, typer.Option("--show-path", help="Print cache file path and exit.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Log to stderr.")] = False,
) -> None:
    """Inspect or refresh the cached filter vocabulary."""
    console = make_console()
    if show_path:
        typer.echo(str(filters_cache_file()))
        return

    cfg = load_config()
    lang_str = lang.value if lang is not None else cfg.defaults.lang

    if refresh:
        before = load_cache()
        try:
            after = refresh_cache(langs=[lang_str], existing=before, verbose=verbose)
            save_cache(after)
        except Exception as e:
            _err(console, f"refresh failed: {e}")
            raise typer.Exit(3) from e
        if not json_out:
            _print_vocab_diff(console, before, after, lang_str)
        vocab = after.languages[lang_str]
    else:
        try:
            vocab, _ = get_vocab(lang_str, config=cfg, verbose=verbose)
        except Exception as e:
            _err(console, f"failed to load filter vocabulary: {e}")
            raise typer.Exit(3) from e

    if json_out:
        render_filter_vocab_json(vocab)
    else:
        render_filter_vocab(vocab, console=console)


def _print_vocab_diff(console: Console, before, after, lang: str) -> None:
    if before is None or lang not in before.languages:
        console.print(f"[green]cache populated for '{lang}'.[/green]")
        return
    old = before.languages[lang]
    new = after.languages[lang]

    for field, label in [
        ("cities", "City"),
        ("districts", "District"),
        ("specializations", "Topic"),
        ("target_groups", "Target group"),
        ("types", "Type"),
        ("implementation_modes", "Mode"),
    ]:
        old_map = {o.value: o.label for o in getattr(old, field)}
        new_map = {o.value: o.label for o in getattr(new, field)}
        added = [f"{v} {new_map[v]!r}" for v in new_map if v not in old_map]
        removed = [f"{v} {old_map[v]!r}" for v in old_map if v not in new_map]
        for a in added:
            console.print(f"  [green]+ added[/green] {label}: {a}")
        for r in removed:
            console.print(f"  [red]- removed[/red] {label}: {r}")


# ---- config ----------------------------------------------------------------


@app.command("config")
def config_cmd(
    path: Annotated[bool, typer.Option("--path", help="Print config file path and exit.")] = False,
) -> None:
    """Show current configuration."""
    if path:
        typer.echo(str(config_file()))
        return
    cfg = load_config()
    typer.echo(f"config file:       {config_file()}")
    typer.echo(f"filters cache:     {filters_cache_file()}")
    typer.echo(f"last results:      {last_results_file()}")
    typer.echo("")
    typer.echo("[cache]")
    typer.echo(f"filters_ttl_days      = {cfg.cache.filters_ttl_days}")
    typer.echo(f"allow_network_refresh = {str(cfg.cache.allow_network_refresh).lower()}")
    typer.echo("")
    typer.echo("[defaults]")
    typer.echo(f"lang            = {cfg.defaults.lang!r}")
    typer.echo(f"include_ongoing = {str(cfg.defaults.include_ongoing).lower()}")
    typer.echo(f"limit           = {cfg.defaults.limit}")
    if cfg.defaults.filters.any_set():
        typer.echo("filters         = saved (see [defaults.filters] in config.toml)")
    else:
        typer.echo("filters         = none")
    typer.echo("")
    typer.echo("[tui]")
    typer.echo(f"enabled                  = {str(cfg.tui.enabled).lower()}")
    typer.echo(f"theme                    = {cfg.tui.theme!r}")
    typer.echo(f"page_size                = {cfg.tui.page_size}")
    typer.echo(f"show_registration_status = {str(cfg.tui.show_registration_status).lower()}")


if __name__ == "__main__":
    app()
