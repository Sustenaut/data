# data

The code behind [data.sustenaut.eu](https://data.sustenaut.eu): an **ingest
pipeline** that fetches public data and builds it into a database, and an
**app** that lets the team explore that database. The first dataset is EEX's
French guarantees of origin auctions, shown at
[data.sustenaut.eu/go-auctions](https://data.sustenaut.eu/go-auctions).

## Start here

Pick the page for what you do with this repository:

| You… | Read |
| --- | --- |
| use data.sustenaut.eu to look at the data | [Using the site](docs/using.md) |
| build the Streamlit app and how people explore the data | [Developing the app](docs/app.md) |
| build the ingest pipeline and own its data quality | [Developing the ingest pipeline](docs/ingest.md) |
| keep the site and the pipeline running, and own the infrastructure | [Operations](docs/operations.md), and the [runbook](docs/runbook.md) when something is failing |
| are an AI agent working in this repository | [Working as an agent](docs/agents.md), and [AGENTS.md](AGENTS.md) |

## What is where

| Path | What it is |
| --- | --- |
| [`src/app/`](src/app/) | the Streamlit app: landing page and go-auctions page |
| [`src/ingest/`](src/ingest/) | the ingest pipeline: the generic stage runner ([`core/`](src/ingest/core/)), the parsers ([`parsers/`](src/ingest/parsers/)), the canonical schemas ([`canonical/`](src/ingest/canonical/)) and the `data` command ([`cli.py`](src/ingest/cli.py)) |
| [`pipelines/`](pipelines/) | each pipeline's stages and their pinned parser versions |
| [`corrections/`](corrections/) | EEX's published mistakes and what the parser does about each |
| [`tests/`](tests/) | the Gherkin suite ([`features/`](tests/features/)) and its steps ([`steps/`](tests/steps/)) |
| [`infra/`](infra/) | the Terraform for everything in Google Cloud |
| [`.github/workflows/`](.github/workflows/) | CI, the deploys, and the ingest run by hand |
| [`bin/data`](bin/data) | the command line: `data run`, `data output`, `data corrections check`, `data app` |
