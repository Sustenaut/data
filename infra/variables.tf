variable "workload_identity_pool" {
  description = "Id of the base stack's Workload Identity Federation pool, which GitHub's tokens come through. Its github provider admits main's runs of the repositories in shared-infra's github_repositories, which must list Sustenaut/data."
  type        = string
  default     = "github"
}

variable "registry_granted" {
  description = "Whether this stack may set IAM on its registry. shared-infra grants that on the registry \"data\" once this stack's first apply has made it (its data_registry_made). Until then the deploy account cannot push and Terraform cannot pull (docs/operations.md, \"Setting it up\")."
  type        = bool
  default     = true
}

variable "serve_app" {
  description = "Whether the data-app service exists. Set it to true once both sign-in secrets hold a value and the deploy workflow has pushed the app's image and its copy of oauth2-proxy (docs/operations.md, \"Setting it up\")."
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
