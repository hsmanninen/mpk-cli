from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from mpk.config import CacheConfig, Config
from mpk.models import FilterOption, FilterVocab
from mpk.vocab import (
    SCHEMA_VERSION,
    VocabCache,
    VocabError,
    VocabRefreshError,
    get_vocab,
    is_stale,
    load_cache,
    refresh_cache,
    resolve_one,
    resolve_with_auto_refresh,
    save_cache,
)


@pytest.fixture()
def vocab() -> FilterVocab:
    return FilterVocab(
        lang="fi",
        cities=[FilterOption("Helsinki", "Helsinki"), FilterOption("Tampere", "Tampere")],
        districts=[FilterOption("1000", "Etelä-Suomi"), FilterOption("1004", "Lounais-Suomi")],
        specializations=[
            FilterOption("1002", "Ensiapu ja kenttälääkintä"),
            FilterOption("1042", "Kyberpuolustus"),
        ],
        target_groups=[FilterOption("1003", "Naiset"), FilterOption("1001", "Reserviläiset")],
        types=[FilterOption("12", "Koulutus"), FilterOption("1011", "Tukeminen")],
        implementation_modes=[
            FilterOption("1", "Verkkokoulutus"),
            FilterOption("1002", "Lähikoulutus"),
            FilterOption("1003", "Monimuotokoulutus"),
        ],
    )


def test_resolve_exact_label(vocab: FilterVocab) -> None:
    opt = resolve_one(vocab, "cities", "Helsinki")
    assert opt.value == "Helsinki"


def test_resolve_case_insensitive(vocab: FilterVocab) -> None:
    opt = resolve_one(vocab, "cities", "helsinki")
    assert opt.value == "Helsinki"


def test_resolve_exact_value(vocab: FilterVocab) -> None:
    opt = resolve_one(vocab, "specializations", "1042")
    assert opt.label == "Kyberpuolustus"


def test_resolve_fuzzy(vocab: FilterVocab) -> None:
    opt = resolve_one(vocab, "specializations", "Ensiapu")
    assert opt.value == "1002"


def test_resolve_mode_shorthand(vocab: FilterVocab) -> None:
    assert resolve_one(vocab, "implementation_modes", "verkko").value == "1"
    assert resolve_one(vocab, "implementation_modes", "lähi").value == "1002"
    assert resolve_one(vocab, "implementation_modes", "monimuoto").value == "1003"


def test_resolve_unknown_suggests(vocab: FilterVocab) -> None:
    with pytest.raises(VocabError) as excinfo:
        resolve_one(vocab, "cities", "Zzyzx")
    assert excinfo.value.suggestions


def test_auto_refresh_failure_has_specific_error(monkeypatch, vocab: FilterVocab) -> None:
    cache = VocabCache(
        schema=SCHEMA_VERSION,
        fetched_at=datetime.now(UTC),
        source_hash="",
        languages={"fi": vocab},
    )
    monkeypatch.setattr(
        "mpk.vocab.refresh_cache",
        lambda **kwargs: (_ for _ in ()).throw(OSError("offline")),
    )

    with pytest.raises(VocabRefreshError, match=r"failed to refresh.*offline") as excinfo:
        resolve_with_auto_refresh(
            vocab,
            cache,
            "cities",
            ["Zzyzx"],
            lang="fi",
            config=Config(),
        )

    assert isinstance(excinfo.value.__cause__, OSError)


def _cache(vocab: FilterVocab, fetched_at: datetime) -> VocabCache:
    return VocabCache(
        schema=SCHEMA_VERSION,
        fetched_at={vocab.lang: fetched_at},
        source_hash={vocab.lang: f"hash-{vocab.lang}"},
        languages={vocab.lang: vocab},
    )


def test_cache_round_trip_preserves_per_language_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path, vocab: FilterVocab
) -> None:
    path = tmp_path / "filters.json"
    english = FilterVocab(lang="en", cities=[FilterOption("Turku", "Turku")])
    fi_time = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    en_time = datetime(2026, 2, 3, 4, 5, tzinfo=UTC)
    cache = VocabCache(
        schema=SCHEMA_VERSION,
        fetched_at={"fi": fi_time, "en": en_time},
        source_hash={"fi": "fi-hash", "en": "en-hash"},
        languages={"fi": vocab, "en": english},
    )
    monkeypatch.setattr("mpk.vocab._cache_path", lambda: path)

    save_cache(cache)

    assert load_cache() == cache
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == 2


def test_cache_serialization_rejects_invalid_metadata(vocab: FilterVocab) -> None:
    cache = VocabCache(
        schema=SCHEMA_VERSION,
        fetched_at={"fi": datetime(2026, 1, 1)},
        source_hash={"fi": "hash"},
        languages={"fi": vocab},
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        cache.to_json()

    cache.fetched_at = {}
    with pytest.raises(ValueError, match="timestamps must match"):
        cache.to_json()


@pytest.mark.parametrize(
    "data",
    [
        "not json",
        "[]",
        '{"schema": 1, "fetched_at": {}, "source_hash": {}, "languages": {}}',
        '{"schema": 2, "fetched_at": {}, "source_hash": {}}',
        '{"schema": 2, "fetched_at": {}, "source_hash": {}, "languages": {"fi": {}}}',
        (
            '{"schema": 2, "fetched_at": {"fi": "2026-01-01T00:00:00"}, '
            '"source_hash": {}, "languages": {"fi": {"lang": "fi"}}}'
        ),
        (
            '{"schema": 2, "fetched_at": {"fi": "2026-01-01T00:00:00+00:00"}, '
            '"source_hash": {}, "languages": {"fi": {"lang": "en"}}}'
        ),
    ],
)
def test_load_cache_rejects_wrong_schema_and_corrupt_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path, data: str
) -> None:
    path = tmp_path / "filters.json"
    path.write_text(data, encoding="utf-8")
    monkeypatch.setattr("mpk.vocab._cache_path", lambda: path)

    assert load_cache() is None


def test_refresh_merges_languages_without_refreshing_existing_language(
    monkeypatch: pytest.MonkeyPatch, vocab: FilterVocab
) -> None:
    old_time = datetime(2025, 1, 1, tzinfo=UTC)
    existing = _cache(vocab, old_time)
    english = FilterVocab(lang="en", cities=[FilterOption("Turku", "Turku")])
    monkeypatch.setattr(
        "mpk.vocab.fetch_vocab_for_lang", lambda lang, **kwargs: (english, "hash-en")
    )

    merged = refresh_cache(langs=["en"], existing=existing)

    assert merged.languages == {"fi": vocab, "en": english}
    assert merged.fetched_at["fi"] == old_time
    assert merged.fetched_at["en"] > old_time
    assert merged.source_hash == {"fi": "hash-fi", "en": "hash-en"}


def test_staleness_is_per_language_and_ttl_boundary(vocab: FilterVocab) -> None:
    now = datetime(2026, 8, 14, tzinfo=UTC)
    english = FilterVocab(lang="en")
    cache = VocabCache(
        schema=SCHEMA_VERSION,
        fetched_at={"fi": now, "en": now - timedelta(days=30)},
        source_hash={},
        languages={"fi": vocab, "en": english},
    )

    assert not is_stale(cache, "fi", 30, now=now)
    assert not is_stale(cache, "en", 30, now=now)
    assert is_stale(cache, "en", 30, now=now + timedelta(microseconds=1))
    assert is_stale(cache, "sv", 30, now=now)
    assert not is_stale(cache, "en", 0, now=now + timedelta(days=100))


@pytest.mark.parametrize("cached_language", [None, "fi"])
def test_network_disabled_rejects_cache_miss_without_fetching(
    monkeypatch: pytest.MonkeyPatch,
    vocab: FilterVocab,
    cached_language: str | None,
) -> None:
    cache = None if cached_language is None else _cache(vocab, datetime.now(UTC))
    monkeypatch.setattr("mpk.vocab.load_cache", lambda: cache)
    monkeypatch.setattr(
        "mpk.vocab.refresh_cache", lambda **kwargs: (_ for _ in ()).throw(AssertionError())
    )
    config = Config(cache=CacheConfig(allow_network_refresh=False))

    with pytest.raises(VocabRefreshError, match="network refresh is disabled"):
        get_vocab("en", config=config)


def test_force_refresh_overrides_disabled_network_policy(
    monkeypatch: pytest.MonkeyPatch, vocab: FilterVocab
) -> None:
    refreshed = _cache(vocab, datetime.now(UTC))
    calls: list[list[str] | None] = []
    monkeypatch.setattr("mpk.vocab.load_cache", lambda: None)
    monkeypatch.setattr(
        "mpk.vocab.refresh_cache",
        lambda **kwargs: calls.append(kwargs["langs"]) or refreshed,
    )
    monkeypatch.setattr("mpk.vocab.save_cache", lambda cache: None)
    config = Config(cache=CacheConfig(allow_network_refresh=False))

    returned_vocab, returned_cache = get_vocab("fi", config=config, force_refresh=True)

    assert calls == [["fi"]]
    assert returned_vocab is vocab
    assert returned_cache is refreshed


def test_soft_refresh_failure_returns_stale_language(
    monkeypatch: pytest.MonkeyPatch, vocab: FilterVocab
) -> None:
    stale = _cache(vocab, datetime.now(UTC) - timedelta(days=31))
    monkeypatch.setattr("mpk.vocab.load_cache", lambda: stale)
    monkeypatch.setattr(
        "mpk.vocab.refresh_cache", lambda **kwargs: (_ for _ in ()).throw(OSError("offline"))
    )

    returned_vocab, returned_cache = get_vocab("fi", config=Config())

    assert returned_vocab is vocab
    assert returned_cache is stale
