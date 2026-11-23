# Saved queries over the run log, as views: each is a link in the runbook
# (docs/runbook.md) and can be queried like a table. The SQL is in sql/.

locals {
  run_log_table = "${local.project}.${google_bigquery_dataset.soldera.dataset_id}.${google_bigquery_table.pipeline_stage_runs.table_id}"
  views_dataset = "${local.project}.${google_bigquery_dataset.soldera.dataset_id}"
}

resource "google_bigquery_table" "stage_runs_latest" {
  dataset_id          = google_bigquery_dataset.soldera.dataset_id
  table_id            = "stage_runs_latest"
  description         = "Each stage of each run as it ended, with its commit, parser and trigger. docs/runbook.md."
  deletion_protection = false

  view {
    query          = templatefile("${path.module}/sql/stage_runs_latest.sql", { table = local.run_log_table })
    use_legacy_sql = false
  }
}

resource "google_bigquery_table" "runs" {
  dataset_id          = google_bigquery_dataset.soldera.dataset_id
  table_id            = "runs"
  description         = "One row per ingest run: how far it got and how it ended. docs/runbook.md."
  deletion_protection = false

  view {
    query          = templatefile("${path.module}/sql/runs.sql", { stage_runs_latest = "${local.views_dataset}.${google_bigquery_table.stage_runs_latest.table_id}" })
    use_legacy_sql = false
  }
}

resource "google_bigquery_table" "failed_items" {
  dataset_id          = google_bigquery_dataset.soldera.dataset_id
  table_id            = "failed_items"
  description         = "What failed in each failed stage run, one row per failed item. docs/runbook.md."
  deletion_protection = false

  view {
    query          = templatefile("${path.module}/sql/failed_items.sql", { stage_runs_latest = "${local.views_dataset}.${google_bigquery_table.stage_runs_latest.table_id}" })
    use_legacy_sql = false
  }
}
