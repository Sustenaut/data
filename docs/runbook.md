# Runbook

What to do when an ingest run fails. Problems with the site, and the bigger
picture, are in [Operations](operations.md).

The ingest pipeline runs as the Cloud Run job `soldera-ingest` in the `sustenaut`
project: every Thursday at 07:00 Paris time from Cloud Scheduler, and by hand
from the **run ingest pipeline** workflow. A failed run fails loudly. Nothing is published,
later stages keep their last good run, and the job exits 1.

## Where things are

| What | Where |
| --- | --- |
| The run log | [`soldera.pipeline_stage_runs`](https://console.cloud.google.com/bigquery?project=sustenaut&ws=!1m5!1m4!4m3!1ssustenaut!2ssoldera!3spipeline_stage_runs), one row when a stage starts and one when it ends |
| Runs, one row each | [`soldera.runs`](https://console.cloud.google.com/bigquery?project=sustenaut&ws=!1m5!1m4!4m3!1ssustenaut!2ssoldera!3sruns) (view) |
| Each stage as it ended | [`soldera.stage_runs_latest`](https://console.cloud.google.com/bigquery?project=sustenaut&ws=!1m5!1m4!4m3!1ssustenaut!2ssoldera!3sstage_runs_latest) (view) |
| What failed | [`soldera.failed_items`](https://console.cloud.google.com/bigquery?project=sustenaut&ws=!1m5!1m4!4m3!1ssustenaut!2ssoldera!3sfailed_items) (view) |
| Data notes | [`soldera.stage_notes`](https://console.cloud.google.com/bigquery?project=sustenaut&ws=!1m5!1m4!4m3!1ssustenaut!2ssoldera!3sstage_notes), every stage run's notes.parquet |
| The job's executions | [Cloud Run, soldera-ingest](https://console.cloud.google.com/run/jobs/details/europe-north1/soldera-ingest/executions?project=sustenaut) |
| The store | [`gs://sustenaut-soldera-store`](https://console.cloud.google.com/storage/browser/sustenaut-soldera-store?project=sustenaut) |
| Workflows | [run ingest pipeline](https://github.com/Sustenaut/soldera/actions/workflows/run-ingest.yml), [deploy ingest pipeline](https://github.com/Sustenaut/soldera/actions/workflows/deploy-ingest.yml), [deploy app](https://github.com/Sustenaut/soldera/actions/workflows/deploy-app.yml), [terraform](https://github.com/Sustenaut/soldera/actions/workflows/terraform.yml) |

The views are made by `infra/views.tf`, and their SQL is in `infra/sql/`.
Open one and use **Query** (or `SELECT * FROM` it) to run it.

## Debugging a failed run

1. **Find the run.** Look in `soldera.runs`, newest first:

   ```sql
   SELECT * FROM `sustenaut.soldera.runs` ORDER BY started_at DESC LIMIT 10
   ```

   `failed_stage` names the stage that stopped the run. `github_run_url` links
   to the workflow run for a run started by hand; `cloud_run_execution` names
   the execution for a scheduled one.

2. **See what failed.** One row per failed item, with its error and traceback:

   ```sql
   SELECT * FROM `sustenaut.soldera.failed_items` WHERE run_id = 'RUN_ID'
   ```

   A row with no `item_key` is a stage that could not start, such as an
   unreadable upstream manifest or a bad option.

3. **Find the code that ran.** `commit_url` in `stage_runs_latest` is the
   commit the image was built from. `parser_name`, `parser_version` and
   `parser_code_hash` say which parser ran. A hash that changed without a
   version bump means the parser was edited in place.

   ```sql
   SELECT stage_name, status, parser_name, parser_version, parser_code_hash, commit_url
   FROM `sustenaut.soldera.stage_runs_latest` WHERE run_id = 'RUN_ID' ORDER BY stage_index
   ```

4. **Read the job's logs**, if the run log has no row for the run (the job
   died before it could write one). Open the execution from the Cloud Run
   page above, or in Logs Explorer:

   ```
   resource.type="cloud_run_job" resource.labels.job_name="soldera-ingest"
   ```

5. **Reproduce it locally** with the same inputs. Copy the store, then run the
   failed stage alone (`make venv` first):

   ```
   mkdir -p store && gcloud storage cp -r "gs://sustenaut-soldera-store/*" ./store
   bin/data run pipelines/eex-french-go-auctions.yaml --store ./store --from STAGE --to STAGE
   ```

## Common failures

| Error | What it means | What to do |
| --- | --- | --- |
| `download: … failed after 3 tries` | EEX's site timed out or cut a transfer off three times | Re-run with **run ingest pipeline**, `from: download` |
| A correction rule is no longer needed | EEX fixed a file that `corrections/eex-french-go-auctions.yaml` corrects | Remove the rule in a PR, then re-run from `parse` |
| A file has the wrong number of segments, or rows out of order | EEX changed a file's layout | Add a correction rule with an excerpt, or a new parser version, in a PR |
| `database: … has REGION TECH twice` or `comes from N files` | Two files give the same auction | Find both files in `failed_items`, and decide which one wins in `corrections/` |
| `403 … Permission … denied` | The job's account lacks a grant | Grants for the job's accounts are in `infra/main.tf`; grants for terraform-data are in shared-infra's `infra/terraform-ci.tf` |

## Re-running

From [Actions, run ingest pipeline, Run workflow](https://github.com/Sustenaut/soldera/actions/workflows/run-ingest.yml):
`from` and `to` pick the stages, and `force` rebuilds items even when their
inputs are unchanged. Stages before `from` keep their last good run. The new
run's rows have `trigger = 'rerun'` and `rerun_from_stage` set.
