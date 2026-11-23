variable "workload_identity_pool" {
  description = "Id of the base stack's Workload Identity Federation pool, which GitHub's tokens come through. Its github provider admits main's runs of the repositories in shared-infra's github_repositories, which must list soldera."
  type        = string
  default     = "github"
}

variable "serve_app" {
  description = "Whether the soldera-app service exists. Set it to true once both sign-in secrets hold a value and the deploy workflow has pushed the app's image and its copy of oauth2-proxy (README, \"Deploying the app\")."
  type        = bool
  default     = true
}

# Set by ./pubsec run (the terraform workflow, or ./with-secrets on a laptop)
# from the Bitwarden project Sustenaut, for the names infra/app.tf lists.
variable "secret_values" {
  description = "Secret values by name, read from Bitwarden. Ephemeral: written to Secret Manager, never to the plan or state."
  type        = map(string)
  ephemeral   = true
  sensitive   = true
}

variable "secret_revisions" {
  description = "Each secret's last change in Bitwarden (epoch seconds), by name. A new one adds a Secret Manager version."
  type        = map(number)
}
