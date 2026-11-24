# Developing the app

You own how people explore the data: the Streamlit app in `src/app/`, which
is the whole of data.sustenaut.eu. It has a landing page at `/` and the
power-auctions page at `/power-auctions`. It only reads data. The database
it shows is built by the [ingest pipeline](ingest.md).

- `streamlit_app.py` is the entry point: it routes `/` and `/power-auctions`.
- `data.py` holds every number the page shows (filters, bins, statistics,
  regions), with no Streamlit in it, so it is tested on its own.
- `page.py` draws: the sidebar, the tabs, the charts, the sticky header.
- `france-regions.geojson` is the regions map, drawn without any map service.
- `.streamlit/config.toml` (at the repository root) is the theme: Sustenaut's
  colours and fonts, light and dark.

## Running it locally

```sh
make venv                                   # once: .venv with everything the suite and the app need
bin/data output pipelines/eex-french-power-auctions.yaml merge \
  --store gs://sustenaut-soldera-store --copy-to power-auctions.duckdb
bin/data app --database power-auctions.duckdb      # then open http://localhost:8501
```

The copy needs Google credentials that can read the bucket
(`gcloud auth application-default login`). Without them, build a database
yourself with `bin/data run pipelines/eex-french-power-auctions.yaml`, which
fetches from EEX and leaves its store in `store/`, then run `bin/data app
--store ./store`. `bin/data app --store gs://sustenaut-soldera-store` reads
the bucket directly, as the deployed app does.

Streamlit reloads the page when you save a file.

## Coding conventions, and how they are enforced

| Convention | Enforced by |
| --- | --- |
| Every behaviour has a Gherkin scenario in `tests/features/app.feature`, and every scenario has a **When** | the suite in CI (`make functional`), and pubrules' TEST-04 in `pubrules sync --check` |
| Numbers live in `data.py` and are tested there, without a browser. `page.py` only draws | review. The app's scenarios run the page with Streamlit's `AppTest` (`tests/steps/test_app.py`) |
| New code is covered by tests, with no new issues or duplication | SonarQube Cloud's quality gate, part of `ci / passed` |
| Colours and fonts come from Sustenaut/theme. Each technology keeps its colour (`data.COLOURS`) whatever is filtered | review. The theme's tokens are copied into `.streamlit/config.toml` and `page.INKS` |
| Text on the page says what a number is and how it was aggregated, in plain words | review |
| Fail loudly: if the data cannot be read, the page says why instead of showing empty charts | the scenarios for a missing or unreadable store |
| Temporary code carries `DEBUG(#N)` with an open issue | the **debug markers** workflow (`bin/check-debug-markers`) |
| Files pubrules manages (CI workflows, `AGENTS.md`, `tests/requirements-pubrules.txt`) are never edited by hand | `pubrules sync --check` |

Run the app's scenarios alone while you work:

```sh
.venv/bin/python -m pytest -q tests/steps/test_app.py -p no:cacheprovider
```

## Debugging

**Locally.** Errors appear on the page, with a traceback in the terminal that
runs `bin/data app`. To check a number, call the function in `data.py` from a
Python shell on a copy of the database. Chart and layout problems are easiest
to see in a screenshot: Playwright with `colorScheme: 'dark'` checks dark mode.

**Deployed.** The app runs in the Cloud Run service `soldera-app`, behind
oauth2-proxy in the same service. Its logs:

```
resource.type="cloud_run_revision" resource.labels.service_name="soldera-app"
```

A page that says it cannot read the auction results means the bucket has no
published database under the merge parser's pinned version. That happens
after a version bump, until an ingest run rebuilds it, which
**deploy ingest pipeline** does on each deploy. A sign-in loop or a 403 is
oauth2-proxy and the team's roles, not the app: see [Operations](operations.md).

## Dependencies

| Package | Why |
| --- | --- |
| [Streamlit](https://streamlit.io) | the app framework: pages, widgets, theming and a test harness (`AppTest`) without writing a front end |
| [Plotly](https://plotly.com/python/) | interactive charts with hover, and polygons for the regions map without a map service |
| [DuckDB](https://duckdb.org) | reads the database file the ingest pipeline builds, fast, with no server |
| [PyArrow](https://arrow.apache.org/docs/python/) | the tables between DuckDB and the charts |
| [Nunito and Nunito Sans](https://github.com/Sustenaut/theme) | Sustenaut's fonts, from Sustenaut/theme through jsDelivr |

`requirements-app.lock` pins them, with hashes, for the image
(`app.Dockerfile`). `make runtime-lock` writes it.

Services the app depends on:

- **The store bucket** `gs://sustenaut-soldera-store`, where the ingest
  pipeline publishes the database. See [Developing the ingest pipeline](ingest.md).
- **auth.sustenaut.eu**, the team sign-in, through oauth2-proxy in front of the app.
- **Cloud Run**, which serves it. See [Operations](operations.md).
