from __future__ import annotations

import pytest
from conftest import read
from selectolax.parser import HTMLParser

from mpk.parse import (
    _parse_period,
    parse_event_detail,
    parse_filter_vocab,
    parse_next_event_fragment,
    parse_search_results,
    parse_total_count,
)


def test_parse_filter_vocab_from_home() -> None:
    html = read("home.html")
    v = parse_filter_vocab(html, "fi")

    assert v.lang == "fi"
    assert len(v.cities) > 30
    # Districts have known IDs 1000..1009 minus 1008
    district_values = {o.value for o in v.districts}
    assert {
        "1000",
        "1001",
        "1002",
        "1003",
        "1004",
        "1005",
        "1006",
        "1007",
        "1009",
    } <= district_values

    spec_labels = {o.label for o in v.specializations}
    assert "Ensiapu ja kenttälääkintä" in spec_labels
    assert "Kyberpuolustus" in spec_labels

    types = {(o.value, o.label) for o in v.types}
    assert ("12", "Koulutus") in types
    assert ("1011", "Tukeminen") in types

    modes = {(o.value, o.label) for o in v.implementation_modes}
    assert ("1", "Verkkokoulutus") in modes
    assert ("1002", "Lähikoulutus") in modes
    assert ("1003", "Monimuotokoulutus") in modes

    target_labels = {o.label for o in v.target_groups}
    assert "Naiset" in target_labels
    assert "Reserviläiset" in target_labels


def test_parse_total_count() -> None:
    assert parse_total_count(read("default.html")) == 701
    assert parse_total_count(read("search.html")) == 4
    assert parse_total_count("<div>no count here</div>") is None
    assert parse_total_count("<h2>Events (42)</h2>") == 42
    assert parse_total_count("<h2>Utbildningar (7)</h2>") == 7


def test_empty_search_requires_recognizable_count_marker() -> None:
    assert parse_search_results("<h2>Events (0)</h2>") == []
    assert parse_search_results("<h2>Utbildningar (0)</h2>") == []

    with pytest.raises(ValueError, match="result-count marker"):
        parse_search_results("<html><h1>Maintenance in progress</h1></html>")


def test_pagination_fragment_rejects_error_page() -> None:
    with pytest.raises(ValueError, match="neither event cards nor an empty marker"):
        parse_next_event_fragment("<html><h1>Service unavailable</h1></html>")


def test_filter_vocab_rejects_missing_or_empty_selects() -> None:
    with pytest.raises(ValueError, match="missing selects"):
        parse_filter_vocab("<html><h1>Maintenance in progress</h1></html>", "en")

    empty_selects = "".join(
        f'<select name="{name}"><option value="">Choose</option></select>'
        for name in (
            "City",
            "LocationDistricts",
            "SpecializationId",
            "NetworkTargetGroups",
            "TypeId",
            "ImplementationMethodId",
        )
    )
    with pytest.raises(ValueError, match="contains no options"):
        parse_filter_vocab(empty_selects, "en")


def test_parse_period_does_not_invent_midnight_end() -> None:
    tree = HTMLParser(
        '<div class="period"><span class="period-date">12.08.2026</span>'
        '<span class="period-time">17.00</span></div>'
    )
    start, end = _parse_period(tree.css_first(".period"))
    assert start is not None and start.hour == 17
    assert end is None


def test_parse_search_results_default_page() -> None:
    events = parse_search_results(read("default.html"))
    assert len(events) >= 1

    first = events[0]
    assert first.title
    assert first.url.startswith("https://koulutuskalenteri.mpk.fi/Calendar/Event?d=")
    assert first.id  # non-empty token
    assert first.start is not None


def test_parse_search_results_search_page() -> None:
    events = parse_search_results(read("search.html"))
    titles = [e.title for e in events]
    # The fixture searched for 'ensiapu' and returned 4 hits.
    assert any("ensiapu" in t.lower() or "taisteluensiapu" in t.lower() for t in titles)
    assert len(events) >= 3


def test_parse_multilingual_search_fixtures() -> None:
    english = parse_search_results(read("search_en.html"))
    swedish = parse_search_results(read("search_sv.html"))

    assert english[0].title == "First aid basics"
    assert swedish[0].title == "Grundkurs i första hjälpen"


@pytest.mark.parametrize(
    ("aria", "expected"),
    [
        ("Open event First aid basics", "First aid basics"),
        ("Öppna evenemang Grundkurs i första hjälpen", "Grundkurs i första hjälpen"),
    ],
)
def test_parse_search_result_strips_localized_aria_prefix(aria: str, expected: str) -> None:
    html = f"""
    <h2>Events (1)</h2>
    <div class="koulutus_lista">
      <a id="eventBlock" class="boxlink"
         href="/Calendar/Event?d=token" aria-label="{aria}"></a>
    </div>
    """
    assert parse_search_results(html)[0].title == expected


@pytest.mark.parametrize(
    "href",
    [
        "http://koulutuskalenteri.mpk.fi/Calendar/Event?d=token",
        "https://evil.example/Calendar/Event?d=token",
        "https://koulutuskalenteri.mpk.fi.evil.example/Calendar/Event?d=token",
        "https://koulutuskalenteri.mpk.fi/Other?d=token",
    ],
)
def test_parse_search_result_rejects_unapproved_event_url(href: str) -> None:
    html = f"""
    <h2>Events (1)</h2>
    <div class="koulutus_lista">
      <a id="eventBlock" class="boxlink" href="{href}" aria-label="Open event Test"></a>
    </div>
    """
    with pytest.raises(ValueError, match="unapproved URL"):
        parse_search_results(html)


def test_parse_event_detail_handles_non_standard_br_tags() -> None:
    """The MPK site emits <br \\> (backslash) — must still be recognised."""
    html = """
    <html><body>
        <label class="calendar_label_bold">Kohderyhmä:</label>
        <label class="calendar_label_info">Reserviläiset</label>
        <label class="calendar_label_info">Reserviläisille<br \\><br \\>Esitiedot:<br \\>Kurssilla tutustutaan.</label>
    </body></html>
    """
    d = parse_event_detail(html)
    assert d.target_group_note is not None
    assert "Reserviläisille" in d.target_group_note
    assert "Esitiedot:" in d.target_group_note
    # Line breaks preserved between the fragments.
    assert "\n" in d.target_group_note
    # And they aren't glued together.
    assert "ReserviläisilleEsitiedot" not in d.target_group_note


def test_target_group_header_accepts_only_predefined_values() -> None:
    html = """
    <html><body>
        <select name="NetworkTargetGroups">
            <option value="">Valitse</option>
            <option value="1001">Reserviläiset</option>
        </select>
        <label class="calendar_label_bold">Kohderyhmä:</label>
        <label class="calendar_label_info">Kurssi soveltuu hyväkuntoisille aikuisille.</label>
    </body></html>
    """
    detail = parse_event_detail(html)
    assert detail.target_groups == []
    assert detail.target_group_note == "Kurssi soveltuu hyväkuntoisille aikuisille."


def test_prose_only_target_group_preserves_paragraph_breaks() -> None:
    html = """
    <html><body>
        <select name="NetworkTargetGroups">
            <option value="1001">Reserviläiset</option>
        </select>
        <label class="calendar_label_bold">Kohderyhmä:</label>
        <label class="calendar_label_info">
            Ensimmäinen kohderyhmäkappale.<br/><br/>
            Toinen pidempi kappale.<br/><br/>
            HUOM! Tärkeä erillinen huomautus.
        </label>
    </body></html>
    """
    detail = parse_event_detail(html)
    assert detail.target_groups == []
    assert detail.target_group_note is not None
    assert "Ensimmäinen kohderyhmäkappale.\n\nToinen pidempi kappale." in detail.target_group_note
    assert "Toinen pidempi kappale.\n\nHUOM!" in detail.target_group_note


def test_target_group_header_keeps_predefined_list_separate_from_prose() -> None:
    html = """
    <html><body>
        <select name="NetworkTargetGroups">
            <option value="1001">Reserviläiset</option>
            <option value="1002">Naiset</option>
        </select>
        <label class="calendar_label_bold">Kohderyhmä:</label>
        <label class="calendar_label_info">Reserviläiset, Naiset</label>
        <label class="calendar_label_info">Kurssi edellyttää aiempaa kokemusta.</label>
    </body></html>
    """
    detail = parse_event_detail(html)
    assert detail.target_groups == ["Reserviläiset", "Naiset"]
    assert detail.target_group_note == "Kurssi edellyttää aiempaa kokemusta."


def test_parse_event_detail_preserves_paragraphs() -> None:
    """Multi-<p> prose fields must keep paragraph breaks in raw_fields."""
    html = """
    <html><body>
        <label class="calendar_label_bold">Keskeinen sisältö:</label>
        <label class="calendar_label_info">
            <p>Ensimmäinen kappale.</p>
            <br/>
            <p>Toinen kappale.</p>
        </label>
        <label class="calendar_label_bold">Tavoitteet:</label>
        <label class="calendar_label_info">
            Rivi yksi.<br/>
            Rivi kaksi.<br/>
            Rivi kolme.
        </label>
    </body></html>
    """
    d = parse_event_detail(html)
    assert d.goals is not None
    assert "Rivi yksi." in d.goals
    assert "Rivi kaksi." in d.goals
    # Line breaks preserved
    assert "\n" in d.goals

    keskeinen = d.raw_fields.get("Keskeinen sisältö", "")
    assert "Ensimmäinen kappale." in keskeinen
    assert "Toinen kappale." in keskeinen
    # Paragraph break between them
    assert "\n\n" in keskeinen or "\n" in keskeinen


def test_parse_event_detail_preserves_contact_line_breaks() -> None:
    html = """
    <html><body>
        <label class="calendar_label_bold">Kurssin johtajan yhteystiedot:</label>
        <label class="calendar_label_info">Matti Meikäläinen<br/>matti@example.test</label>
        <label class="calendar_label_info">040 123 4567</label>
    </body></html>
    """

    detail = parse_event_detail(html)

    assert detail.contact == "Matti Meikäläinen\nmatti@example.test\n\n040 123 4567"


def test_parse_event_detail() -> None:
    d = parse_event_detail(read("event.html"))
    assert "Taisteluensiapu" in d.title
    assert d.mode == "Verkkokoulutus"
    assert d.duration == "16 tuntia"
    assert d.price and "maksuton" in d.price.lower()
    assert d.start is not None
    assert d.end is not None
    assert d.start.year == 2026
    assert d.description and "taisteluensiavun" in d.description.lower()
    assert d.goals
    assert d.contact == "Testihenkilö\ntesti@example.invalid"
    assert "MPK:n sitoutuneet kouluttajat ja toimijat" in d.target_groups
    assert "Reserviläiset" in d.target_groups
    # The extra Kohderyhmä prose block must be captured, not dropped.
    assert d.target_group_note is not None
    assert "reserviläisille" in d.target_group_note.lower()
    # Registration form link and deadline are first-class fields.
    assert d.registration_url is not None
    assert "ilmoittautuminen.mpk.fi" in d.registration_url
    assert d.registration_deadline is not None
    assert "06.12.2026" in d.registration_deadline


def test_parse_multilingual_detail_fixtures() -> None:
    english = parse_event_detail(read("event_en.html"))
    swedish = parse_event_detail(read("event_sv.html"))

    assert english.title == "Synthetic first aid course"
    assert english.mode == "Online training"
    assert english.description == "Synthetic English description."
    assert english.registration_deadline == "06.12.2026 18.00"
    assert swedish.title == "Syntetisk kurs i första hjälpen"
    assert swedish.mode == "Webbutbildning"
    assert swedish.description == "Syntetisk svensk beskrivning."
    assert swedish.registration_deadline == "07.12.2026 19.00"


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Open until 06.12.2026 18.00", "06.12.2026 18.00"),
        ("Öppet till 07.12.2026 19.00", "07.12.2026 19.00"),
    ],
)
def test_parse_localized_registration_deadline(label: str, expected: str) -> None:
    detail = parse_event_detail(f'<div class="label_container"><label>{label}</label></div>')
    assert detail.registration_deadline == expected


@pytest.mark.parametrize(
    "href",
    [
        "http://ilmoittautuminen.mpk.fi/Registration/Login?id=1",
        "https://ilmoittautuminen.mpk.fi.evil.example/Registration/Login?id=1",
        "https://evil.example/?next=ilmoittautuminen.mpk.fi",
    ],
)
def test_parse_event_detail_ignores_unapproved_registration_url(href: str) -> None:
    detail = parse_event_detail(f'<a class="button_green" href="{href}">Registration</a>')
    assert detail.registration_url is None


def test_parse_event_detail_accepts_approved_registration_url() -> None:
    href = "https://ilmoittautuminen.mpk.fi/Registration/Login?id=1&amp;lang=en"
    detail = parse_event_detail(f'<a class="button_green" href="{href}">Registration</a>')
    assert detail.registration_url == href.replace("&amp;", "&")
