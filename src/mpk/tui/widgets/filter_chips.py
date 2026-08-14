"""Filter chip bar: shows currently-applied filters."""

from __future__ import annotations

from textual.containers import Horizontal
from textual.widgets import Static

from ...models import FilterOption


class FilterChips(Horizontal):
    """Horizontal row of chips representing the active filters."""

    DEFAULT_MESSAGE = "Ei aktiivisia suodattimia · f avaa suodattimet"

    def __init__(self) -> None:
        super().__init__()
        self._empty = Static(self.DEFAULT_MESSAGE)

    def compose(self):
        yield self._empty

    def update_filters(
        self,
        *,
        cities: list[FilterOption],
        districts: list[FilterOption],
        specializations: list[FilterOption],
        target_groups: list[FilterOption],
        modes: list[FilterOption],
        types: list[FilterOption],
    ) -> None:
        # Remove all existing children and re-render.
        for child in list(self.children):
            child.remove()

        chips: list[tuple[str, str]] = []
        for opt in cities:
            chips.append(("Kaupunki", opt.label))
        for opt in districts:
            chips.append(("Piiri", opt.label))
        for opt in specializations:
            chips.append(("Aihe", opt.label))
        for opt in target_groups:
            chips.append(("Kohderyhmä", opt.label))
        for opt in modes:
            chips.append(("Muoto", opt.label))
        for opt in types:
            chips.append(("Tyyppi", opt.label))

        if not chips:
            self.mount(Static(self.DEFAULT_MESSAGE))
            return

        if len(chips) > 3:
            self.mount(Static(f"{len(chips)} aktiivista suodatinta · f muokkaa", classes="active"))
            return

        summary = "   ".join(f"{kind}: {label}" for kind, label in chips)
        self.mount(Static(summary, classes="active", markup=False))
