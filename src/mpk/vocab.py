"""Filter vocabulary: fetch, cache, refresh, fuzzy-resolve."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

from .client import MpkClient
from .config import Config, load_config
from .models import FilterOption, FilterVocab, lang_id
from .parse import parse_filter_vocab
from .paths import filters_cache_file

SCHEMA_VERSION = 2


class VocabError(Exception):
    """Raised when a filter name cannot be resolved."""

    def __init__(self, message: str, suggestions: list[str] | None = None) -> None:
        super().__init__(message)
        self.suggestions = suggestions or []


class VocabRefreshError(Exception):
    """Raised when an automatic vocabulary refresh fails."""


# ---- cache file layout ------------------------------------------------------


@dataclass
class VocabCache:
    schema: int
    fetched_at: dict[str, datetime]
    source_hash: dict[str, str]
    languages: dict[str, FilterVocab]

    def __post_init__(self) -> None:
        # Keep direct construction concise for callers creating a single-language
        # cache while normalizing the in-memory representation to per-language data.
        if isinstance(self.fetched_at, datetime):
            self.fetched_at = {lang: self.fetched_at for lang in self.languages}
        if isinstance(self.source_hash, str):
            self.source_hash = {lang: self.source_hash for lang in self.languages}

    def to_json(self) -> dict[str, Any]:
        if self.schema != SCHEMA_VERSION:
            raise ValueError(f"unsupported cache schema {self.schema}")
        if set(self.fetched_at) != set(self.languages):
            raise ValueError("cache timestamps must match cached languages")
        if not set(self.source_hash) <= set(self.languages):
            raise ValueError("cache source hashes must refer to cached languages")
        if any(
            not isinstance(value, datetime) or value.tzinfo is None
            for value in self.fetched_at.values()
        ):
            raise ValueError("cache timestamps must be timezone-aware datetimes")
        if any(vocab.lang != lang for lang, vocab in self.languages.items()):
            raise ValueError("cached vocabulary language does not match its key")
        if not all(isinstance(value, str) for value in self.source_hash.values()):
            raise ValueError("cache source hashes must be strings")
        return {
            "schema": self.schema,
            "fetched_at": {lang: value.isoformat() for lang, value in self.fetched_at.items()},
            "source_hash": self.source_hash,
            "languages": {k: v.to_dict() for k, v in self.languages.items()},
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> VocabCache:
        if not isinstance(data, dict):
            raise TypeError("cache must be a JSON object")
        schema = data["schema"]
        fetched_raw = data["fetched_at"]
        hashes_raw = data["source_hash"]
        langs_raw = data["languages"]
        if isinstance(schema, bool) or not isinstance(schema, int):
            raise TypeError("cache schema must be an integer")
        if schema != SCHEMA_VERSION:
            raise ValueError(f"unsupported cache schema {schema}")
        if not all(isinstance(value, dict) for value in (fetched_raw, hashes_raw, langs_raw)):
            raise TypeError("cache language data must be JSON objects")

        languages: dict[str, FilterVocab] = {}
        for k, v in langs_raw.items():
            if not isinstance(k, str) or not isinstance(v, dict):
                raise TypeError("invalid cached vocabulary")
            languages[k] = FilterVocab.from_dict(v)
            if languages[k].lang != k:
                raise ValueError("cached vocabulary language does not match its key")

        if set(fetched_raw) != set(languages):
            raise ValueError("cache timestamps must match cached languages")
        fetched_at: dict[str, datetime] = {}
        for lang, value in fetched_raw.items():
            if not isinstance(value, str):
                raise TypeError("cache timestamp must be a string")
            fetched = datetime.fromisoformat(value)
            if fetched.tzinfo is None:
                raise ValueError("cache timestamp must include a timezone")
            fetched_at[lang] = fetched

        if not set(hashes_raw) <= set(languages) or not all(
            isinstance(lang, str) and isinstance(value, str) for lang, value in hashes_raw.items()
        ):
            raise ValueError("invalid cache source hashes")

        return cls(
            schema=schema,
            fetched_at=fetched_at,
            source_hash=dict(hashes_raw),
            languages=languages,
        )


def _cache_path() -> Path:
    return filters_cache_file()


def load_cache() -> VocabCache | None:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return None
    try:
        cache = VocabCache.from_json(data)
    except (KeyError, TypeError, ValueError):
        return None
    return cache


def save_cache(cache: VocabCache) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # atomic write: tmp file next to target, fsync, rename.
    fd, tmp = tempfile.mkstemp(prefix=".filters.", suffix=".json.tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache.to_json(), f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# ---- staleness --------------------------------------------------------------


def is_stale(
    cache: VocabCache | None,
    lang: str,
    ttl_days: int,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether one language's cache entry needs refreshing."""
    if cache is None or lang not in cache.languages or lang not in cache.fetched_at:
        return True
    if ttl_days <= 0:
        return False
    age = (now or datetime.now(UTC)) - cache.fetched_at[lang]
    return age > timedelta(days=ttl_days)


def _hash_html(html: str) -> str:
    return "sha256:" + hashlib.sha256(html.encode("utf-8")).hexdigest()


# ---- fetch ------------------------------------------------------------------


def fetch_vocab_for_lang(lang: str, *, verbose: bool = False) -> tuple[FilterVocab, str]:
    """Fetch and parse the vocab for one language. Returns (vocab, html_hash)."""
    lid = lang_id(lang)
    with MpkClient(lang_id=lid, verbose=verbose) as client:
        # Bootstrap the session in Finnish first, then GET the (possibly translated) home
        # page. Fetching directly with the language cookie means the option
        # labels come back in the requested language.
        client.bootstrap()
        r = client.get("/Calendar/")
        html = r.text
    vocab = parse_filter_vocab(html, lang)
    return vocab, _hash_html(html)


def refresh_cache(
    *,
    langs: list[str] | None = None,
    existing: VocabCache | None = None,
    verbose: bool = False,
) -> VocabCache:
    """Refresh the cache for the given languages (defaults to just 'fi')."""
    langs = langs or ["fi"]

    languages: dict[str, FilterVocab] = dict(existing.languages) if existing else {}
    fetched_at = dict(existing.fetched_at) if existing else {}
    source_hash = dict(existing.source_hash) if existing else {}

    for lang in langs:
        vocab, h = fetch_vocab_for_lang(lang, verbose=verbose)
        languages[lang] = vocab
        fetched_at[lang] = datetime.now(UTC)
        source_hash[lang] = h

    return VocabCache(
        schema=SCHEMA_VERSION,
        fetched_at=fetched_at,
        source_hash=source_hash,
        languages=languages,
    )


# ---- top-level: ensure vocab for a language --------------------------------


def get_vocab(
    lang: str,
    *,
    config: Config | None = None,
    force_refresh: bool = False,
    verbose: bool = False,
) -> tuple[FilterVocab, VocabCache]:
    """Return a FilterVocab for `lang`, honoring TTL + soft refresh policy.

    - If force_refresh: fetch synchronously, regardless of network policy.
    - If cache or language is missing: fetch only when network refresh is allowed.
    - Else if cache older than TTL and network allowed: try a soft inline refresh,
      swallowing failures (stale cache still used on error).
    """
    cfg = config or load_config()
    cache = load_cache()

    if force_refresh:
        try:
            cache = refresh_cache(langs=[lang], existing=cache, verbose=verbose)
        except Exception as e:
            raise VocabRefreshError(f"failed to refresh filter vocabulary: {e}") from e
        save_cache(cache)
        return cache.languages[lang], cache

    if cache is None:
        if not cfg.cache.allow_network_refresh:
            raise VocabRefreshError(
                "filter vocabulary cache is missing and network refresh is disabled"
            )
        try:
            cache = refresh_cache(langs=[lang], verbose=verbose)
        except Exception as e:
            raise VocabRefreshError(f"failed to refresh filter vocabulary: {e}") from e
        save_cache(cache)
        return cache.languages[lang], cache

    if lang not in cache.languages:
        if not cfg.cache.allow_network_refresh:
            raise VocabRefreshError(
                f"filter vocabulary for {lang!r} is not cached and network refresh is disabled"
            )
        try:
            cache = refresh_cache(langs=[lang], existing=cache, verbose=verbose)
        except Exception as e:
            raise VocabRefreshError(f"failed to refresh filter vocabulary: {e}") from e
        save_cache(cache)
        return cache.languages[lang], cache

    if is_stale(cache, lang, cfg.cache.filters_ttl_days) and cfg.cache.allow_network_refresh:
        try:
            cache = refresh_cache(langs=[lang], existing=cache, verbose=verbose)
            save_cache(cache)
        except Exception as e:
            if verbose:
                print(f"note: soft refresh failed ({e}); using stale cache", file=sys.stderr)

    return cache.languages[lang], cache


# ---- resolver ---------------------------------------------------------------


_FIELD_ALIASES: dict[str, list[str]] = {
    # Delivery mode common shorthands (fi/en)
    "implementation_modes": [
        "Lähikoulutus",
        "Verkkokoulutus",
        "Monimuotokoulutus",
    ],
    "types": [
        "Koulutus",
        "Tukeminen",
    ],
}


_MODE_SHORTHANDS: dict[str, str] = {
    "verkko": "verkkokoulutus",
    "online": "verkkokoulutus",
    "web": "verkkokoulutus",
    "lähi": "lähikoulutus",
    "lahi": "lähikoulutus",
    "onsite": "lähikoulutus",
    "monimuoto": "monimuotokoulutus",
    "hybrid": "monimuotokoulutus",
}


def _normalize(s: str) -> str:
    return s.strip().casefold()


def resolve_one(
    vocab: FilterVocab,
    field: str,
    user_input: str,
    *,
    threshold: int = 80,
) -> FilterOption:
    """Resolve a single user string to a FilterOption for the given field.

    Match order:
      1. Exact value match (raw backend value; useful for numeric IDs).
      2. Exact label match (case-insensitive).
      3. Field-specific shorthand (e.g. 'verkko' -> 'Verkkokoulutus').
      4. Fuzzy label match above threshold.

    Raises VocabError with suggestions when nothing scores high enough.
    """
    options: list[FilterOption] = getattr(vocab, field)
    if not options:
        raise VocabError(f"No options loaded for filter {field!r}.")

    raw = user_input.strip()
    norm = _normalize(raw)

    # 1. exact value match
    for opt in options:
        if opt.value == raw:
            return opt

    # 2. exact label match (case-insensitive)
    for opt in options:
        if _normalize(opt.label) == norm:
            return opt

    # 3. field-specific shorthands
    if field == "implementation_modes":
        alias = _MODE_SHORTHANDS.get(norm)
        if alias:
            for opt in options:
                if _normalize(opt.label) == alias or alias in _normalize(opt.label):
                    return opt

    # 4. fuzzy label match
    labels = [opt.label for opt in options]
    match = process.extractOne(
        raw,
        labels,
        scorer=fuzz.WRatio,
        processor=lambda s: _normalize(s),
    )
    if match and match[1] >= threshold:
        return options[match[2]]

    # No match: build suggestions
    top = process.extract(
        raw,
        labels,
        scorer=fuzz.WRatio,
        processor=lambda s: _normalize(s),
        limit=3,
    )
    suggestions = [t[0] for t in top]
    raise VocabError(
        f"Unknown {field} value {user_input!r}.",
        suggestions=suggestions,
    )


def resolve_many(
    vocab: FilterVocab,
    field: str,
    values: list[str],
    *,
    threshold: int = 80,
) -> list[FilterOption]:
    return [resolve_one(vocab, field, v, threshold=threshold) for v in values]


# ---- self-healing resolver: auto-refresh on miss ---------------------------


def resolve_with_auto_refresh(
    vocab: FilterVocab,
    cache: VocabCache,
    field: str,
    values: list[str],
    *,
    lang: str,
    config: Config,
    threshold: int = 80,
    verbose: bool = False,
) -> tuple[list[FilterOption], FilterVocab, VocabCache]:
    """Resolve values, transparently refreshing the vocab once on a miss.

    Returns the (possibly updated) vocab and cache alongside the resolved options.
    """
    try:
        return resolve_many(vocab, field, values, threshold=threshold), vocab, cache
    except VocabError:
        if not config.cache.allow_network_refresh:
            raise
        if verbose:
            print(
                f"note: refreshing filter vocabulary (cache miss on {field})…",
                file=sys.stderr,
            )
        try:
            cache = refresh_cache(langs=[lang], existing=cache, verbose=verbose)
            save_cache(cache)
        except Exception as e:
            if verbose:
                print(f"note: refresh failed ({e})", file=sys.stderr)
            raise VocabRefreshError(f"failed to refresh filter vocabulary: {e}") from e
        new_vocab = cache.languages[lang]
        return resolve_many(new_vocab, field, values, threshold=threshold), new_vocab, cache
