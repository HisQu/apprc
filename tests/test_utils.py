from __future__ import annotations

from apprc.utils import deep_get, deep_right_merge, deep_set


def test_nested_dict_helpers_read_write_and_merge() -> None:
    values = {"a": {"b": 1}, "keep": {"left": True}}

    assert deep_get(values, ("a", "b")) == 1
    assert deep_get(values, ("a", "missing"), default="fallback") == "fallback"

    deep_set(values, ("a", "c"), 2)

    assert values["a"]["c"] == 2
    assert deep_right_merge(
        values,
        {"a": {"b": "right"}, "keep": {"right": True}},
    ) == {
        "a": {"b": "right", "c": 2},
        "keep": {"left": True, "right": True},
    }
