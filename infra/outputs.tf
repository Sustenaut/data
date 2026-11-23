output "image" {
  description = "Where the deploy workflow pushes the ingest image."
  value       = local.image
}

output "job" {
  description = "The Cloud Run job the deploy updates and the ingest workflow runs."
  value       = google_cloud_run_v2_job.ingest.name
}

output "store_bucket" {
  description = "The bucket the job's store is."
  value       = google_storage_bucket.store.name
}

output "run_log" {
  description = "The run log, as soldera's --run-log takes it."
  value       = "bigquery:${local.run_log}"
}

output "deploy_service_account" {
  description = "The account GitHub Actions in Sustenaut/soldera deploy and re-run as: the repository variable GCP_DEPLOY_SERVICE_ACCOUNT."
  value       = google_service_account.deploy.email
}

output "workload_identity_provider" {
  description = "The provider the deploy and ingest workflows authenticate through, when its id is the pool's: the repository variable GCP_WORKLOAD_IDENTITY_PROVIDER."
  value       = "projects/${data.google_project.this.number}/locations/global/workloadIdentityPools/${var.workload_identity_pool}/providers/${var.workload_identity_pool}"
}
