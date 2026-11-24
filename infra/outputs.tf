output "image" {
  description = "Where the deploy workflow pushes the ingest image."
  value       = local.image
}

output "job" {
  description = "The Cloud Run job the deploy updates and the ingest workflow runs."
  value       = google_cloud_run_v2_job.ingest_job.name
}

output "store_bucket" {
  description = "The bucket the job's store is."
  value       = google_storage_bucket.store.name
}

output "run_log" {
  description = "The run log, as data run's --run-log takes it."
  value       = "bigquery:${local.run_log}"
}

output "deploy_service_account" {
  description = "The account GitHub Actions in Sustenaut/data deploy and re-run as, named in deploy-ingest.yml, deploy-app.yml and run-ingest.yml."
  value       = data.google_service_account.deploy.email
}

output "workload_identity_provider" {
  description = "The provider the deploy and ingest workflows authenticate through, whose id is the pool's."
  value       = "projects/${data.google_project.this.number}/locations/global/workloadIdentityPools/${var.workload_identity_pool}/providers/${var.workload_identity_pool}"
}

output "app_image" {
  description = "Where the deploy workflow pushes the app's image."
  value       = local.app_image
}

output "app_services" {
  description = "Each environment's Cloud Run service and address, once var.serve_app is true; shared-infra maps each address to its service."
  value       = { for name, service in google_cloud_run_v2_service.app : name => { service = service.name, site = local.sites[name].site } }
}

output "app_secrets" {
  description = "The secrets a person puts the sign-in values in, before var.serve_app is set."
  value       = keys(google_secret_manager_secret.app_sign_in)
}
