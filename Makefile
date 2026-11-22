# soldera: ingest pipelines for data.sustenaut.eu. CI runs `make venv` then
# `make functional` (pubrules.json's ci block).

PYTHON ?= python3
VENV := .venv

.PHONY: venv functional check lock sync-check clean

venv: $(VENV)/.done

$(VENV)/.done: tests/requirements.lock
	$(PYTHON) -m venv $(VENV)
	tests/install-lock $(VENV)/bin/pip
	touch $@

# The Gherkin suite, run against bin/soldera on every core, with its coverage
# (and that of every soldera it starts) in coverage/coverage.xml.
functional: venv
	rm -rf coverage && mkdir coverage
	cd tests && COVERAGE_RCFILE=$(CURDIR)/pyproject.toml COVERAGE_FILE=$(CURDIR)/coverage/.coverage \
	  SOLDERA_BIN_DIR=$(CURDIR)/bin ../$(VENV)/bin/coverage run -m pytest -n auto
	COVERAGE_RCFILE=pyproject.toml COVERAGE_FILE=coverage/.coverage $(VENV)/bin/coverage combine -q
	COVERAGE_RCFILE=pyproject.toml COVERAGE_FILE=coverage/.coverage $(VENV)/bin/coverage xml -q
	COVERAGE_RCFILE=pyproject.toml COVERAGE_FILE=coverage/.coverage $(VENV)/bin/coverage report

check: sync-check functional ## Everything CI runs

lock:
	./pubrules lock

sync-check:
	./pubrules sync --check

clean:
	rm -rf $(VENV) coverage
