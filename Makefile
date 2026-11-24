# data.sustenaut.eu: its ingest pipelines and app. CI runs `make venv` then
# `make functional` (pubrules.json's ci block).

PYTHON ?= python3
VENV := .venv

.PHONY: venv functional lint fmt check lock runtime-lock sync-check clean

venv: $(VENV)/.done

$(VENV)/.done: tests/requirements.lock
	$(PYTHON) -m venv $(VENV)
	tests/install-lock $(VENV)/bin/pip
	touch $@

# The Gherkin suite, run against bin/data on every core, with its coverage
# (and that of every bin/data it starts) in coverage/coverage.xml.
functional: venv
	rm -rf coverage && mkdir coverage
	cd tests && COVERAGE_RCFILE=$(CURDIR)/pyproject.toml COVERAGE_FILE=$(CURDIR)/coverage/.coverage \
	  DATA_BIN_DIR=$(CURDIR)/bin ../$(VENV)/bin/coverage run -m pytest -n auto
	COVERAGE_RCFILE=pyproject.toml COVERAGE_FILE=coverage/.coverage $(VENV)/bin/coverage combine -q
	COVERAGE_RCFILE=pyproject.toml COVERAGE_FILE=coverage/.coverage $(VENV)/bin/coverage xml -q
	COVERAGE_RCFILE=pyproject.toml COVERAGE_FILE=coverage/.coverage $(VENV)/bin/coverage report

# Ruff, with pubrules' Python standard (pubrules-ruff.toml, which
# pyproject.toml extends), as CI's lint job runs it.
lint: venv
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

# Format the code, and apply Ruff's safe fixes.
fmt: venv
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

check: sync-check functional ## Everything CI runs

lock:
	./pubrules lock
	$(MAKE) runtime-lock

# The images' packages: pyproject.toml's dependencies, at the versions the
# suite's lock pins, with hashes, for Linux on x86_64. requirements.lock is
# the ingest job's; requirements-app.lock adds the app extra, for the app's.
runtime-lock:
	grep -E '^[A-Za-z0-9_.-]+==' tests/requirements.lock | sed 's/ .*//' > .runtime-constraints.txt
	uv pip compile pyproject.toml -c .runtime-constraints.txt --generate-hashes --no-header -q \
	  --python-version 3.13 --python-platform x86_64-manylinux_2_28 -o requirements.lock
	uv pip compile pyproject.toml --extra app -c .runtime-constraints.txt --generate-hashes --no-header -q \
	  --python-version 3.13 --python-platform x86_64-manylinux_2_28 -o requirements-app.lock
	rm .runtime-constraints.txt

sync-check:
	./pubrules sync --check

clean:
	rm -rf $(VENV) coverage
