terraform {
  required_version = ">= 1.11"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }

  # One state bucket for every repository, one prefix each (pubhost's README,
  # "One stack per repository"). The bucket is the base stack's.
  backend "gcs" {
    bucket = "TODO-state-bucket" # TODO(David): the base stack's state bucket
    prefix = "soldera"
  }
}

provider "google" {
  project = local.gcp.project
  region  = local.gcp.region
}
