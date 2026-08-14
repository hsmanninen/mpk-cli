from __future__ import annotations

import io

from conftest import read
from rich.console import Console

from mpk.models import Event, FilterOption, FilterVocab
from mpk.parse import parse_event_detail
from mpk.render import (
    render_event_detail,
    render_events_table,
    render_events_tsv,
    render_filter_vocab,
)


def _render_to_string(detail) -> str:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=200)
    render_event_detail(detail, console=console)
    return buf.getvalue()


def test_render_event_detail_shows_all_prose_fields() -> None:
    detail = parse_event_detail(read("event.html"))
    detail.url = "https://koulutuskalenteri.mpk.fi/Calendar/Event?d=test"
    output = _render_to_string(detail)

    # Structured fields shown once (in the panel), not duplicated as prose.
    assert "Koulutusmuoto" in output
    assert "Kesto" in output

    # Named prose fields.
    assert "Kuvaus" in output
    assert "Osallistuja perehtyy taisteluensiavun perusteisiin." in output
    assert "Tavoitteet" in output

    # Kohderyhmä: compact list in the panel + prose note in its own section.
    assert "Kohderyhmä" in output
    assert "Reserviläiset" in output
    assert "reserviläisille" in output.lower()

    # The critical fix: spill remaining raw_fields as their own sections.
    assert "Keskeinen sisältö" in output
    assert "opetuspaketti" in output.lower()


def test_render_skips_empty_raw_fields() -> None:
    detail = parse_event_detail(read("event.html"))
    # forcibly add an empty extra field
    detail.raw_fields["Muut tiedot"] = ""
    output = _render_to_string(detail)
    assert "Muut tiedot" not in output


def test_render_does_not_duplicate_structured_labels() -> None:
    detail = parse_event_detail(read("event.html"))
    output = _render_to_string(detail)
    # "Koulutusmuoto" appears exactly once (as a row label).
    assert output.count("Koulutusmuoto") == 1
    # "Kohderyhmä" appears twice: once as the compact panel row, once as the
    # prose-note section header.
    assert output.count("Kohderyhmä") == 2


def test_render_event_detail_treats_scraped_text_as_literal_markup() -> None:
    detail = parse_event_detail(
        '<meta property="og:title" content="[bold]Title[/bold]">'
        '<label class="calendar_label_bold">Muut tiedot:</label>'
        '<label class="calendar_label_info">[red]Do not style[/red]</label>'
    )
    output = _render_to_string(detail)
    assert "[bold]Title[/bold]" in output
    assert "[red]Do not style[/red]" in output


def test_render_tables_treat_scraped_text_as_literal_markup() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=200)
    event = Event(id="id", url="https://example.test", title="[bold]Title[/bold]", city="[red]City")
    render_events_table([event], total=1, console=console)
    render_filter_vocab(
        FilterVocab(lang="[blue]en", cities=[FilterOption(value="[1]", label="[green]City")]),
        console=console,
    )
    output = buf.getvalue()
    assert "[bold]Title[/bold]" in output
    assert "[red]City" in output
    assert "[blue]en" in output
    assert "[green]City" in output


def test_render_events_tsv_sanitizes_every_field(capsys) -> None:
    event = Event(
        id="id\twith-tab",
        url="https://example.test/a\r\nb",
        title="line one\nline two",
        city="city\rcarriage",
        registration_status="open\tsoon\nnow",
    )
    render_events_tsv([event])
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert len(lines[1].split("\t")) == 8
    assert "\r" not in lines[1]
    assert "line one line two" in lines[1]
    assert "id with-tab" in lines[1]
