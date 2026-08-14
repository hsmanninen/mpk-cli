"""Rendering: Rich tables for humans, JSON for machines, TSV for pipes."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import Event, EventDetail, FilterVocab


def _tsv_field(value: Any) -> str:
    """Flatten a value so it cannot add columns or records to TSV output."""
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _fmt_dt(dt: datetime | None, *, with_time: bool = True) -> str:
    if dt is None:
        return ""
    if not with_time or (dt.hour == 0 and dt.minute == 0):
        return dt.strftime("%d.%m.%Y")
    return dt.strftime("%d.%m.%Y %H:%M")


def _fmt_period(start: datetime | None, end: datetime | None) -> str:
    if start is None and end is None:
        return ""
    if start and end and start.date() == end.date():
        return _fmt_dt(start)
    return f"{_fmt_dt(start)} – {_fmt_dt(end)}".strip(" –")


def _status_style(status: str | None) -> str:
    if not status:
        return "dim"
    s = status.lower()
    if "täynnä" in s or "full" in s or "expired" in s or "päätty" in s:
        return "red"
    if "käynniss" in s or "in progress" in s or "pågår" in s:
        return "yellow"
    if "voi ilmoit" in s or "auki" in s or "open" in s:
        return "green"
    return "cyan"


# ---- listing ----------------------------------------------------------------


def render_events_table(
    events: list[Event],
    *,
    total: int | None,
    console: Console,
) -> None:
    header = "Koulutukset"
    if total is not None:
        header = f"Koulutukset ({len(events)}/{total})"
    else:
        header = f"Koulutukset ({len(events)})"

    table = Table(
        title=header,
        show_lines=False,
        title_style="bold cyan",
        header_style="bold",
        expand=True,
    )
    table.add_column("#", justify="right", style="dim", no_wrap=True, width=4)
    table.add_column("Alkaa", no_wrap=True)
    table.add_column("Päättyy", no_wrap=True)
    table.add_column("Kaupunki", no_wrap=True)
    table.add_column("Nimi", overflow="fold", ratio=3)
    table.add_column("Tila", no_wrap=True)

    for i, ev in enumerate(events, 1):
        table.add_row(
            str(i),
            _fmt_dt(ev.start),
            _fmt_dt(ev.end),
            Text(ev.city or ""),
            Text(ev.title, style="bold"),
            Text(ev.registration_status or "", style=_status_style(ev.registration_status)),
        )
    console.print(table)


def render_events_tsv(events: list[Event]) -> None:
    """Plain TSV for pipes / non-TTY stdout."""
    cols = ["idx", "id", "title", "start", "end", "city", "status", "url"]
    print("\t".join(cols))
    for i, ev in enumerate(events, 1):
        row = [
            str(i),
            ev.id,
            ev.title.replace("\t", " "),
            ev.start.isoformat() if ev.start else "",
            ev.end.isoformat() if ev.end else "",
            (ev.city or "").replace("\t", " "),
            (ev.registration_status or "").replace("\t", " "),
            ev.url,
        ]
        print("\t".join(_tsv_field(value) for value in row))


def render_events_json(
    events: list[Event],
    *,
    total: int | None,
) -> None:
    payload = {"total": total, "count": len(events), "events": [e.to_dict() for e in events]}
    print(json.dumps(payload, ensure_ascii=False, indent=2))


# ---- detail -----------------------------------------------------------------


# Field labels (all languages) that map to something already shown in the
# structured panel — we skip these when spilling remaining raw_fields as prose.
_STRUCTURED_LABELS: frozenset[str] = frozenset(
    {
        # Finnish
        "Ajankohta",
        "Tapahtumapaikka",
        "Koulutusmuoto",
        "Kesto",
        "Hinta",
        "Järjestäjä",
        "Kurssin johtajan yhteystiedot",
        "Kohderyhmä",
        "Tapahtuman kuvaus",
        "Tavoitteet",
        # English
        "Time",
        "Location",
        "Training form",
        "Duration",
        "Price",
        "Organizer",
        "Course leader contact information",
        "Target group",
        "Event description",
        "Goals",
        # Swedish
        "Tid",
        "Plats",
        "Kursform",
        "Längd",
        "Pris",
        "Arrangör",
        "Kursledarens kontaktuppgifter",
        "Målgrupp",
        "Beskrivning av evenemanget",
        "Mål",
    }
)


def render_event_detail(detail: EventDetail, *, console: Console) -> None:
    header = Text(detail.title, style="bold cyan")
    subtitle_parts = [_fmt_period(detail.start, detail.end)]
    if detail.city:
        subtitle_parts.append(detail.city)
    if detail.location:
        subtitle_parts.append(detail.location)
    subtitle = "  •  ".join(p for p in subtitle_parts if p)

    body = Table.grid(padding=(0, 1))
    body.add_column(style="bold", no_wrap=True)
    body.add_column()

    def _short(v: str | None) -> str | None:
        """Flatten a possibly multi-line short value into a single line for the panel."""
        if v is None:
            return None
        collapsed = " ".join(part.strip() for part in v.splitlines() if part.strip())
        return collapsed or None

    def _row(k: str, v: str | None) -> None:
        if v:
            body.add_row(k + ":", Text(v))

    _row("Ajankohta", _fmt_period(detail.start, detail.end))
    _row("Paikka", _short(detail.location))
    _row("Kaupunki", detail.city)
    _row("Koulutusmuoto", _short(detail.mode))
    _row("Kesto", _short(detail.duration))
    _row("Hinta", _short(detail.price))
    _row("Järjestäjä", _short(detail.organizer))
    _row("Yhteystiedot", _short(detail.contact))
    if detail.target_groups:
        _row("Kohderyhmä", ", ".join(detail.target_groups))
    if detail.registration_url:
        _row("Ilmoittautuminen", detail.registration_url)
    if detail.registration_deadline:
        _row("Avoinna", detail.registration_deadline)
    _row("URL", detail.url)

    panel_subtitle = Text(subtitle) if subtitle else None
    console.print(Panel.fit(body, title=header, subtitle=panel_subtitle, border_style="cyan"))

    if detail.description:
        console.print()
        console.print(Text("Kuvaus", style="bold underline"))
        console.print(Text(detail.description))
    if detail.goals:
        console.print()
        console.print(Text("Tavoitteet", style="bold underline"))
        console.print(Text(detail.goals))
    if detail.target_group_note:
        console.print()
        console.print(Text("Kohderyhmä", style="bold underline"))
        console.print(Text(detail.target_group_note))

    # Spill any remaining prose fields that weren't captured by the structured
    # dataclass fields (e.g. "Keskeinen sisältö", "Muut tiedot", ...). Their
    # order is preserved from the source document.
    for label, value in detail.raw_fields.items():
        if not value:
            continue
        if label in _STRUCTURED_LABELS:
            continue
        console.print()
        console.print(Text(label, style="bold underline"))
        console.print(Text(value))


def render_event_detail_json(detail: EventDetail) -> None:
    print(json.dumps(detail.to_dict(), ensure_ascii=False, indent=2))


# ---- filters ---------------------------------------------------------------


def render_filter_vocab(vocab: FilterVocab, *, console: Console) -> None:
    def _table(name: str, options: list[Any]) -> Table:
        t = Table(title=name, title_style="bold cyan", header_style="bold", show_lines=False)
        t.add_column("Arvo", style="dim", no_wrap=True)
        t.add_column("Nimi")
        for opt in options:
            t.add_row(Text(opt.value), Text(opt.label))
        return t

    language = Text("Kieli: ", style="bold")
    language.append(vocab.lang)
    console.print(language)
    for name, attr in [
        ("Kaupungit", "cities"),
        ("Piirit", "districts"),
        ("Aiheet", "specializations"),
        ("Kohderyhmät", "target_groups"),
        ("Tyypit", "types"),
        ("Koulutusmuodot", "implementation_modes"),
    ]:
        opts = getattr(vocab, attr)
        if opts:
            console.print(_table(f"{name} ({len(opts)})", opts))


def render_filter_vocab_json(vocab: FilterVocab) -> None:
    print(json.dumps(vocab.to_dict(), ensure_ascii=False, indent=2))


# ---- console factory --------------------------------------------------------


def make_console(*, force_terminal: bool | None = None) -> Console:
    """Create a Console that plays nicely with pipes."""
    if force_terminal is None:
        force_terminal = sys.stdout.isatty()
    return Console(force_terminal=force_terminal, soft_wrap=False)
