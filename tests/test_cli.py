from __future__ import annotations

import json
from datetime import UTC, datetime

from typer.testing import CliRunner

from mpk.cli import app
from mpk.config import Config, DefaultFiltersConfig, DefaultsConfig
from mpk.models import FilterOption, FilterVocab
from mpk.search import SearchResult
from mpk.vocab import SCHEMA_VERSION, VocabCache

runner = CliRunner()


def _vocab() -> FilterVocab:
    return FilterVocab(lang="fi", cities=[FilterOption("Helsinki", "Helsinki")])


def _cache(vocab: FilterVocab) -> VocabCache:
    return VocabCache(
        schema=SCHEMA_VERSION,
        fetched_at=datetime.now(UTC),
        source_hash="test",
        languages={"fi": vocab},
    )


def test_plain_classic_search_uses_config_without_vocab(monkeypatch) -> None:
    captured = []
    config = Config(defaults=DefaultsConfig(lang="en", include_ongoing=False, limit=12))
    monkeypatch.setattr("mpk.cli.load_config", lambda: config)
    monkeypatch.setattr("mpk.cli._tui_available", lambda: False)
    monkeypatch.setattr(
        "mpk.cli.get_vocab", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError())
    )

    def fake_search(query, **kwargs):
        captured.append((query, kwargs))
        return SearchResult(total=0, events=[], fetched=0)

    monkeypatch.setattr("mpk.cli.run_search", fake_search)
    result = runner.invoke(app, ["search", "example", "--classic", "--json"])

    assert result.exit_code == 0
    query, kwargs = captured[0]
    assert query.lang == "en"
    assert query.include_ongoing is False
    assert kwargs["limit"] == 12


def test_search_rejects_reversed_dates_before_network(monkeypatch) -> None:
    monkeypatch.setattr("mpk.cli._tui_available", lambda: False)
    monkeypatch.setattr(
        "mpk.cli.run_search", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError())
    )
    result = runner.invoke(
        app,
        ["search", "--classic", "--from", "2027-02-02", "--to", "2027-02-01"],
    )
    assert result.exit_code == 2
    assert "--to must be on or after --from" in result.output


def test_classic_search_applies_saved_default_filters(monkeypatch) -> None:
    captured = []
    config = Config(
        defaults=DefaultsConfig(
            filters=DefaultFiltersConfig(cities=["Helsinki"], specializations=["1002"])
        )
    )
    monkeypatch.setattr("mpk.cli.load_config", lambda: config)
    monkeypatch.setattr("mpk.cli._tui_available", lambda: False)

    def fake_search(query, **kwargs):
        captured.append(query)
        return SearchResult(total=0, events=[], fetched=0)

    monkeypatch.setattr("mpk.cli.run_search", fake_search)
    result = runner.invoke(app, ["search", "--classic", "--json"])

    assert result.exit_code == 0
    assert captured[0].cities == ["Helsinki"]
    assert captured[0].specializations == ["1002"]


def test_filter_auto_refresh_failure_is_exit_3_without_traceback(monkeypatch) -> None:
    vocab = _vocab()
    monkeypatch.setattr("mpk.cli._tui_available", lambda: False)
    monkeypatch.setattr("mpk.cli.get_vocab", lambda *args, **kwargs: (vocab, _cache(vocab)))
    monkeypatch.setattr(
        "mpk.vocab.refresh_cache",
        lambda **kwargs: (_ for _ in ()).throw(OSError("offline")),
    )

    result = runner.invoke(app, ["search", "--classic", "--city", "missing"])

    assert result.exit_code == 3
    assert "error: failed to refresh filter vocabulary: offline" in result.stderr
    assert "Traceback" not in result.output


def test_filters_refresh_json_has_only_json_on_stdout(monkeypatch) -> None:
    vocab = _vocab()
    before = _cache(FilterVocab(lang="fi"))
    after = _cache(vocab)
    monkeypatch.setattr("mpk.cli.load_cache", lambda: before)
    monkeypatch.setattr("mpk.cli.refresh_cache", lambda **kwargs: after)
    monkeypatch.setattr("mpk.cli.save_cache", lambda cache: None)

    result = runner.invoke(app, ["filters", "--refresh", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["lang"] == "fi"
    assert "added" not in result.stdout


def test_launch_tui_preserves_none_initial_filters(monkeypatch) -> None:
    captured = {}

    def fake_launch(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("mpk.tui.launch", fake_launch)

    from mpk.cli import _launch_tui

    _launch_tui(initial_filters=None)

    assert captured["initial_filters"] is None


def test_bare_mpk_tui_startup_failure_is_exit_3(monkeypatch) -> None:
    monkeypatch.setattr("mpk.cli._tui_available", lambda: True)
    monkeypatch.setattr(
        "mpk.cli._launch_tui", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("broken"))
    )

    result = runner.invoke(app, [])

    assert result.exit_code == 3
    assert "error: TUI failed to start: broken" in result.stderr
    assert "Traceback" not in result.output


def test_explicit_tui_startup_failure_is_exit_3(monkeypatch) -> None:
    monkeypatch.setattr("mpk.cli._tui_available", lambda: True)
    monkeypatch.setattr(
        "mpk.cli._launch_tui", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("broken"))
    )

    result = runner.invoke(app, ["tui"])

    assert result.exit_code == 3
    assert "error: TUI failed to start: broken" in result.stderr
    assert "Traceback" not in result.output


def test_show_malformed_url_is_exit_2(monkeypatch) -> None:
    result = runner.invoke(
        app,
        ["show", "https://koulutuskalenteri.mpk.fi/Calendar/Event"],
    )

    assert result.exit_code == 2
    assert "error: Could not extract event id" in result.stderr
    assert "Traceback" not in result.output


def test_show_network_failure_is_exit_3(monkeypatch) -> None:
    monkeypatch.setattr(
        "mpk.cli.fetch_event_detail",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")),
    )

    result = runner.invoke(app, ["show", "event-token"])

    assert result.exit_code == 3
    assert "error: failed to fetch event: offline" in result.stderr
    assert "Traceback" not in result.output
