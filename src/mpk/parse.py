"""HTML parsers for search results, event details, and filter vocabulary."""

from __future__ import annotations

import html as html_module
import re
from datetime import datetime, time
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser, Node

from .client import BASE_URL
from .models import Event, EventDetail, FilterOption, FilterVocab

# ---- helpers ----------------------------------------------------------------


def _text(node: Node | None) -> str:
    if node is None:
        return ""
    return node.text(separator=" ", strip=True)


def _clean_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _node_text_with_breaks(node: Node | None) -> str:
    """Extract text content preserving paragraph and line breaks.

    Converts <p>, <br>, <li>, <ul>, <ol>, <div>, <h*> into newlines so the
    output roughly mirrors how the source page renders. Horizontal whitespace
    within a line is collapsed; runs of blank lines are squashed to one.
    """
    if node is None:
        return ""
    raw = node.html or ""
    # Drop the outermost wrapping <label ...> ... </label>.
    raw = re.sub(r"^\s*<label[^>]*>", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"</label>\s*$", "", raw, flags=re.IGNORECASE)

    # Structural tags -> newlines.
    # NB: The MPK site emits non-standard <br \> (backslash), so match liberally.
    raw = re.sub(r"<br\b[^>]*>", "\n", raw, flags=re.IGNORECASE)
    raw = re.sub(r"</p\s*>", "\n\n", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<p[^>]*>", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<li[^>]*>", "\n• ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"</li\s*>", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"</?(ul|ol|div|h[1-6])[^>]*>", "\n", raw, flags=re.IGNORECASE)

    # Strip all remaining tags.
    raw = re.sub(r"<[^>]+>", "", raw)

    # Decode entities and normalise non-breaking spaces.
    text = html_module.unescape(raw).replace("\xa0", " ")

    # Collapse horizontal whitespace within each line, keep vertical structure.
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]

    # Collapse runs of blank lines to a single blank; trim leading blanks.
    result: list[str] = []
    just_blanked = True
    for line in lines:
        if line:
            result.append(line)
            just_blanked = False
        elif not just_blanked:
            result.append("")
            just_blanked = True
    return "\n".join(result).strip()


_FI_MONTHS = {
    # ordinal.month.year -> handled explicitly
}


def _parse_date(s: str) -> datetime | None:
    """Parse dd.mm.yyyy into a naive datetime at 00:00."""
    s = s.strip()
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", s)
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    try:
        return datetime(y, mo, d)
    except ValueError:
        return None


def _parse_time(s: str) -> time | None:
    """Parse HH.MM or HH:MM into a time, ignoring extras."""
    s = s.strip()
    m = re.match(r"^(\d{1,2})[.:](\d{2})", s)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if 0 <= hh < 24 and 0 <= mm < 60:
        return time(hh, mm)
    return None


def _combine(d: datetime | None, t: time | None) -> datetime | None:
    if d is None:
        return None
    if t is None:
        return d
    return d.replace(hour=t.hour, minute=t.minute)


def _parse_period(period_node: Node) -> tuple[datetime | None, datetime | None]:
    """Parse a training_period / calendar_info_period span structure into (start, end)."""
    date_nodes = period_node.css(".period-date")
    time_nodes = period_node.css(".period-time")

    dates = [_parse_date(_text(n)) for n in date_nodes]
    # A period-time may contain a range like "17.00–20.00"
    raw_times: list[str] = [_text(n) for n in time_nodes]

    times: list[time | None] = []
    for raw in raw_times:
        # split "17.00–20.00" or "17.00-20.00" into two
        parts = re.split(r"[–\-]", raw)
        for p in parts:
            t = _parse_time(p)
            if t is not None:
                times.append(t)

    # Fill combinations
    start_date = dates[0] if len(dates) >= 1 else None
    end_date = dates[1] if len(dates) >= 2 else start_date

    start_time = times[0] if len(times) >= 1 else None
    end_time = times[1] if len(times) >= 2 else None

    start = _combine(start_date, start_time)
    if end_time is None and start_time is not None:
        return start, None
    return start, _combine(end_date, end_time)


def _extract_event_id(href: str) -> str:
    """Extract the ?d=... token from a /Calendar/Event URL."""
    m = re.search(r"[?&]d=([^&]+)", href)
    return m.group(1) if m else href


def _validated_https_url(raw: str, *, host: str, path: str | None = None) -> str | None:
    """Return an approved absolute HTTPS URL, or None for an unsafe URL."""
    try:
        url = urljoin(BASE_URL, raw)
        parsed = urlparse(url)
        parsed_host = parsed.hostname
        parsed_port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed_host is None
        or parsed_host.casefold() != host
        or parsed.username is not None
        or parsed.password is not None
        or parsed_port is not None
        or (path is not None and parsed.path != path)
    ):
        return None
    return url


# ---- search results ---------------------------------------------------------


TOTAL_COUNT_RE = re.compile(r"(?:Koulutuksia|Events|Utbildningar)\s*\((\d+)\)", re.IGNORECASE)


def parse_total_count(html: str) -> int | None:
    m = TOTAL_COUNT_RE.search(html)
    return int(m.group(1)) if m else None


def parse_search_results(html: str) -> list[Event]:
    """Parse all event cards from a full search-results HTML page."""
    total = parse_total_count(html)
    if total is None:
        raise ValueError("Search response is missing the result-count marker")
    tree = HTMLParser(html)
    events = [_parse_event_card(node) for node in tree.css(".koulutus_lista")]
    if total == 0 and events:
        raise ValueError("Search response reports zero results but contains event cards")
    if total > 0 and not events:
        raise ValueError("Search response reports results but contains no event cards")
    return events


def parse_next_event_fragment(html: str) -> list[Event]:
    """Parse events from a /Calendar/LoadNextEvent HTML fragment."""
    tree = HTMLParser(html)
    # Fragment may include one or multiple .koulutus_lista blocks, or be inside
    # a wrapping .col-xs-12. Accept both.
    cards = tree.css(".koulutus_lista")
    if not cards:
        raise ValueError("Pagination response contains neither event cards nor an empty marker")
    return [_parse_event_card(node) for node in cards]


def _parse_event_card(node: Node) -> Event:
    link = node.css_first("a.boxlink, a#eventBlock")
    if link is None:
        raise ValueError("Event card is missing its event link")
    href = link.attributes.get("href", "") or ""
    if not href:
        raise ValueError("Event card has an empty event link")
    url = _validated_https_url(
        href,
        host="koulutuskalenteri.mpk.fi",
        path="/Calendar/Event",
    )
    if url is None:
        raise ValueError(f"Event card has an unapproved URL: {href!r}")
    event_id = _extract_event_id(href)
    if not event_id or event_id == href:
        raise ValueError("Event card URL is missing the event id")

    aria = link.attributes.get("aria-label", "") or ""
    title = re.sub(
        r"^(?:Avaa\s+tapahtuma|Open\s+event|Öppna\s+(?:evenemang(?:et)?|händelse))\s+",
        "",
        aria,
        flags=re.IGNORECASE,
    ).strip()
    if not title:
        # fallback to the visible title span
        title_node = node.css_first(".tapahtumalinkki_calendar")
        title = _clean_ws(_text(title_node))
    if not title:
        raise ValueError("Event card is missing its title")

    # Registration status
    status_node = node.css_first(".registration_status")
    status = _clean_ws(_text(status_node)).lstrip("-").strip() or None

    # City
    city_node = node.css_first(".training_city")
    city = _clean_ws(_text(city_node)) or None

    # Period
    start = end = None
    period_node = node.css_first(".training_period")
    if period_node is not None:
        start, end = _parse_period(period_node)

    return Event(
        id=event_id,
        url=url,
        title=title,
        start=start,
        end=end,
        city=city,
        registration_status=status,
    )


# ---- event detail -----------------------------------------------------------


def parse_event_detail(html: str) -> EventDetail:
    tree = HTMLParser(html)

    # The h1.calendar_title node holds the site name ("Koulutuskalenteri").
    # The real event title lives in og:title / <title>, and repeats in an
    # unstyled h2 inside .content-70-tapahtumavalinta.
    title = ""
    og = tree.css_first('meta[property="og:title"]')
    if og is not None:
        title = _clean_ws(og.attributes.get("content", "") or "")
    if not title:
        title_tag = tree.css_first("title")
        raw = _clean_ws(_text(title_tag))
        title = re.sub(r"\s*-\s*Koulutuskalenteri\s*$", "", raw)
    if not title:
        h2 = tree.css_first(".content-70-tapahtumavalinta h2")
        title = _clean_ws(_text(h2))

    # Fields are label.calendar_label_bold followed by one or more
    # sibling label.calendar_label_info elements.
    fields, field_lists = _extract_label_field_pairs(tree)

    # Period lives inside #calendar_info_period
    start = end = None
    period_container = tree.css_first("#calendar_info_period")
    if period_container is not None:
        start, end = _parse_period(period_container)

    # Location
    training_place = _text(tree.css_first(".cal_training_place")) or None
    cal_location = _text(tree.css_first(".cal_location")) or None
    cal_city = _clean_ws(_text(tree.css_first(".cal_city"))) or None
    location = " / ".join(x for x in (training_place, cal_location) if x) or None

    mode = fields.get("Koulutusmuoto") or fields.get("Training form") or fields.get("Kursform")
    duration = fields.get("Kesto") or fields.get("Duration") or fields.get("Längd")
    price = fields.get("Hinta") or fields.get("Price") or fields.get("Pris")

    def _multiline(*candidates: str) -> str | None:
        """Return the multi-line (break-preserving) value for the first hit."""
        for key in candidates:
            frags = field_lists.get(key)
            if frags:
                joined = "\n\n".join(f for f in frags if f.strip()).strip()
                if joined:
                    return joined
        return None

    organizer = _multiline("Järjestäjä", "Organizer", "Arrangör")
    contact = _multiline(
        "Kurssin johtajan yhteystiedot",
        "Course leader contact information",
        "Kursledarens kontaktuppgifter",
    )
    description = _multiline("Tapahtuman kuvaus", "Event description", "Beskrivning av evenemanget")
    goals = _multiline("Tavoitteet", "Goals", "Mål")

    target_field_key: str | None = None
    for candidate in ("Kohderyhmä", "Target group", "Målgrupp"):
        if candidate in field_lists:
            target_field_key = candidate
            break
    target_groups: list[str] = []
    target_group_note: str | None = None
    if target_field_key:
        parts = field_lists[target_field_key]
        # Only exact options from MPK's predefined target-group select belong
        # in the structured header. Event authors may put arbitrary prose in
        # the first Kohderyhmä block, so its position alone is not sufficient.
        predefined_groups = {
            _clean_ws(_text(option)).casefold(): _clean_ws(_text(option))
            for option in tree.css('select[name="NetworkTargetGroups"] option')
            if (option.attributes.get("value", "") or "") not in {"", "-"}
        }
        note_parts: list[str] = []
        if parts:
            first_flat = _clean_ws(parts[0])
            candidates = [item.strip() for item in re.split(r"[,;]", first_flat) if item.strip()]
            predefined = [predefined_groups.get(candidate.casefold()) for candidate in candidates]
            if candidates and all(label is not None for label in predefined):
                target_groups = [label for label in predefined if label is not None]
            else:
                # Keep the original structural newlines from <br>/<p>. Flattening
                # this block would destroy paragraph boundaries in prose-only
                # Kohderyhmä sections.
                note_parts.append(parts[0])
        note_parts.extend(part for part in parts[1:] if part.strip())
        note = "\n\n".join(note_parts).strip()
        target_group_note = note or None

    # Prefer multi-line raw_fields so the renderer's "spill" of unknown fields
    # (e.g. "Keskeinen sisältö") preserves paragraph structure.
    raw_fields_multiline: dict[str, str] = {}
    for key, frags in field_lists.items():
        joined = "\n\n".join(f for f in frags if f.strip()).strip()
        raw_fields_multiline[key] = joined if joined else fields.get(key, "")

    # Registration form link — the "Ilmoittautumislomake" / "Registration form" /
    # "Anmälningsblankett" anchor that opens the external ilmoittautuminen.mpk.fi
    # site. Present on most events with an open registration window.
    registration_url: str | None = None
    for anchor in tree.css("a.button_green"):
        href = anchor.attributes.get("href") or ""
        approved = _validated_https_url(href, host="ilmoittautuminen.mpk.fi")
        if approved is not None:
            registration_url = approved
            break

    # "Avoinna … saakka" freshness marker sits inside the same label_container
    # as the registration anchor. It's optional and can appear in any of the
    # three site languages.
    registration_deadline: str | None = None
    for lc in tree.css(".label_container"):
        text = _clean_ws(_text(lc))
        m = re.search(
            r"(?:Avoinna\s+(.+?\S)\s+saakka|Open\s+until\s+(.+?\S)|Öppet\s+till\s+(.+?\S))$",
            text,
            flags=re.IGNORECASE,
        )
        if m:
            registration_deadline = next(group for group in m.groups() if group is not None).strip()
            break

    # id from the current form/hidden field or, failing that, empty
    ev_id = ""
    hidden = tree.css_first('input[name="EventId"]')
    if hidden is not None:
        ev_id = hidden.attributes.get("value", "") or ""

    return EventDetail(
        id=ev_id,
        url="",  # caller fills in
        title=title,
        start=start,
        end=end,
        city=cal_city or None,
        location=location,
        mode=mode,
        topics=[],
        target_groups=target_groups,
        registration_status=None,
        description=description,
        goals=goals,
        duration=duration,
        price=price,
        organizer=organizer,
        contact=contact,
        target_group_note=target_group_note,
        registration_url=registration_url,
        registration_deadline=registration_deadline,
        raw_fields=raw_fields_multiline,
    )


def parse_event_detail_page(html: str) -> EventDetail:
    """Parse a fetched detail page after checking stable page invariants."""
    tree = HTMLParser(html)
    has_title = tree.css_first('meta[property="og:title"], title') is not None
    has_detail_content = (
        tree.css_first(
            '#calendar_info_period, input[name="EventId"], label.calendar_label_bold, '
            ".content-70-tapahtumavalinta"
        )
        is not None
    )
    if not has_title or not has_detail_content:
        raise ValueError("Event detail response does not look like a calendar event page")
    detail = parse_event_detail(html)
    if not detail.title:
        raise ValueError("Event detail response is missing the event title")
    return detail


def _extract_label_field_pairs(
    tree: HTMLParser,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Collect every 'calendar_label_bold' -> 'calendar_label_info' pair.

    Returns two aligned mappings:
      * flat: bold key -> single-line concatenated info text (for structured
        fields like Koulutusmuoto, Kesto, Hinta).
      * lists: bold key -> ordered list of individual info fragments with
        their internal line breaks preserved (for prose fields like
        Tavoitteet, Keskeinen sisältö, and the Kohderyhmä note).

    We walk every <label> in document order to associate each bold label with
    the info nodes that follow before the next bold label. (selectolax's grouped
    selectors are NOT document-ordered.)
    """
    flat: dict[str, str] = {}
    lists: dict[str, list[str]] = {}
    current_key: str | None = None
    current_multiline: list[str] = []
    current_flat: list[str] = []

    def _flush() -> None:
        nonlocal current_key, current_multiline, current_flat
        if current_key is not None:
            cleaned_flat = [v for v in (_clean_ws(v) for v in current_flat) if v]
            flat[current_key] = _clean_ws(" ".join(cleaned_flat))
            cleaned_ml = [v for v in current_multiline if v.strip()]
            lists[current_key] = cleaned_ml

    for node in tree.css("label"):
        classes = node.attributes.get("class", "") or ""
        if "calendar_label_bold" in classes:
            _flush()
            current_key = _clean_ws(_text(node)).rstrip(":")
            current_multiline = []
            current_flat = []
        elif "calendar_label_info" in classes:
            if current_key is None:
                continue
            current_multiline.append(_node_text_with_breaks(node))
            current_flat.append(_text(node))

    _flush()
    return flat, lists


# ---- filter vocabulary ------------------------------------------------------


_SELECT_TO_FIELD = {
    "City": "cities",
    "LocationDistricts": "districts",
    "SpecializationId": "specializations",
    "NetworkTargetGroups": "target_groups",
    "TypeId": "types",
    "ImplementationMethodId": "implementation_modes",
}


def parse_filter_vocab(html: str, lang: str) -> FilterVocab:
    tree = HTMLParser(html)
    vocab = FilterVocab(lang=lang)
    found: set[str] = set()

    for select in tree.css("select"):
        name = select.attributes.get("name")
        if name not in _SELECT_TO_FIELD:
            continue
        found.add(name)
        field = _SELECT_TO_FIELD[name]
        options: list[FilterOption] = []
        for opt in select.css("option"):
            value = opt.attributes.get("value", "") or ""
            label = _clean_ws(_text(opt))
            if value == "" or value == "-":
                continue
            options.append(FilterOption(value=value, label=label))
        if not options:
            raise ValueError(f"Filter vocabulary select {name!r} contains no options")
        setattr(vocab, field, options)

    missing = _SELECT_TO_FIELD.keys() - found
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"Filter vocabulary response is missing selects: {names}")

    return vocab
