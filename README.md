# soldera

Ingest pipelines for [data.sustenaut.eu](https://data.sustenaut.eu). The first
pipeline takes the results of the French auctions of power guarantees of origin
from EEX and turns them into one DuckDB database for the power-auctions app.

A pipeline is a list of stages. Each stage is the same runner with one pinned,
versioned parser plugged in, and every stage keeps its output in the store. So
a pipeline can be run again from any stage, and a new parser version re-runs
only its own stage and the ones after it.

## Running a pipeline

```sh
make venv
bin/soldera run PIPELINE.yaml                 # every stage, in order
bin/soldera run PIPELINE.yaml --from parse    # from one stage, reusing what is stored before it
bin/soldera run PIPELINE.yaml --from auto     # from where a parser pin or an input changed
bin/soldera run PIPELINE.yaml --force         # build every item again
```

Outputs go to `store/` (`--store`, `SOLDERA_STORE`), filed by content hash. To
find or copy the newest published output of a stage:

```sh
bin/soldera output PIPELINE.yaml merge                                   # its path
bin/soldera output PIPELINE.yaml merge --copy-to power-auctions.duckdb   # a copy
bin/soldera output PIPELINE.yaml discover --name page.html               # one of several
```

Run log rows go to `runs.jsonl`, or to BigQuery with
`--run-log bigquery:PROJECT.DATASET.TABLE` (`SOLDERA_RUN_LOG`). The table's
schema is `src/soldera/core/schemas/pipeline_stage_runs.json`; rows are
streamed in with Google's application default credentials (the job's service
account on Cloud Run, `gcloud auth application-default login` on a laptop).
A row that cannot be written stops the run.

Web requests are tried up to three times when a transfer is cut off, the
connection drops or times out, or the server answers 429 or 5xx.

`soldera run` exits 0 when every stage succeeded, 1 when a stage failed (any
of its items failing fails it) or the run log could not be written, and 2
when the run could not start as asked.

A pipeline file pins each stage's parser:

```yaml
pipeline: demo
plugins: [soldera.testing]          # modules that register parsers
stages:
  - {name: fetch, parser: testing-files@1.0.0, options: {dir: src}}
  - {name: upper, parser: testing-upper@1.0.0}
  - {name: join, parser: testing-join@1.0.0}
```

An option may name an environment variable, `${NAME}` or
`${NAME:-default}`; the suite uses that to point a stage at a fake service.

## The EEX pipeline

`pipelines/eex-french-power-auctions.yaml` is the pipeline for
data.sustenaut.eu/power-auctions. Its parsers are in `src/soldera/parsers/eex/`:

| Stage | Parser | What it stores |
| --- | --- | --- |
| discover | eex-french-auction-page | the page, and `files.json`: every file it links to, with its section, title and publishing date |
| download | eex-french-auction-download | each file as fetched, and each file inside an archive |
| select | eex-go-global-results-select | each monthly GO Global Results file, once, by its own name |
| parse | eex-french-auction | `results.parquet` per file, in the canonical `auction_results` schema (`src/soldera/canonical/`) |
| merge | auction-results-duckdb | `power-auctions.duckdb`, the database the app reads (below) |

```sh
bin/soldera run pipelines/eex-french-power-auctions.yaml
```

The merge stage (`src/soldera/parsers/auction_results.py`, for any
provider's `auction_results`) writes one DuckDB file:

| Name | What it holds |
| --- | --- |
| `auction_results` | every row, by auction date |
| `data_notes` | every note of every stage, copied from each stage's `notes.parquet` |
| `build_info` | one row: the run, the parser, how many files, rows and auctions, the first and last auction date |
| `auctions` (view) | one row per auction: volumes, volume-weighted price, bidders, winners |
| `auction_technologies` (view) | the same per auction and technology |

Two rows for the same auction, region and technology, or one auction from
two files, fail the run. The merge notes what only the whole series shows:
auction numbers skipped or used twice, and production months with no
auction.

### Data corrections

Every results file must hold all 48 region and technology pairs, in EEX's
usual order, with no pair twice. Where EEX published a mistake, a rule in
`corrections/eex-french-power-auctions.yaml` says what is wrong, why we think
so, and what the parser does about it: drop or set fields of a wrong row,
note a missing row, or accept a file's other order or a partial auction. A
rule that a file no longer needs fails the run, so a fix by EEX is noticed.
The file is plain YAML so it can be sent to EEX as is.

Each row rule keeps the file's sha256 and an excerpt of the rows as
published, so the evidence survives EEX replacing the file. This checks
every rule against its excerpt (the tests run it too):

```sh
bin/soldera corrections check corrections/eex-french-power-auctions.yaml
```

## Deploying

The ingest runs as the Cloud Run job `soldera-ingest`, in the `sustenaut`
project (`pubrules.json`, `hosting.providers.gcp`). `infra/` makes it and
everything around it:

| Resource | What it is for |
| --- | --- |
| `soldera` registry | the ingest image (`Dockerfile`), the ten newest kept |
| `sustenaut-soldera-store` bucket | the store, mounted in the job at `/store` |
| `soldera.pipeline_stage_runs` | the run log, schema `src/soldera/core/schemas/pipeline_stage_runs.json` |
| `soldera.stage_notes` | an external table over every stage run's `notes.parquet` in the bucket |
| `soldera-ingest` job | one task, never retried, an hour at most, as `soldera-ingest@` |
| `soldera-ingest-weekly` | Cloud Scheduler, Thursdays 07:00 Paris time, the morning after EEX's auction day |
| `soldera-deploy@` | what this repository's workflows act as: push the image, update and run the job |

Workflows:

- **terraform** applies `infra/` from main with pubhost's `terraform.yml`
  once the repository variable `TERRAFORM_CI` is `on`.
- **deploy** builds the image on each change to main that touches it, checks
  that it starts, pushes it and points the job at it, once `DEPLOY_CI` is `on`.
- **ingest** (Actions, ingest, Run workflow) runs the job now with `from`,
  `to` and `force`, and fails when the job does. The run log rows link back
  to the workflow run.

To turn it on: the base stack's pool must admit `Sustenaut/soldera` and make
its Terraform account; set the repository variables
`GCP_WORKLOAD_IDENTITY_PROVIDER` and `TERRAFORM_SERVICE_ACCOUNT`, make the
environments `terraform` and `deploy` limited to main, and set
`TERRAFORM_CI=on`. After the first apply, set `GCP_DEPLOY_SERVICE_ACCOUNT` to
the `deploy_service_account` output and `DEPLOY_CI=on`. The project needs the
Run, Artifact Registry, BigQuery, Cloud Scheduler and Storage APIs, which
are the base stack's.

`make lock` also writes `requirements.lock`, the image's packages at the
suite's versions, with hashes.

## How a stage runs

`src/soldera/core/runner.py` is the runner. For each stage it asks the parser
for the stage's work items (`plan`), runs each one (`transform`), and:

- **skips an item whose output is stored**: the cache key is the parser's name
  and version, the input files' hashes and the item's parameters;
- **fails loudly when an item fails**: the other items still run, so one run
  reports every failure, but the stage then fails, publishes nothing, and the
  run stops with exit 1. The stages after it keep reading the last good run;
- **stores each output once, by its content**, under `objects/`, so an
  unchanged file fetched again costs nothing;
- **writes the stage's manifest and notes** under
  `NN-stage/parser@version/runs/<run id>/`, and `latest.json`, which the next
  stage reads;
- **logs a row** when the stage starts (`running`) and when it ends, with
  what every item did.

Outputs of an old parser version are never overwritten, so pinning back to it
reuses them.

Notes are what a reader of the data should know, such as a file left out or an
auction missing. The stage that finds one writes it to `notes.parquet`; every
other view of it reads or copies those rows.

## Parsers

A parser subclasses `soldera.core.parser.Parser`, sets `name` and `version`,
implements `transform`, and is registered with `@register`. Bump the version
whenever its output changes. `soldera.testing` holds the small parsers the
suite uses.

## Tests

The suite is Gherkin, on pubtest's steps, and drives `bin/soldera` as a person
would: `make functional`. CI is pubrules': `pubrules.json`'s `ci` block, written
out by `./pubrules sync`.
