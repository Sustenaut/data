# The app at data.sustenaut.eu: the landing page at / and the go-auctions
# app at /go-auctions (src/app), one Streamlit server in the Cloud
# Run service data-app, with oauth2-proxy in front of it in the same
# service. The proxy signs people in with the team realm at auth.sustenaut.eu
# and lets in only those with the role data, as business-plan's planning app
# does with plan. The app reads the newest database the database stage published
# in the store bucket, as data-app, which may read that bucket and the two
# sign-in secrets and nothing else. The deploy workflow builds the app's
# image and points the service's app container at it; shared-infra maps
# data.sustenaut.eu to the service.
#
# The service needs both secrets to hold a value (from Bitwarden, below), and
# both images to be in the registry, before it can start. So it waits for var.serve_app, which a
# pull request sets once a person has added the values and the deploy
# workflow has pushed the images (docs/operations.md, "Setting it up").

locals {
  app_image   = "${local.region}-docker.pkg.dev/${local.project}/${google_artifact_registry_repository.data.repository_id}/app"
  proxy_image = "${local.region}-docker.pkg.dev/${local.project}/${google_artifact_registry_repository.data.repository_id}/oauth2-proxy:v7.15.5"
  site        = "data.sustenaut.eu"
}

# The service's account (shared-infra's).
data "google_service_account" "app" {
  project    = local.project
  account_id = "data-app"
}

resource "google_storage_bucket_iam_member" "app_reads_store" {
  bucket = google_storage_bucket.store.name
  role   = "roles/storage.objectViewer"
  member = data.google_service_account.app.member
}

# The values are kept in the Bitwarden Secrets Manager project Sustenaut,
# under these names. The terraform workflow runs through ./pubsec run, which
# reads them (with-secrets.json lists this file) and hands them over as the
# ephemeral var.secret_values; each goes to Secret Manager through a
# write-only argument, so no value is in git, the plan or the state.
resource "google_secret_manager_secret" "app_sign_in" {
  for_each = {
    "data-oidc-client-secret" = "Secret of sustenaut.eu's team client, which data-app's oauth2-proxy signs in with."
    "data-cookie-secret"      = "Key data-app's oauth2-proxy encrypts its session cookies with."
  }

  secret_id   = each.key
  labels      = { managed-by = "terraform" }
  annotations = { description = each.value }

  replication {
    user_managed {
      replicas {
        location = local.region
      }
    }
  }
}

# A value changed in Bitwarden has a new revision, which adds a version here;
# the one it replaces is disabled, not destroyed, so it can be switched back.
resource "google_secret_manager_secret_version" "app_sign_in" {
  for_each = { for name, revision in var.secret_revisions : name => revision if contains(keys(google_secret_manager_secret.app_sign_in), name) }

  secret                 = google_secret_manager_secret.app_sign_in[each.key].id
  secret_data_wo         = var.secret_values[each.key]
  secret_data_wo_version = each.value
  deletion_policy        = "DISABLE"
}

resource "google_secret_manager_secret_iam_member" "app_reads_sign_in" {
  for_each = google_secret_manager_secret.app_sign_in

  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = data.google_service_account.app.member
}

# Cloud Run checks that whoever creates or changes the service may pull its
# images, so this stack's own account (the terraform workflow's) reads the
# registry. The ingest job never needed it: it starts from a public
# placeholder image (main.tf).
data "google_client_openid_userinfo" "terraform" {}

resource "google_artifact_registry_repository_iam_member" "terraform_pulls" {
  count = var.registry_granted ? 1 : 0

  location   = local.region
  repository = google_artifact_registry_repository.data.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${data.google_client_openid_userinfo.terraform.email}"
}

resource "google_cloud_run_v2_service" "app" {
  count = var.serve_app ? 1 : 0

  name                = "data-app"
  location            = local.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  iap_enabled         = false # oauth2-proxy signs people in (below)
  deletion_protection = true

  template {
    service_account = data.google_service_account.app.email
    # Streamlit keeps each page open over one websocket: an hour before
    # Cloud Run closes it (the page then reconnects), and the same instance
    # for a browser while it lasts.
    timeout                          = "3600s"
    session_affinity                 = true
    max_instance_request_concurrency = 80

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    # oauth2-proxy, the service's front container: the team realm, as
    # sustenaut.eu's team client, letting in only people with the role data.
    # The same settings as the planning app's (business-plan infra/plan.tf),
    # but its own cookie. The deploy workflow keeps a copy of this exact
    # release in this stack's registry, as Cloud Run does not pull from quay.io.
    containers {
      name       = "oauth2-proxy"
      image      = local.proxy_image
      depends_on = ["app"]
      ports {
        container_port = 4180
      }
      args = [
        "--provider=keycloak-oidc",
        "--oidc-issuer-url=https://auth.sustenaut.eu/realms/team",
        "--code-challenge-method=S256",
        "--scope=openid email profile",
        "--http-address=0.0.0.0:4180",
        "--upstream=http://127.0.0.1:8080/",
        "--redirect-url=https://${local.site}/oauth2/callback",
        "--reverse-proxy=true",
        "--email-domain=*",
        "--oidc-groups-claim=access",
        "--allowed-group=data",
        "--cookie-refresh=4m",
        "--cookie-name=_data",
        "--cookie-secure=true",
        "--cookie-samesite=lax",
        "--skip-provider-button=true",
        "--silence-ping-logging=true",
      ]
      env {
        name  = "OAUTH2_PROXY_CLIENT_ID"
        value = "sustenaut.eu"
      }
      env {
        name = "OAUTH2_PROXY_CLIENT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.app_sign_in["data-oidc-client-secret"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "OAUTH2_PROXY_COOKIE_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.app_sign_in["data-cookie-secret"].secret_id
            version = "latest"
          }
        }
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "256Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }
    }

    # The app, on 8080, reached only by oauth2-proxy on localhost. The deploy
    # workflow sets its image and Terraform leaves it alone after: the first
    # revision starts from the newest image the workflow pushed.
    containers {
      name  = "app"
      image = "${local.app_image}:latest"
      env {
        name  = "DATA_STORE"
        value = "gs://${google_storage_bucket.store.name}"
      }
      # The page links the run that built its data; a scheduled run is a
      # Cloud Run execution of the ingest job, shown here.
      env {
        name  = "DATA_EXECUTION_URL"
        value = "https://console.cloud.google.com/run/jobs/executions/details/${local.region}/{execution}/tasks?project=${local.project}"
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }
      startup_probe {
        tcp_socket {
          port = 8080
        }
        period_seconds    = 1
        failure_threshold = 30
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[1].image, client, client_version]
  }

  depends_on = [google_secret_manager_secret_iam_member.app_reads_sign_in, google_secret_manager_secret_version.app_sign_in,
  google_storage_bucket_iam_member.app_reads_store, google_artifact_registry_repository_iam_member.terraform_pulls]
}

# Anyone may reach the service: oauth2-proxy, its front container, decides
# who gets past it.
resource "google_cloud_run_v2_service_iam_member" "app_public" {
  count = var.serve_app ? 1 : 0

  name     = google_cloud_run_v2_service.app[0].name
  location = local.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# The deploy workflow updates the app container's image: only what
# `gcloud run deploy --container app --image` needs, on this one service.
resource "google_cloud_run_v2_service_iam_member" "deploy_app" {
  count = var.serve_app ? 1 : 0

  name     = google_cloud_run_v2_service.app[0].name
  location = local.region
  role     = "projects/${local.project}/roles/dataServiceDeployer"
  member   = data.google_service_account.deploy.member
}

resource "google_service_account_iam_member" "deploy_acts_as_app" {
  service_account_id = data.google_service_account.app.name
  role               = "roles/iam.serviceAccountUser"
  member             = data.google_service_account.deploy.member
}
