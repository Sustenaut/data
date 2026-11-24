"""Steps for bin/deploy-environments: GitHub's event as the workflows hand it
over, in its environment variables, and the list it prints."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("deploy_environments.feature")

SCRIPT = Path(__file__).resolve().parents[2] / "bin" / "deploy-environments"


@pytest.fixture
def event():
    """The variables the workflow sets from GitHub's event."""
    return {}


def names(text: str) -> list[str]:
    return [] if text == "nowhere" else [n.strip() for n in text.split(",")]


@given(parsers.parse("a push to main, with the environments {state}"))
def push(event, state):
    event.update(EVENT="push", ENVIRONMENTS=state)


@given(parsers.re(r"a pull request labelled (?P<labels>.+), just (?P<action>pushed to|given (?P<added>\S+))$"))
def pull_request(event, labels, action, added):
    event.update(EVENT="pull_request", LABELS=json.dumps(names(labels)), ENVIRONMENTS="on")
    if added:
        event.update(ACTION="labeled", ADDED=added)
    else:
        event.update(ACTION="synchronize")


@when(parsers.parse("the {part} deploy asks where it goes"), target_fixture="answer")
def ask(event, part):
    env = {k: v for k, v in os.environ.items() if k not in ("EVENT", "ACTION", "ADDED", "LABELS", "ENVIRONMENTS")}
    done = subprocess.run([str(SCRIPT), part], env={**env, **event}, capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


@then(parsers.parse("it goes to {where}"))
def goes_to(answer, where):
    assert [e["name"] for e in answer] == names(where)
    assert all(e["live"] == (e["name"] == "live") for e in answer)
