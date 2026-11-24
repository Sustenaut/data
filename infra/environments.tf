# What an environment with "ingest": true in environments.json has of its
# own (app.tf has its service): a store, a run log with the runbook's views,
# and an ingest job. A pull request deployed to it (deploy-app.yml) also
# deploys its ingest image to that job and runs it with --from auto, so
# pipeline changes are tried on its own data before they reach live's.
#
# The job runs a pull request's code, so it runs as its own account,
# data-ingest-NAME (shared-infra's), which may write only this store and this
# run log: nothing here can reach live's data. The store is for trying
# things: no access logs, replaced objects kept a week, and emptied when the
# environment is removed. It has no schedule; only deploys run it.

locals {
  ingest_environments = { for name, e in local.environments : name => e if e.ingest }
}

data "google_service_account" "environment_ingest" {
  for_each = local.ingest_environments

  project    = local.project
  account_id = "data-ingest-${each.key}"
}

resource "google_storage_bucket" "environment_store" {
  for_each = local.ingest_environments

  name                        = "${local.project}-data-store-${each.key}"
  location                    = local.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true

  versioning {
    enabled = true
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      days_since_noncurrent_time = 7
      with_state                 = "ARCHIVED"
    }
  }

  soft_delete_policy {
    retention_duration_seconds = 604800 # 7 days
  }
}

resource "google_storage_bucket_iam_member" "environment_ingest_store" {
  for_each = local.ingest_environments

  bucket = google_storage_bucket.environment_store[each.key].name
  role   = "roles/storage.objectUser"
  member = data.google_service_account.environment_ingest[each.key].member
}

resource "google_storage_bucket_iam_member" "app_reads_environment_store" {
  for_each = local.ingest_environments

  bucket = google_storage_bucket.environment_store[each.key].name
  role   = "roles/storage.objectViewer"
  member = data.google_service_account.app.member
}

# --- The run log, as live's (main.tf, views.tf) ---------------------------------

resource "google_bigquery_dataset" "environment_ingest" {
  for_each = local.ingest_environments

  dataset_id                 = "data_ingest_${each.key}"
  location                   = local.region
  description                = "The ${each.key} environment's ingest runs: one row per stage per run, and each stage run's notes."
  delete_contents_on_destroy = true
}

resource "google_bigquery_table" "environment_pipeline_stage_runs" {
  for_each = local.ingest_environments

  dataset_id          = google_bigquery_dataset.environment_ingest[each.key].dataset_id
  table_id            = "pipeline_stage_runs"
  description         = "One row when a stage starts and one when it ends, written by data run."
  schema              = file("${path.module}/../src/ingest/core/schemas/pipeline_stage_runs.json")
  deletion_protection = false

  time_partitioning {
    type  = "MONTH"
    field = "logged_at"
  }
  clustering = ["pipeline", "stage_name"]
}

resource "google_bigquery_table" "environment_stage_notes" {
  for_each = local.ingest_environments

  dataset_id          = google_bigquery_dataset.environment_ingest[each.key].dataset_id
  table_id            = "stage_notes"
  description         = "The notes each stage run wrote, read from its notes.parquet in the store."
  deletion_protection = false

  external_data_configuration {
    autodetect    = false
    source_format = "PARQUET"
    source_uris   = ["gs://${google_storage_bucket.environment_store[each.key].name}/*notes.parquet"]
    schema = jsonencode([for name in local.note_fields : {
      name = name
      type = "STRING"
      mode = "NULLABLE"
    }])
  }
}

resource "google_bigquery_table_iam_member" "environment_ingest_run_log" {
  for_each = local.ingest_environments

  dataset_id = google_bigquery_dataset.environment_ingest[each.key].dataset_id
  table_id   = google_bigquery_table.environment_pipeline_stage_runs[each.key].table_id
  role       = "roles/bigquery.dataEditor"
  member     = data.google_service_account.environment_ingest[each.key].member
}

resource "google_bigquery_table" "environment_stage_runs_latest" {
  for_each = local.ingest_environments

  dataset_id          = google_bigquery_dataset.environment_ingest[each.key].dataset_id
  table_id            = "stage_runs_latest"
  description         = "Each stage of each run as it ended, with its commit, parser and trigger. docs/runbook.md."
  deletion_protection = false

  view {
    query          = templatefile("${path.module}/sql/stage_runs_latest.sql", { table = "${local.project}.${google_bigquery_dataset.environment_ingest[each.key].dataset_id}.${google_bigquery_table.environment_pipeline_stage_runs[each.key].table_id}" })
    use_legacy_sql = false
  }
}

resource "google_bigquery_table" "environment_runs" {
  for_each = local.ingest_environments

  dataset_id          = google_bigquery_dataset.environment_ingest[each.key].dataset_id
  table_id            = "runs"
  description         = "One row per ingest run: how far it got and how it ended. docs/runbook.md."
  deletion_protection = false

  view {
    query          = templatefile("${path.module}/sql/runs.sql", { stage_runs_latest = "${local.project}.${google_bigquery_dataset.environment_ingest[each.key].dataset_id}.${google_bigquery_table.environment_stage_runs_latest[each.key].table_id}" })
    use_legacy_sql = false
  }
}

resource "google_bigquery_table" "environment_failed_items" {
  for_each = local.ingest_environments

  dataset_id          = google_bigquery_dataset.environment_ingest[each.key].dataset_id
  table_id            = "failed_items"
  description         = "What failed in each failed stage run, one row per failed item. docs/runbook.md."
  deletion_protection = false

  view {
    query          = templatefile("${path.module}/sql/failed_items.sql", { stage_runs_latest = "${local.project}.${google_bigquery_dataset.environment_ingest[each.key].dataset_id}.${google_bigquery_table.environment_stage_runs_latest[each.key].table_id}" })
    use_legacy_sql = false
  }
}

# --- The job, as live's (main.tf) -----------------------------------------------

resource "google_cloud_run_v2_job" "environment_ingest" {
  for_each = local.ingest_environments

  name                = "data-ingest-${each.key}"
  location            = local.region
  deletion_protection = false

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account       = data.google_service_account.environment_ingest[each.key].email
      timeout               = "3600s"
      max_retries           = 0
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"

      containers {
        # The first deploy replaces this; Terraform leaves the image alone after.
        image = "us-docker.pkg.dev/cloudrun/container/job"

        env {
          name  = "DATA_STORE"
          value = "/store"
        }
        env {
          name  = "DATA_STORE_URI"
          value = "gs://${google_storage_bucket.environment_store[each.key].name}"
        }
        env {
          name  = "DATA_RUN_LOG"
          value = "bigquery:${local.project}.${google_bigquery_dataset.environment_ingest[each.key].dataset_id}.${google_bigquery_table.environment_pipeline_stage_runs[each.key].table_id}"
        }

        resources {
          limits = {
            cpu    = "2"
            memory = "2Gi"
          }
        }

        volume_mounts {
          name       = "store"
          mount_path = "/store"
        }
      }

      volumes {
        name = "store"
        gcs {
          bucket    = google_storage_bucket.environment_store[each.key].name
          read_only = false
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }
}

# A pull request's deploy updates the job's image and runs it, as data-preview.
resource "google_cloud_run_v2_job_iam_member" "preview_deploys_ingest" {
  for_each = local.ingest_environments

  name     = google_cloud_run_v2_job.environment_ingest[each.key].name
  location = local.region
  role     = "projects/${local.project}/roles/dataJobDeployer"
  member   = data.google_service_account.preview[0].member
}

resource "google_service_account_iam_member" "preview_acts_as_environment_ingest" {
  for_each = local.ingest_environments

  service_account_id = data.google_service_account.environment_ingest[each.key].name
  role               = "roles/iam.serviceAccountUser"
  member             = data.google_service_account.preview[0].member
}
