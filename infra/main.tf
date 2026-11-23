# The ingest job of data.sustenaut.eu/power-auctions: soldera's image, the
# bucket its store lives in, the BigQuery run log, the Cloud Run job, a weekly
# schedule, and an account only this repository's workflows can act as, which
# deploys the image and starts the job and does nothing else.
#
# The project and region are pubrules.json's (hosting.providers.gcp). The
# project's APIs and the Workload Identity Federation pool are the base
# stack's, found here by their fixed names; this stack never reads its state.

locals {
  gcp              = jsondecode(file("${path.module}/../pubrules.json")).hosting.providers["gcp"]
  project          = local.gcp.project
  region           = local.gcp.region
  scheduler_region = "europe-west1"
  repository       = "Sustenaut/soldera"
  image            = "${local.region}-docker.pkg.dev/${local.project}/${google_artifact_registry_repository.soldera.repository_id}/ingest"
  note_fields = ["note_id", "run_id", "pipeline", "stage", "parser_name", "parser_version", "item_key",
  "severity", "kind", "subject", "message", "source_key", "source_sha256"]
  run_log = "${local.project}.${google_bigquery_dataset.soldera.dataset_id}.${google_bigquery_table.pipeline_stage_runs.table_id}"
}

data "google_project" "this" {
  project_id = local.project
}

# --- The image ----------------------------------------------------------------

resource "google_artifact_registry_repository" "soldera" {
  location      = local.region
  repository_id = "soldera"
  format        = "DOCKER"
  description   = "soldera's ingest image, pushed by GitHub Actions in ${local.repository}."

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }
  cleanup_policies {
    id     = "delete-old"
    action = "DELETE"
    condition {
      older_than = "2592000s" # 30 days, for anything beyond the ten kept above
    }
  }
}

# --- The store ----------------------------------------------------------------

# Every stage's outputs, manifests and notes, mounted in the job at /store.
# Objects are written once by their content hash, so nothing current expires.
# Versioning keeps a replaced or deleted object for 30 days (a stage's latest
# manifest is the one thing rewritten), and every request is logged to the
# bucket below.
resource "google_storage_bucket" "store" {
  name                        = "${local.project}-soldera-store"
  location                    = local.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      days_since_noncurrent_time = 30
      with_state                 = "ARCHIVED"
    }
  }

  logging {
    log_bucket = google_storage_bucket.store_logs.name
  }

  soft_delete_policy {
    retention_duration_seconds = 604800 # 7 days
  }
}

# The store's usage and storage logs, kept for a year. Only Cloud Storage
# writes here; it logs its own requests to itself.
resource "google_storage_bucket" "store_logs" {
  name                        = "${local.project}-soldera-store-logs"
  location                    = local.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age = 365
    }
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      days_since_noncurrent_time = 30
      with_state                 = "ARCHIVED"
    }
  }

  logging {
    log_bucket = "${local.project}-soldera-store-logs"
  }

  soft_delete_policy {
    retention_duration_seconds = 604800 # 7 days
  }
}

# Cloud Storage writes the logs as this group.
resource "google_storage_bucket_iam_member" "store_logs_writer" {
  bucket = google_storage_bucket.store_logs.name
  role   = "roles/storage.objectCreator"
  member = "group:cloud-storage-analytics@google.com"
}

# --- The run log --------------------------------------------------------------

resource "google_bigquery_dataset" "soldera" {
  dataset_id  = "soldera"
  location    = local.region
  description = "soldera's ingest runs: one row per stage per run, and each stage run's notes."
}

# Rows are only appended; a stage's newest row in a run is its state.
resource "google_bigquery_table" "pipeline_stage_runs" {
  dataset_id          = google_bigquery_dataset.soldera.dataset_id
  table_id            = "pipeline_stage_runs"
  description         = "One row when a stage starts and one when it ends, written by soldera run."
  schema              = file("${path.module}/../src/soldera/core/schemas/pipeline_stage_runs.json")
  deletion_protection = true

  time_partitioning {
    type  = "MONTH"
    field = "logged_at"
  }
  clustering = ["pipeline", "stage_name"]
}

# Every stage run's notes.parquet, as written, never copied: the store holds
# no other file named *notes.parquet (outputs are stored by hash, unnamed).
resource "google_bigquery_table" "stage_notes" {
  dataset_id          = google_bigquery_dataset.soldera.dataset_id
  table_id            = "stage_notes"
  description         = "The notes each stage run wrote, read from its notes.parquet in the store."
  deletion_protection = true

  # Named, not detected: detecting reads a file, and there is none until the
  # first run. The columns are soldera.core.notes.FIELDS, every one a string.
  external_data_configuration {
    autodetect    = false
    source_format = "PARQUET"
    source_uris   = ["gs://${google_storage_bucket.store.name}/*notes.parquet"]
    schema = jsonencode([for name in local.note_fields : {
      name = name
      type = "STRING"
      mode = "NULLABLE"
    }])
  }
}

# --- The job ------------------------------------------------------------------

# The job's account: reads and writes its store bucket, appends to its run
# log. shared-infra makes soldera's three accounts and lets this stack set
# their IAM, so that this stack can never set IAM on any other account.
data "google_service_account" "ingest" {
  project    = local.project
  account_id = "soldera-ingest"
}

# Read, write and replace objects (the mount's atomic writes delete the
# temporary file), but not change the bucket or who may use it.
resource "google_storage_bucket_iam_member" "ingest_store" {
  bucket = google_storage_bucket.store.name
  role   = "roles/storage.objectUser"
  member = data.google_service_account.ingest.member
}

resource "google_bigquery_table_iam_member" "ingest_run_log" {
  dataset_id = google_bigquery_dataset.soldera.dataset_id
  table_id   = google_bigquery_table.pipeline_stage_runs.table_id
  role       = "roles/bigquery.dataEditor"
  member     = data.google_service_account.ingest.member
}

# One task, never retried: a failed run fails loudly and waits for a person,
# who re-runs it from the ingest workflow.
resource "google_cloud_run_v2_job" "ingest_job" {
  name                = "soldera-ingest"
  location            = local.region
  deletion_protection = true

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account       = data.google_service_account.ingest.email
      timeout               = "3600s"
      max_retries           = 0
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"

      containers {
        # The first deploy replaces this; Terraform leaves the image alone after.
        image = "us-docker.pkg.dev/cloudrun/container/job"

        env {
          name  = "SOLDERA_STORE"
          value = "/store"
        }
        env {
          name  = "SOLDERA_STORE_URI"
          value = "gs://${google_storage_bucket.store.name}"
        }
        env {
          name  = "SOLDERA_RUN_LOG"
          value = "bigquery:${local.run_log}"
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
          bucket    = google_storage_bucket.store.name
          read_only = false
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }
}

# --- The schedule -------------------------------------------------------------

# Cloud Scheduler's account (shared-infra's): starts the job, nothing else.
data "google_service_account" "scheduler" {
  project    = local.project
  account_id = "soldera-scheduler"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_runs_ingest" {
  name     = google_cloud_run_v2_job.ingest_job.name
  location = local.region
  role     = "roles/run.invoker"
  member   = data.google_service_account.scheduler.member
}

# EEX holds each month's auction on a Wednesday and publishes its results
# the same day; Thursday morning finds them.
# Cloud Scheduler has no europe-north1; the nearest region it runs in calls
# the job in europe-north1 just the same.
resource "google_cloud_scheduler_job" "weekly" {
  name        = "soldera-ingest-weekly"
  region      = local.scheduler_region
  description = "Runs soldera-ingest every Thursday morning."
  schedule    = "0 7 * * 4"
  time_zone   = "Europe/Paris"

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${local.project}/locations/${local.region}/jobs/${google_cloud_run_v2_job.ingest_job.name}:run"

    oauth_token {
      service_account_email = data.google_service_account.scheduler.email
    }
  }
}

# --- Deploys and re-runs from GitHub Actions, without keys ----------------------

# GitHub Actions' account (shared-infra's): pushes the ingest image, deploys
# it to the job, and starts the job.
data "google_service_account" "deploy" {
  project    = local.project
  account_id = "soldera-deploy"
}

resource "google_service_account_iam_member" "deploy_from_github" {
  service_account_id = data.google_service_account.deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/projects/${data.google_project.this.number}/locations/global/workloadIdentityPools/${var.workload_identity_pool}/attribute.repository/${local.repository}"
}

resource "google_artifact_registry_repository_iam_member" "deploy_push" {
  location   = local.region
  repository = google_artifact_registry_repository.soldera.name
  role       = "roles/artifactregistry.writer"
  member     = data.google_service_account.deploy.member
}

# Updating the job's image, and running it with other arguments: only what
# `gcloud run jobs update` and `gcloud run jobs execute --wait` need, granted
# on this one job. The role is shared-infra's, since this stack may not make
# roles.
resource "google_cloud_run_v2_job_iam_member" "deploy" {
  name     = google_cloud_run_v2_job.ingest_job.name
  location = local.region
  role     = "projects/${local.project}/roles/solderaJobDeployer"
  member   = data.google_service_account.deploy.member
}

# A job that runs as the ingest account is deployed by one that may act as it.
resource "google_service_account_iam_member" "deploy_acts_as_ingest" {
  service_account_id = data.google_service_account.ingest.name
  role               = "roles/iam.serviceAccountUser"
  member             = data.google_service_account.deploy.member
}

# The first apply made the job but could not read it back (2026-11-23), so
# its state was marked tainted and every plan after would replace it, which
# deletion_protection forbids. Forgetting that entry and importing the job
# under a new address keeps the job as it is. The registry was made by the
# same run, which could not wait for it. These blocks can go once applied.
removed {
  from = google_cloud_run_v2_job.ingest

  lifecycle {
    destroy = false
  }
}

import {
  to = google_cloud_run_v2_job.ingest_job
  id = "projects/sustenaut/locations/europe-north1/jobs/soldera-ingest"
}

import {
  to = google_artifact_registry_repository.soldera
  id = "projects/sustenaut/locations/europe-north1/repositories/soldera"
}

# The same for the schedule: made, then refused cloudscheduler.jobs.enable,
# so tainted.
removed {
  from = google_cloud_scheduler_job.ingest_weekly

  lifecycle {
    destroy = false
  }
}

import {
  to = google_cloud_scheduler_job.weekly
  id = "projects/sustenaut/locations/europe-west1/jobs/soldera-ingest-weekly"
}
