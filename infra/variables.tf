variable "workload_identity_pool" {
  description = "Id of the base stack's Workload Identity Federation pool, which GitHub's tokens come through. Its github provider admits main's runs of the repositories in shared-infra's github_repositories, which must list soldera."
  type        = string
  default     = "github"
}

variable "serve_app" {
  description = "Whether the soldera-app service exists. Set it to true once both sign-in secrets hold a value and the deploy workflow has pushed the app's image and its copy of oauth2-proxy (README, \"Deploying the app\")."
  type        = bool
  default     = false
}
