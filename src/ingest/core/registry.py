"""Parsers by name and version. Old versions stay registered, so a pipeline
can pin back to one and reuse the outputs it stored."""

from __future__ import annotations

import importlib

from ingest.core.parser import Parser

_PARSERS: dict[tuple[str, str], type[Parser]] = {}

# Modules whose parsers every pipeline can use. Each registers its parsers
# when imported.
BUILT_IN: tuple[str, ...] = ()


class UnknownParser(LookupError):
    pass


def register(cls: type[Parser]) -> type[Parser]:
    """Class decorator: make a parser available by its name and version."""
    key = (cls.name, cls.version)
    if key in _PARSERS and _PARSERS[key] is not cls:
        raise ValueError(f"{cls.ref()} is registered twice")
    _PARSERS[key] = cls
    return cls


def load(modules: list[str] | tuple[str, ...]) -> None:
    for module in (*BUILT_IN, *modules):
        importlib.import_module(module)


def get(ref: str) -> type[Parser]:
    """The parser a pin such as `eex-french-auction@1.0.0` names."""
    name, sep, version = ref.partition("@")
    if not sep or not name or not version:
        raise UnknownParser(f"parser pin {ref!r} must be NAME@VERSION")
    if (name, version) in _PARSERS:
        return _PARSERS[(name, version)]
    known = sorted(v for n, v in _PARSERS if n == name)
    if known:
        raise UnknownParser(f"{name} has no version {version}; it has {', '.join(known)}")
    raise UnknownParser(f"no parser is named {name}")
