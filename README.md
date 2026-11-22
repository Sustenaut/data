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

Outputs go to `store/` (`--store`, `SOLDERA_STORE`) and run log rows to
`runs.jsonl` (`--run-log`, `SOLDERA_RUN_LOG`). `soldera run` exits 0 when every
stage succeeded, 1 when a stage failed or some of its items did, and 2 when
the run could not start as asked.

A pipeline file pins each stage's parser:

```yaml
pipeline: demo
plugins: [soldera.testing]          # modules that register parsers
stages:
  - {name: fetch, parser: testing-files@1.0.0, options: {dir: src}}
  - {name: upper, parser: testing-upper@1.0.0}
  - {name: join, parser: testing-join@1.0.0}
```

## How a stage runs

`src/soldera/core/runner.py` is the runner. For each stage it asks the parser
for the stage's work items (`plan`), runs each one (`transform`), and:

- **skips an item whose output is stored**: the cache key is the parser's name
  and version, the input files' hashes and the item's parameters;
- **keeps going when an item fails**: the stage is then `partial`, and the
  next stage reads the items that succeeded;
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
