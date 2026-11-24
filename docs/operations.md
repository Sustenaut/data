# Operations

You keep data.sustenaut.eu and its weekly ingest running, debug production,
and own the infrastructure in [`infra/`](../infra/). **When something is failing now, go
to the [runbook](runbook.md).**

Everything runs in the Google Cloud project `sustenaut` (region
europe-north1), from Terraform in `infra/` and the workflows in
[`.github/workflows/`](../.github/workflows/). Nothing is created by hand, except the one-time steps
under [Setting it up](#setting-it-up).

## What runs where

The workflows deploy to these. The soldera-* resources (the old Terraform
state prefix `soldera`) are left over from before the rename, and are being
deleted.

| Resource | What it is for |
| --- | --- |
| [`data-app`](https://console.cloud.google.com/run/detail/europe-north1/data-app?project=sustenaut) Cloud Run service | data.sustenaut.eu: oauth2-proxy in front, signing people in at auth.sustenaut.eu and letting in those with the role `data`, and the app behind it |
| [`data-ingest`](https://console.cloud.google.com/run/jobs/details/europe-north1/data-ingest/executions?project=sustenaut) Cloud Run job | the ingest pipeline: one task, never retried, an hour at most |
| [`data-ingest-weekly`](https://console.cloud.google.com/cloudscheduler?project=sustenaut) | Cloud Scheduler (europe-west1, which has a scheduler; europe-north1 has none): Thursdays 07:00 Paris time, the morning after EEX's auction day |
| [`sustenaut-data-store`](https://console.cloud.google.com/storage/browser/sustenaut-data-store?project=sustenaut) bucket | the store, mounted in the job at `/store` and read by the app over its API; versioned, replaced objects kept 30 days |
| [`sustenaut-data-store-logs`](https://console.cloud.google.com/storage/browser/sustenaut-data-store-logs?project=sustenaut) bucket | the store's access logs, kept a year |
| [`data_ingest`](https://console.cloud.google.com/bigquery?project=sustenaut&ws=!1m4!1m3!3m2!1ssustenaut!2sdata_ingest) BigQuery dataset | the run log `pipeline_stage_runs`, the notes table `stage_notes`, and the views `runs`, `stage_runs_latest`, `failed_items` ([`infra/views.tf`](../infra/views.tf), SQL in [`infra/sql/`](../infra/sql/)) |
| [`data`](https://console.cloud.google.com/artifacts/docker/sustenaut/europe-north1/data?project=sustenaut) Artifact Registry repository | the ingest and app images (the ten newest of each kept), and a copy of oauth2-proxy |
| `data-ingest@`, `data-app@`, `data-scheduler@` ([service accounts](https://console.cloud.google.com/iam-admin/serviceaccounts?project=sustenaut)) | the accounts the job, the service and the scheduler run as |
| `data-deploy@` | what this repository's workflows act as, through the custom roles `dataJobDeployer` (on the job only) and `dataServiceDeployer` (on the service only) |
| `data-oidc-client-secret`, `data-cookie-secret` ([Secret Manager](https://console.cloud.google.com/security/secret-manager?project=sustenaut)) | oauth2-proxy's secrets, from the Bitwarden Secrets Manager project `Sustenaut` |

shared-infra owns what this stack may not make: the Workload Identity pools
([`infra/deploy.tf`](https://github.com/Sustenaut/shared-infra/blob/main/infra/deploy.tf)), the accounts and custom roles
above and the Terraform account `terraform-data` (the data stack's entry in
`terraform_stacks`, [`infra/variables.tf`](https://github.com/Sustenaut/shared-infra/blob/main/infra/variables.tf)), and the
domain mappings and DNS of every address (its sites in
[`pubrules.json`](https://github.com/Sustenaut/shared-infra/blob/main/pubrules.json)).

## Workflows

| Workflow | When | What |
| --- | --- | --- |
| [**ci**](https://github.com/Sustenaut/data/actions/workflows/main.yml) ([`pr.yml`](../.github/workflows/pr.yml), [`main.yml`](../.github/workflows/main.yml)) | each pull request and push to main | pubrules' checks, the suite, Terraform plan, SonarQube Cloud |
| [**terraform**](https://github.com/Sustenaut/data/actions/workflows/terraform.yml) ([`terraform.yml`](../.github/workflows/terraform.yml)) | pushes to main that touch [`infra/`](../infra/), or by hand | applies `infra/` as `terraform-data` (pubhost's workflow, secrets through pubsec). An apply that destroys or replaces a resource needs the label [`terraform-destroy`](https://github.com/Sustenaut/data/labels) on its pull request |
| [**deploy ingest pipeline**](https://github.com/Sustenaut/data/actions/workflows/deploy-ingest.yml) ([`deploy-ingest.yml`](../.github/workflows/deploy-ingest.yml)) | pushes to main that touch the pipeline, and pull requests labelled `deploy-to-NAME` | builds and checks the ingest image, points a job at it, and runs it with `--from auto`, which does nothing when every stage is current: from main, live's job and each environment's with its own data; from a pull request, the job of NAME, if it has its own data (below, "Environments") |
| [**deploy app**](https://github.com/Sustenaut/data/actions/workflows/deploy-app.yml) ([`deploy-app.yml`](../.github/workflows/deploy-app.yml)) | pushes to main that touch the app, and pull requests labelled `deploy-to-NAME` | builds the app image, checks it serves both pages, and points a service's app container at it: live's from main, NAME's from a pull request (below, "Environments") |
| [**labels**](https://github.com/Sustenaut/data/actions/workflows/labels.yml) ([`labels.yml`](../.github/workflows/labels.yml)) | pushes to main that touch [`infra/environments.json`](../infra/environments.json) | makes a label `deploy-to-NAME` for each environment |
| [**run ingest pipeline**](https://github.com/Sustenaut/data/actions/workflows/run-ingest.yml) ([`run-ingest.yml`](../.github/workflows/run-ingest.yml)) | by hand (its Actions page, **Run workflow**) | runs the job now with `from`, `to` and `force`, and fails when it does |
| [**debug markers**](https://github.com/Sustenaut/data/actions/workflows/debug-markers.yml) ([`debug-markers.yml`](../.github/workflows/debug-markers.yml)) | pull requests, main, and each closed issue | fails while temporary code marked `DEBUG(#N)` names a closed issue |

[Repository variables](https://github.com/Sustenaut/data/settings/variables/actions) gate them: `TERRAFORM_CI`, `DEPLOY_CI` and
`APP_SERVICE` must be `on`, and `ENVIRONMENTS` too for pull requests'
deploys.

## Environments

The app runs live and in each environment [`infra/environments.json`](../infra/environments.json) names,
each its own Cloud Run service at its own address:

| Environment | Address | Service | Its data | Deployed by |
| --- | --- | --- | --- | --- |
| live | <https://data.sustenaut.eu/> | `data-app` | `gs://sustenaut-data-store`, `data_ingest`, job `data-ingest` (weekly) | each push to main, as `data-deploy` |
| staging | <https://data-staging.sustenaut.eu/> | `data-app-staging` | its own: `gs://sustenaut-data-store-staging`, `data_ingest_staging`, job `data-ingest-staging` | a pull request with the label `deploy-to-staging` |
| branch | <https://data-branch.sustenaut.eu/> | `data-app-branch` | staging's, read only | a pull request with the label `deploy-to-branch` |

Adding the label (the [labels](https://github.com/Sustenaut/data/labels) page lists them) deploys the pull request's head, and each push to it
deploys again while the label is on: **deploy app** its app, and **deploy
ingest pipeline** its pipeline, where the environment has its own data.
[`bin/deploy-environments`](../bin/deploy-environments) answers both where a run goes, so they agree.
Staging (`"data": "own"`) gets the pull request's ingest image in its own
job, which then runs with `--from auto`: that is where pipeline changes are
tried. Its job has no schedule, and
runs as `data-ingest-staging`, which can write only staging's store and run
log. Branch (`"data": "staging"`) is for the front end only: it reads
staging's store and runs nothing ([`infra/environments.tf`](../infra/environments.tf)). So that branch
never shows a stale pipeline's data, every push to main that changes the
pipeline deploys it to staging's job as well as live's, and runs both
(**deploy ingest pipeline**). Staging then runs main's pipeline again until a
pull request is next deployed there.

Only someone who can label a pull request can deploy one, and pull requests
from forks never get credentials. Pull requests deploy as `data-preview`,
through shared-infra's pool `github-preview` ([`infra/deploy.tf`](https://github.com/Sustenaut/shared-infra/blob/main/infra/deploy.tf)), which admits only this
repository's pull request runs. That account can deploy no live service or
job, and pushes its images as `app-preview` and `ingest-preview`. Every
environment signs people in at auth.sustenaut.eu with the role `data`, so
staging is also the way in while live is down (runbook, "The site is down").

To add an environment NAME:

1. In shared-infra, add the account `data-ingest-NAME` to the data stack's
   `managed_accounts` in [`infra/variables.tf`](https://github.com/Sustenaut/shared-infra/blob/main/infra/variables.tf), if NAME will have `"data": "own"`.
2. Here, add NAME to `infra/environments.json`, with `"data": "own"` for its
   own data, or `"data": "OTHER"` to read the environment OTHER's. The apply makes its service (and its
   store, run log and job), and the **labels** workflow its label.
3. In shared-infra, add the site `data-NAME` to [`pubrules.json`](https://github.com/Sustenaut/shared-infra/blob/main/pubrules.json), with
   `"kind": "cloud-run"` and `"service": "data-app-NAME"`. Its apply makes the
   DNS records and the domain mapping, and Google issues the certificate
   within the hour.
4. Register its address on the team client, as in step 4 below, with
   `data-NAME.sustenaut.eu` for `data.sustenaut.eu`.

## Coding conventions, and how they are enforced

| Convention | Enforced by |
| --- | --- |
| All infrastructure is Terraform in [`infra/`](../infra/), applied from CI, never clicked together | review. The terraform workflow's plan shows any drift |
| Third-party actions and images are pinned to a commit or digest, with the version in a comment | review |
| Secrets live in Bitwarden (project `Sustenaut`) and reach Terraform as write-only values through pubsec. None is in the repository or a workflow | review. [`with-secrets.json`](../with-secrets.json) declares which secrets exist |
| The deploy account can do only what deploying needs, on its own resources | custom roles bound on the job and the service alone |
| Pull requests are small and do one thing. CI must pass, `ci / passed` | main's [ruleset](https://github.com/Sustenaut/data/settings/rules) |
| Temporary code carries `DEBUG(#N)` with an open issue | the **debug markers** workflow |

## Debugging production

Start with the [runbook](runbook.md). In short:

- **A failed ingest run**: the run log's views in BigQuery say which stage
  and which items failed, and why. The job's logs are in Logs Explorer:
  `resource.type="cloud_run_job" resource.labels.job_name="data-ingest"`.
- **The site is down or slow**: first tell the service from the domain with
  the service's own address (runbook, "The site is down"). Then the service's logs and revisions, in the
  Cloud Run console for `data-app`, or in Logs Explorer:
  `resource.type="cloud_run_revision" resource.labels.service_name="data-app"`.
- **Sign-in fails**: oauth2-proxy's logs in the same service. Check the
  secrets' latest versions, and that the person has the `data` role at
  auth.sustenaut.eu.
- **A deploy or apply is denied (403)**: grants for the job's and app's
  accounts are in [`infra/`](../infra/). Grants for `terraform-data` are in
  shared-infra's [`infra/terraform-ci.tf`](https://github.com/Sustenaut/shared-infra/blob/main/infra/terraform-ci.tf).

## Setting it up

These were done once, in this order, and are only needed again for a new
project or a rebuild:

1. shared-infra adds this repository to `github_repositories`
   ([`infra/variables.tf`](https://github.com/Sustenaut/shared-infra/blob/main/infra/variables.tf)) (the pool's
   `github` provider then admits main's runs) and to `terraform_stacks`
   (account `terraform-data`, owner id 343693649, repository id
   1467291589), and makes the accounts and custom roles above.
2. Make the [GitHub environment](https://github.com/Sustenaut/data/settings/environments) `terraform`, limited to main, with the secret
   `BWS_ACCESS_TOKEN` (a read-only Bitwarden machine account's token), and
   set `TERRAFORM_CI=on`.
3. Put the secrets' values in Bitwarden under their names: the team client's
   secret as `data-oidc-client-secret`, and a cookie key as
   `data-cookie-secret` (`openssl rand -base64 32 | tr -d '\n' | tr --
   '+/' '-_'`).
4. Register the site on the team client with Sustenaut/auth's
   [`register-app.py`](https://github.com/Sustenaut/auth/blob/main/register-app.py). It runs on the k3s server, which keeps the client, so
   from a clone of Sustenaut/auth:

   ```sh
   ssh root@sustenaut "python3 -I - --state-dir /root/.config/sustenaut-auth/team-sustenaut.eu \
     --auth https://auth.sustenaut.eu/realms/team --domain sustenaut.eu --name 'sustenaut.eu team sites' \
     --redirect https://data.sustenaut.eu/oauth2/callback --logout https://data.sustenaut.eu/ --role data" < register-app.py
   ```

   It prints `"status": "ok"`. It needs no certificate: it never opens the
   site.
5. The first apply makes everything but the registry's grants and the app's
   service. shared-infra then sets `data_registry_made = true`
   ([`infra/variables.tf`](https://github.com/Sustenaut/shared-infra/blob/main/infra/variables.tf)), which lets
   this stack set IAM on its registry, and a pull request here sets
   `registry_granted = true` ([`infra/variables.tf`](../infra/variables.tf)).
6. Set `DEPLOY_CI=on`, run **deploy app** and **deploy ingest pipeline**
   once (the second builds the store from nothing), set `serve_app = true`,
   then `APP_SERVICE=on`.
7. shared-infra maps data.sustenaut.eu to the service. Its Terraform account
   must be an Owner of sustenaut.eu in [Search Console](https://search.google.com/search-console) (Settings, Users and
   permissions).
8. For the environments: shared-infra makes the pool `github-preview` and the
   account `data-preview`. A pull request here then sets
   `environments_ready = true`, and once it has applied, set
   `ENVIRONMENTS=on`. shared-infra maps each environment's address, and each is
   registered on the team client (above, "Environments").

On a laptop, `./with-secrets terraform -chdir=infra plan` plans with the
secrets, as CI does.

## Dependencies

| Tool | Why |
| --- | --- |
| [Terraform](https://developer.hashicorp.com/terraform) | the infrastructure as code, planned on every pull request |
| [pubhost](https://github.com/Sustenaut/pubhost) | Sustenaut's Terraform workflow and image build action, shared by every service |
| [pubsec](https://github.com/Sustenaut/pubsec) | hands Bitwarden secrets to Terraform without writing them anywhere |
| [pubrules](https://github.com/Sustenaut/pubrules) | the CI workflows and the files every repository keeps in step |
| [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/) | the team sign-in in front of the app, so the app has no auth code |
| [Bitwarden Secrets Manager](https://bitwarden.com/products/secrets-manager/) | where the secrets' values live |

Services: Google Cloud (Cloud Run, Cloud Scheduler, Cloud Storage, BigQuery,
Artifact Registry, Secret Manager), auth.sustenaut.eu (Keycloak, the team
realm), GitHub Actions on GitHub's hosted runners (the repository is public), and [SonarQube Cloud](https://sonarcloud.io/project/overview?id=Sustenaut_data).

The code that runs is described in [Developing the app](app.md) and
[Developing the ingest pipeline](ingest.md).
