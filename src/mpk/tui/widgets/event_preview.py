"""Unified summary and detail rendering for the TUI."""

from __future__ import annotations

from datetime import datetime

from textual.containers import Grid, VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from ...models import Event, EventDetail


def format_period(start: datetime | None, end: datetime | None) -> str:
    if start is None and end is None:
        return ""
    if start and end and start.date() == end.date():
        date = start.strftime("%d.%m.%Y")
        if start.time() != datetime.min.time() or end.time() != datetime.min.time():
            return f"{date}  {start:%H:%M}-{end:%H:%M}"
        return date
    return " - ".join(value for value in (_format_datetime(start), _format_datetime(end)) if value)


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.hour == 0 and value.minute == 0:
        return value.strftime("%d.%m.%Y")
    return value.strftime("%d.%m.%Y %H:%M")


def _short(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = " ".join(part.strip() for part in value.splitlines() if part.strip())
    return collapsed or None


class EventPreview(VerticalScroll):
    """Render event data without interpreting site content as markup."""

    def show_empty(self) -> None:
        self._replace(
            Static("Valitse tapahtuma tuloksista.", classes="preview-empty", markup=False)
        )

    def show_summary(self, event: Event) -> None:
        children: list[Widget] = [
            Static("ESIKATSELU", classes="eyebrow", markup=False),
            Static(event.title, classes="preview-title", markup=False),
        ]
        children.append(self._metadata(event))
        children.append(
            Static(
                "Enter  lataa tiedot   o  avaa sivu   y  kopioi URL",
                classes="action-strip",
                markup=False,
            )
        )
        self._replace(*children)

    def show_loading(self, event: Event) -> None:
        self._replace(
            Static("TAPAHTUMA", classes="eyebrow", markup=False),
            Static(event.title, classes="preview-title", markup=False),
            Static(
                "Ladataan tapahtuman tietoja…",
                classes="preview-state",
                markup=False,
            ),
        )

    def show_error(self, event: Event, message: str) -> None:
        self._replace(
            Static("TAPAHTUMA", classes="eyebrow", markup=False),
            Static(event.title, classes="preview-title", markup=False),
            Static(
                f"Tietojen lataus epäonnistui: {message}", classes="preview-error", markup=False
            ),
            Static("Enter  yritä uudelleen   Esc  tuloksiin", classes="action-strip", markup=False),
        )

    def show_detail(self, detail: EventDetail) -> None:
        children: list[Widget] = [
            Static("TAPAHTUMA", classes="eyebrow", markup=False),
            Static(detail.title, classes="preview-title", markup=False),
        ]
        children.append(self._metadata(detail))
        registration = (
            "i  ilmoittaudu" if detail.registration_url else "i  ei ilmoittautumislinkkiä"
        )
        children.append(
            Static(
                f"o  avaa sivu   {registration}   y  kopioi URL",
                classes="action-strip",
                markup=False,
            )
        )
        for heading, value in (
            ("Kuvaus", detail.description),
            ("Tavoitteet", detail.goals),
            ("Kohderyhmä", detail.target_group_note),
        ):
            if value:
                children.append(Static(heading.upper(), classes="section-heading", markup=False))
                children.append(Static(value, classes="prose", markup=False))
        structured = {
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
        for heading, value in detail.raw_fields.items():
            if value and heading not in structured:
                children.append(Static(heading.upper(), classes="section-heading", markup=False))
                children.append(Static(value, classes="prose", markup=False))
        self._replace(*children)

    def _metadata(self, event: Event) -> Grid:
        values = [
            ("Ajankohta", format_period(event.start, event.end)),
            ("Paikka", _short(event.location)),
            ("Kaupunki", event.city),
            ("Muoto", _short(event.mode)),
        ]
        if isinstance(event, EventDetail):
            values.extend(
                [
                    ("Kesto", _short(event.duration)),
                    ("Hinta", _short(event.price)),
                    ("Järjestäjä", event.organizer),
                    ("Yhteystiedot", event.contact),
                    ("Kohderyhmä", ", ".join(event.target_groups)),
                    ("Avoinna", event.registration_deadline),
                ]
            )
        children: list[Static] = []
        for label, value in values:
            if not value:
                continue
            children.append(Static(label, classes="metadata-label", markup=False))
            children.append(Static(value, classes="metadata-value", markup=False))
        return Grid(*children, classes="metadata-grid")

    def _replace(self, *children: Widget) -> None:
        self.remove_children()
        self.mount(*children)
