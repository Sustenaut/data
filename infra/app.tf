# The app at data.sustenaut.eu: the landing page at / and the power-auctions
# app at /power-auctions (src/soldera/app), one Streamlit server in the Cloud
# Run service soldera-app, with oauth2-proxy in front of it in the same
# service. The proxy signs people in with the team realm at auth.sustenaut.eu
# and lets in only those with the role data, as business-plan's planning app
# does with plan. The app reads the newest database the merge stage published
# in the store bucket, as soldera-app, which may read that bucket and the two
# sign-in secrets and nothing else. The deploy workflow builds the app's
# image and points the service's app container at it; shared-infra maps
# data.sustenaut.eu to the service.
#
# The service needs both secrets to hold a value, and both images to be in
# the registry, before it can start. So it waits for var.serve_app, which a
# pull request sets once a person has added the values and the deploy
# workflow has pushed the images (README, "Deploying the app").

locals {
  app_image   = "${local.region}-docker.pkg.dev/${local.project}/${google_artifact_registry_repository.soldera.repository_id}/app"
  proxy_image = "${local.region}-docker.pkg.dev/${local.project}/${google_artifact_registry_repository.soldera.repository_id}/oauth2-proxy:v7.15.5"
  site        = "data.sustenaut.eu"
}

# The service's account (shared-infra's).
data "google_service_account" "app" {
  project    = local.project
  account_id = "soldera-app"
}

resource "google_storage_bucket_iam_member" "app_reads_store" {
  bucket = google_storage_bucket.store.name
  role   = "roles/storage.objectViewer"
  member = data.google_service_account.app.member
}

# Only the secrets' names are here. A person adds their values (README), so
# no value is in git, the plan or the state.
resource "google_secret_manager_secret" "app_sign_in" {
  for_each = {
    "soldera-oidc-client-secret" = "Secret of sustenaut.eu's team client, which soldera-app's oauth2-proxy signs in with."
    "soldera-cookie-secret"      = "Key soldera-app's oauth2-proxy encrypts its session cookies with."
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

resource "google_secret_manager_secret_iam_member" "app_reads_sign_in" {
  for_each = google_secret_manager_secret.app_sign_in

  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = data.google_service_account.app.member
}

resource "google_cloud_run_v2_service" "app" {
  count = var.serve_app ? 1 : 0

  name                = "soldera-app"
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
    # release in soldera's registry, as Cloud Run does not pull from quay.io.
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
            secret  = google_secret_manager_secret.app_sign_in["soldera-oidc-client-secret"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "OAUTH2_PROXY_COOKIE_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.app_sign_in["soldera-cookie-secret"].secret_id
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
        name  = "SOLDERA_STORE"
        value = "gs://${google_storage_bucket.store.name}"
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

  depends_on = [google_secret_manager_secret_iam_member.app_reads_sign_in, google_storage_bucket_iam_member.app_reads_store]
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
  role     = "projects/${local.project}/roles/solderaServiceDeployer"
  member   = data.google_service_account.deploy.member
}

resource "google_service_account_iam_member" "deploy_acts_as_app" {
  service_account_id = data.google_service_account.app.name
  role               = "roles/iam.serviceAccountUser"
  member             = data.google_service_account.deploy.member
}
