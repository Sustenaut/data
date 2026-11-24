"""A pipeline's definition, read from YAML:

    pipeline: eex-french-go-auctions
    plugins: [ingest.parsers.eex_french_auction]   # modules that register parsers
    stages:
      - name: discover
        parser: eex-french-auction-page@1.0.0     # the pinned parser version
        options: {url: https://...}

The pins are the only place a parser version is chosen: bumping one is a
reviewed change to this file.

An option may name an environment variable, `${NAME}` or `${NAME:-default}`,
so a test can point a stage at a fake service:

    options: {url: "${EEX_URL:-https://www.eex.com}/en/markets/..."}"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ingest.core import registry
from ingest.core.parser import Parser

NAME = re.compile(r"^[a-z][a-z0-9-]*$")
VARIABLE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)(?::-([^}]*))?\}")


class PipelineError(ValueError):
    pass


@dataclass(frozen=True)
class Stage:
    index: int
    name: str
    parser: type[Parser]
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def prefix(self) -> str:
        """Where this stage's outputs for its pinned parser live."""
        return f"{self.index:02d}-{self.name}/{self.parser.ref()}"


@dataclass(frozen=True)
class Pipeline:
    name: str
    stages: tuple[Stage, ...]
    source: dict[str, Any]

    def stage(self, name: str) -> Stage:
        for stage in self.stages:
            if stage.name == name:
                return stage
        raise PipelineError(f"{self.name} has no stage {name!r}; its stages are {', '.join(self.names())}")

    def names(self) -> list[str]:
        return [s.name for s in self.stages]


def expand(value: Any, where: str) -> Any:
    """An option with every `${NAME}` and `${NAME:-default}` replaced."""
    if isinstance(value, dict):
        return {k: expand(v, where) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v, where) for v in value]
    if not isinstance(value, str):
        return value

    def variable(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        if name in os.environ:
            return os.environ[name]
        if default is None:
            raise PipelineError(f"{where}: {name} is not set and has no default")
        return default

    return VARIABLE.sub(variable, value)


def inside(path: str | Path, root: Path | None = None) -> Path:
    """The pipeline file, resolved, which must be a YAML file under the
    working directory (or `root`): a pipeline is a reviewed file of the
    repository, never a path from elsewhere."""
    base = (root or Path.cwd()).resolve()
    resolved = (base / path).resolve()
    if not resolved.is_relative_to(base):
        raise PipelineError(f"{path} is outside {base}; a pipeline file must be inside the working directory")
    if resolved.suffix not in (".yaml", ".yml"):
        raise PipelineError(f"{path} is not a .yaml file")
    return resolved


def load(path: str | Path) -> Pipeline:
    resolved = inside(path)
    try:
        data = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise PipelineError(f"cannot read {path}: {error}") from error
    if not isinstance(data, dict):
        raise PipelineError(f"{path} must be a mapping with pipeline and stages")
    name = data.get("pipeline")
    if not isinstance(name, str) or not NAME.match(name):
        raise PipelineError(f"{path}: pipeline must be a lowercase name such as eex-french-go-auctions")
    plugins = data.get("plugins") or []
    if not isinstance(plugins, list) or not all(isinstance(p, str) for p in plugins):
        raise PipelineError(f"{path}: plugins must be a list of module names")
    try:
        registry.load(plugins)
    except ImportError as error:
        raise PipelineError(f"{path}: cannot load plugin: {error}") from error
    raw = data.get("stages")
    if not isinstance(raw, list) or not raw:
        raise PipelineError(f"{path}: stages must be a non-empty list")
    stages: list[Stage] = []
    for index, entry in enumerate(raw, start=1):
        stages.append(read_stage(path, index, entry, stages))
    return Pipeline(name, tuple(stages), data)


def read_stage(path: str | Path, index: int, entry: Any, stages: list[Stage]) -> Stage:
    """Stage `index` of the pipeline file: a unique lowercase name, a known
    parser pin and its options."""
    if not isinstance(entry, dict):
        raise PipelineError(f"{path}: stage {index} must be a mapping")
    stage_name, pin = entry.get("name"), entry.get("parser")
    if not isinstance(stage_name, str) or not NAME.match(stage_name):
        raise PipelineError(f"{path}: stage {index} needs a lowercase name")
    if stage_name in [s.name for s in stages]:
        raise PipelineError(f"{path}: stage {stage_name!r} appears twice")
    if not isinstance(pin, str):
        raise PipelineError(f"{path}: stage {stage_name} needs a parser pin, NAME@VERSION")
    try:
        parser = registry.get(pin)
    except registry.UnknownParser as error:
        raise PipelineError(f"{path}: stage {stage_name}: {error}") from error
    options = entry.get("options") or {}
    if not isinstance(options, dict):
        raise PipelineError(f"{path}: stage {stage_name}: options must be a mapping")
    return Stage(index, stage_name, parser, expand(options, f"{path}: stage {stage_name}"))
