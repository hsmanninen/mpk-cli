from __future__ import annotations

from datetime import date

from mpk.search import SearchQuery


def test_search_query_form_data_basic() -> None:
    q = SearchQuery(text="ensiapu", begin=date(2026, 8, 12), lang="fi")
    data = q.to_form_data()
    d = dict(data)
    assert d["SearchText"] == "ensiapu"
    assert d["BeginDate"] == "2026-08-12"
    assert d["LangId"] == "0"
    assert d["CalendarViewMode"] == "list"


def test_search_query_form_data_repeat_keys() -> None:
    q = SearchQuery(
        cities=["Helsinki", "Tampere"],
        specializations=["1002", "1042"],
        implementation_modes=["1"],
    )
    data = q.to_form_data()
    cities = [v for k, v in data if k == "City"]
    specs = [v for k, v in data if k == "SpecializationId"]
    modes = [v for k, v in data if k == "ImplementationMethodId"]
    assert cities == ["Helsinki", "Tampere"]
    assert specs == ["1002", "1042"]
    assert modes == ["1"]


def test_search_query_form_data_ongoing_flag() -> None:
    enabled = [v for k, v in SearchQuery().to_form_data() if k == "ShowOnGoingOpenEvents"]
    disabled = [
        v
        for k, v in SearchQuery(include_ongoing=False).to_form_data()
        if k == "ShowOnGoingOpenEvents"
    ]
    assert enabled == ["true", "false"]
    assert disabled == ["false"]


def test_lang_switch() -> None:
    for lang, expected in [("fi", "0"), ("en", "1"), ("sv", "2")]:
        q = SearchQuery(lang=lang)
        d = dict(q.to_form_data())
        assert d["LangId"] == expected
