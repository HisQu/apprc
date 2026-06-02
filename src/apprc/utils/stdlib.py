"""Utility functions to fill in gaps in the Python standard library."""

# %%

from functools import reduce
from operator import getitem
from typing import Any

from contextlib import contextmanager
import time

from typing import Callable

# =====================================================================
# === Dictionary / JSON conveniences
# =====================================================================


# %%
def deep_get(d: dict, keypath: tuple, default=None) -> Any:
    """Safely get a nested key by providing a path of keys: deep_get(cfg, 'db', 'host')."""
    try:
        return reduce(getitem, keypath, d)
    except (KeyError, TypeError):
        return default


def deep_set(
    d: dict,
    keypath: tuple,
    value: Any,
) -> None:
    """Set a nested key, creating dictionaries on the way."""
    for k in keypath[:-1]:
        d = d.setdefault(k, {})
    d[keypath[-1]] = value


def deep_right_merge(a: dict, b: dict) -> dict:
    """Recursively merge dict *b* into copy of *a* (right-bias)."""
    out = a.copy()
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_right_merge(out[k], v)
        else:
            out[k] = v
    return out


if __name__ == "__main__":
    _test_dict = {"a": {"_b": 1, "_c": 2}, "d": {"_e": 3}}
    print(deep_get(_test_dict, keypath=("a", "_b"), default=None))

    deep_set(_test_dict, keypath=("a", "_b"), value="new")
    print(_test_dict)

    _test_dict2 = {"a": 1, "b": 2, "c": {"_d": 3}}
    print(deep_right_merge(_test_dict, _test_dict2))


# =====================================================================
# === Custom Context Managers (with statement)
# =====================================================================


# %%
@contextmanager
def timer(name: str = "block"):
    """Context manager that prints elapsed time for a code block."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        print(f"{name} finished in {elapsed:0.4f}s")


if __name__ == "__main__":
    with timer("Example"):
        time.sleep(2)


# =====================================================================
# === Others
# =====================================================================

# %%
