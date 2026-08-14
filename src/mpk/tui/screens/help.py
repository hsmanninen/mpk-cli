"""Context-aware keyboard reference."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Static


class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape,question_mark,?,q,f1", "dismiss", "Sulje")]

    def __init__(self, *, context: str = "browse") -> None:
        super().__init__()
        self._help_context = context

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-body"):
            yield Static("NÄPPÄIMET", classes="eyebrow", markup=False)
            yield Static(self._text(), markup=False)
        yield Footer()

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 90 or event.size.height < 26, "compact")

    def _text(self) -> str:
        if self._help_context == "filters":
            return (
                "Suodattimet\n\n"
                "Nuoli ylös/alas   liiku kategoriassa tai vaihtoehdoissa\n"
                "Enter / oikea     avaa kategorian vaihtoehdot\n"
                "Vasen             palaa kategorioihin\n"
                "/                 hae nykyisen kategorian vaihtoehdoista\n"
                "Tab               seuraava alue\n"
                "Enter haussa      siirry vaihtoehtoihin\n"
                "Space             vaihda valinta\n"
                "Ctrl+X            tyhjennä kaikki suodattimet\n"
                "Ctrl+S            tallenna valinnat käynnistysoletukseksi\n"
                "Ctrl+R            poista tallennettu oletussuodatin\n"
                "Ctrl+Enter        käytä muutokset\n"
                "Esc               peruuta"
            )
        if self._help_context == "detail":
            return (
                "Tapahtuman tiedot\n\n"
                "Nuoli ylös/alas   vieritä tietoja\n"
                "o                 avaa tapahtumasivu\n"
                "i                 avaa ilmoittautuminen\n"
                "y                 kopioi URL\n"
                "Enter             yritä latausta uudelleen\n"
                "Esc               takaisin tuloksiin\n"
                "? tai F1          tämä ohje"
            )
        return (
            "Tulokset\n\n"
            "/                 siirry hakuun\n"
            "Enter haussa      suorita haku\n"
            "Nuoli ylös/alas   valitse tapahtuma\n"
            "Enter tuloksissa  lataa tarkat tiedot\n"
            "f                 avaa suodattimet\n"
            "x                 tyhjennä kaikki suodattimet\n"
            "r                 päivitä haku\n"
            "l                 vaihda sisältökieltä\n\n"
            "Tapahtuma\n\n"
            "o                 avaa tapahtumasivu\n"
            "i                 avaa ilmoittautuminen\n"
            "y                 kopioi URL\n"
            "Esc               poistu hausta / takaisin\n"
            "q tai Ctrl+Q      lopeta\n"
            "? tai F1          tämä ohje"
        )
