# Developing the ingest pipeline

You own the data and the code that makes it: `src/ingest/`, `pipelines/` and
`corrections/`. The pipeline fetches EEX's published files, checks and
corrects them, and builds the one DuckDB database the [app](app.md) reads.
Data quality is yours: a number on the site that is wrong is wrong here first.

A pipeline is a list of stages. Each stage is the same runner
(`src/ingest/core/runner.py`) with one pinned, versioned parser plugged in,
and every stage keeps its output in the store. So a pipeline can be run again
from any stage, and a new parser version re-runs only its own stage and the
ones after it.

## Running it locally

```sh
make venv
bin/data run pipelines/eex-french-power-auctions.yaml               # every stage, in order
bin/data run pipelines/eex-french-power-auctions.yaml --from parse  # from one stage, reusing what is stored before it
bin/data run pipelines/eex-french-power-auctions.yaml --from auto   # from where a parser pin or an input changed
bin/data run pipelines/eex-french-power-auctions.yaml --force       # build every item again
```

Outputs go to `store/` (`--store`, `DATA_STORE`), filed by content hash.
Run log rows go to `runs.jsonl` (`--run-log`, `DATA_RUN_LOG`), or to BigQuery
with `--run-log bigquery:PROJECT.DATASET.TABLE`. To find or copy the newest
published output of a stage:

```sh
bin/data output pipelines/eex-french-power-auctions.yaml merge                                   # its path
bin/data output pipelines/eex-french-power-auctions.yaml merge --copy-to power-auctions.duckdb   # a copy
bin/data output pipelines/eex-french-power-auctions.yaml discover --name page.html               # one of several
bin/data output pipelines/eex-french-power-auctions.yaml merge --store gs://sustenaut-soldera-store --copy-to power-auctions.duckdb
```

The last reads the bucket with Google's application default credentials.

`bin/data run` exits 0 when every stage succeeded, 1 when a stage failed or
the run log could not be written, and 2 when the run could not start as
asked.

### The EEX pipeline

`pipelines/eex-french-power-auctions.yaml` pins each stage's parser:

| Stage | Parser | What it stores |
| --- | --- | --- |
| discover | eex-french-auction-page | the page, and `files.json`: every file it links to, with its section, title and publishing date |
| download | eex-french-auction-download | each file as fetched, and each file inside an archive |
| select | eex-go-global-results-select | each monthly GO Global Results file, once, by its own name |
| parse | eex-french-auction | `results.parquet` per file, in the canonical `auction_results` schema (`src/ingest/canonical/`) |
| merge | auction-results-duckdb | `power-auctions.duckdb`, the database the app reads |

The merge stage (`src/ingest/parsers/auction_results.py`) writes the tables
`auction_results`, `data_notes` and `build_info`, and the views `auctions`
and `auction_technologies`. Two rows for the same auction, region and
technology, or one auction from two files, fail the run. The merge notes
what only the whole series shows: auction numbers skipped or used twice, and
production months with no auction.

### How a stage runs

For each stage, the runner asks the parser for its work items (`plan`), runs
each one (`transform`), and:

- **skips an item whose output is stored**: the cache key is the parser's
  name and version, the input files' hashes and the item's parameters;
- **fails loudly when an item fails**: the other items still run, so one run
  reports every failure, but the stage then fails, publishes nothing, and
  the run stops with exit 1. The stages after it keep reading the last good run;
- **stores each output once, by its content**, under `objects/`;
- **writes the stage's manifest and notes** under
  `NN-stage/parser@version/runs/<run id>/`, and `latest.json`, which the
  next stage reads;
- **logs a row** when the stage starts and when it ends.

Notes are what a reader of the data should know, such as a file left out or
an auction missing. The stage that finds one writes it to `notes.parquet`.

## Coding conventions, and how they are enforced

| Convention | Enforced by |
| --- | --- |
| Every behaviour has a Gherkin scenario in `tests/features/`, run against `bin/data` as a person would run it, and every scenario has a **When** | the suite in CI (`make functional`), and pubrules' TEST-04 in `pubrules sync --check` |
| A parser subclasses `ingest.core.parser.Parser`, sets `name` and `version`, and registers with `@register`. **Bump the version whenever its output changes**: old outputs are never overwritten, and **deploy ingest pipeline** rebuilds from the first stage whose pin changed | review. `parser_code_hash` in the run log shows a parser edited without a bump |
| Fail loudly: any failed item fails its stage, and nothing partial is published | the runner itself, and its scenarios in `runner.feature` |
| EEX's mistakes are corrected in `corrections/eex-french-power-auctions.yaml`, never in code. Each row rule keeps the file's sha256 and an excerpt, and a rule no longer needed fails the run | `bin/data corrections check`, in the suite |
| The generic runner (`src/ingest/core/`) knows nothing about EEX, and says "ingest run" | review |
| New code is covered by tests, with no new issues or duplication | SonarQube Cloud's quality gate, part of `ci / passed` |
| Temporary code carries `DEBUG(#N)` with an open issue | the **debug markers** workflow (`bin/check-debug-markers`) |
| Files pubrules manages are never edited by hand | `pubrules sync --check` |

`ingest.testing` holds the small parsers the suite's own pipelines use. An
option in a pipeline file may name an environment variable, `${NAME}` or
`${NAME:-default}`, which the suite uses to point a stage at a fake service.

## Debugging

**Locally.** Run the failing stage alone on a copy of the store:

```sh
mkdir -p store && gcloud storage cp -r "gs://sustenaut-soldera-store/*" ./store
bin/data run pipelines/eex-french-power-auctions.yaml --store ./store --from STAGE --to STAGE
```

The run log in `runs.jsonl` has a row per stage with every failed item's
error and traceback. Each stage's notes are in its `notes.parquet`.

**Deployed.** The pipeline runs as the Cloud Run job `soldera-ingest`. The
[runbook](runbook.md) walks through a failed run: the run log's views in
BigQuery, the failed items, the code that ran, and the job's logs.

## Dependencies

| Package | Why |
| --- | --- |
| [PyArrow](https://arrow.apache.org/docs/python/) | the Parquet files every stage writes, and the schemas they follow |
| [DuckDB](https://duckdb.org) | builds the one database file the app reads, with no server |
| [openpyxl](https://openpyxl.readthedocs.io) | reads EEX's xlsx files |
| [PyYAML](https://pyyaml.org) | reads the pipeline files and the corrections file |
| [google-auth](https://googleapis.dev/python/google-auth/latest/) | credentials for the bucket and BigQuery, with no heavier Google client |
| [pubtest](https://github.com/Sustenaut/pubtest) (tests) | the shared Gherkin steps and fakes the suite runs on |

`requirements.lock` pins them, with hashes, for the image (`Dockerfile`).
`make lock` writes it.

Services the pipeline depends on:

- **eex.com**, the source of every file.
- **The store bucket** `gs://sustenaut-soldera-store` and **BigQuery**
  (the run log), in the `sustenaut` project.
- **Cloud Run** and **Cloud Scheduler**, which run it weekly. See
  [Operations](operations.md).

What the app does with the database is in [Developing the app](app.md).
