"""Interfaces package for LYRA."""

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "main":
        from lyra.interfaces.cli import main
        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["main"]
