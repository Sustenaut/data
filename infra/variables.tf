variable "workload_identity_pool" {
  description = "Id of the base stack's Workload Identity Federation pool, which GitHub's tokens come through. Its condition must admit Sustenaut/soldera."
  type        = string
  default     = "github"
}
