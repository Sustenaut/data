variable "workload_identity_pool" {
  description = "Id of the base stack's Workload Identity Federation pool, which GitHub's tokens come through. Its github provider admits main's runs of the repositories in shared-infra's github_repositories, which must list soldera."
  type        = string
  default     = "github"
}
