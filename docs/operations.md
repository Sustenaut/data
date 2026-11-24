# Operations

You keep data.sustenaut.eu and its weekly ingest running, debug production,
and own the infrastructure in `infra/`. **When something is failing now, go
to the [runbook](runbook.md).**

Everything runs in the Google Cloud project `sustenaut` (region
europe-north1), from Terraform in `infra/` and the workflows in
`.github/workflows/`. Nothing is created by hand, except the one-time steps
under [Setting it up](#setting-it-up).

## What runs where

The workflows deploy to these. The soldera-* resources (the old Terraform
state prefix `soldera`) are left over from before the rename, and are being
deleted.

| Resource | What it is for |
| --- | --- |
| `data-app` Cloud Run service | data.sustenaut.eu: oauth2-proxy in front, signing people in at auth.sustenaut.eu and letting in those with the role `data`, and the app behind it |
| `data-ingest` Cloud Run job | the ingest pipeline: one task, never retried, an hour at most |
| `data-ingest-weekly` | Cloud Scheduler (europe-west1, which has a scheduler; europe-north1 has none): Thursdays 07:00 Paris time, the morning after EEX's auction day |
| `sustenaut-data-store` bucket | the store, mounted in the job at `/store` and read by the app over its API; versioned, replaced objects kept 30 days |
| `sustenaut-data-store-logs` bucket | the store's access logs, kept a year |
| `data_ingest` BigQuery dataset | the run log `pipeline_stage_runs`, the notes table `stage_notes`, and the views `runs`, `stage_runs_latest`, `failed_items` (`infra/views.tf`, SQL in `infra/sql/`) |
| `data` Artifact Registry repository | the ingest and app images (the ten newest of each kept), and a copy of oauth2-proxy |
| `data-ingest@`, `data-app@`, `data-scheduler@` | the accounts the job, the service and the scheduler run as |
| `data-deploy@` | what this repository's workflows act as, through the custom roles `dataJobDeployer` (on the job only) and `dataServiceDeployer` (on the service only) |
| `data-oidc-client-secret`, `data-cookie-secret` | oauth2-proxy's secrets, from the Bitwarden Secrets Manager project `Sustenaut` |

shared-infra owns what this stack may not make: the Workload Identity pool,
the accounts and custom roles above, the Terraform account
`terraform-data`, and the domain mapping of data.sustenaut.eu.

## Workflows

| Workflow | When | What |
| --- | --- | --- |
| **ci** (`pr.yml`, `main.yml`) | each pull request and push to main | pubrules' checks, the suite, Terraform plan, SonarQube Cloud |
| **terraform** | pushes to main that touch `infra/`, or by hand | applies `infra/` as `terraform-data` (pubhost's workflow, secrets through pubsec). An apply that destroys or replaces a resource needs the label `terraform-destroy` on its pull request |
| **deploy ingest pipeline** | pushes to main that touch the pipeline | builds and checks the ingest image, points the job at it, and runs the job with `--from auto`, which does nothing when every stage is current |
| **deploy app** | pushes to main that touch the app, and pull requests labelled `deploy-to-NAME` | builds the app image, checks it serves both pages, and points an environment's service's app container at it: live from main, NAME from a pull request (below, "Environments") |
| **labels** | pushes to main that touch `infra/environments.json` | makes a label `deploy-to-NAME` for each environment |
| **run ingest pipeline** | by hand (Actions, Run workflow) | runs the job now with `from`, `to` and `force`, and fails when it does |
| **debug markers** | pull requests, main, and each closed issue | fails while temporary code marked `DEBUG(#N)` names a closed issue |

Repository variables gate them: `TERRAFORM_CI`, `DEPLOY_CI` and
`APP_SERVICE` must be `on`, and `ENVIRONMENTS` too for pull requests'
deploys.

## Environments

The app runs live and in each environment `infra/environments.json` names,
each its own Cloud Run service at its own address:

| Environment | Address | Service | Deployed by |
| --- | --- | --- | --- |
| live | data.sustenaut.eu | `data-app` | each push to main, as `data-deploy` |
| staging | data-staging.sustenaut.eu | `data-app-staging` | a pull request with the label `deploy-to-staging` |
| branch | data-branch.sustenaut.eu | `data-app-branch` | a pull request with the label `deploy-to-branch` |

Adding the label deploys the pull request's head, and each push to it
deploys again while the label is on. Only someone who can label a pull request
can deploy one, and pull requests from forks never get credentials. Pull
requests deploy as `data-preview`, through shared-infra's pool
`github-preview`, which admits only this repository's pull request runs. That
account can deploy no live service, and pushes its images as `app-preview`.
Every environment signs people in at auth.sustenaut.eu with the role `data`,
and reads the same store, so staging is also the way in while live is down
(runbook, "The site is down").

To add an environment NAME:

1. Here, add NAME to `infra/environments.json`. The apply makes its service
   and the **labels** workflow its label.
2. In shared-infra, add the site `data-NAME` to `pubrules.json`, with
   `"kind": "cloud-run"` and `"service": "data-app-NAME"`. Its apply makes the
   DNS records and the domain mapping, and Google issues the certificate
   within the hour.
3. Register its address on the team client: `register-app.py --redirect
   https://data-NAME.sustenaut.eu/oauth2/callback --logout
   https://data-NAME.sustenaut.eu/ --role data` (step 4 below).

## Coding conventions, and how they are enforced

| Convention | Enforced by |
| --- | --- |
| All infrastructure is Terraform in `infra/`, applied from CI, never clicked together | review. The terraform workflow's plan shows any drift |
| Third-party actions and images are pinned to a commit or digest, with the version in a comment | review |
| Secrets live in Bitwarden (project `Sustenaut`) and reach Terraform as write-only values through pubsec. None is in the repository or a workflow | review. `with-secrets.json` declares which secrets exist |
| The deploy account can do only what deploying needs, on its own resources | custom roles bound on the job and the service alone |
| Pull requests are small and do one thing. CI must pass, `ci / passed` | main's ruleset |
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
  accounts are in `infra/`. Grants for `terraform-data` are in
  shared-infra's `infra/terraform-ci.tf`.

## Setting it up

These were done once, in this order, and are only needed again for a new
project or a rebuild:

1. shared-infra adds this repository to `github_repositories` (the pool's
   `github` provider then admits main's runs) and to `terraform_stacks`
   (account `terraform-data`, owner id 343693649, repository id
   1467291589), and makes the accounts and custom roles above.
2. Make the GitHub environment `terraform`, limited to main, with the secret
   `BWS_ACCESS_TOKEN` (a read-only Bitwarden machine account's token), and
   set `TERRAFORM_CI=on`.
3. Put the secrets' values in Bitwarden under their names: the team client's
   secret as `data-oidc-client-secret`, and a cookie key as
   `data-cookie-secret` (`openssl rand -base64 32 | tr -d '\n' | tr --
   '+/' '-_'`).
4. Register the site on the team client with Sustenaut/auth's
   `register-app.py --redirect https://data.sustenaut.eu/oauth2/callback
   --logout https://data.sustenaut.eu/ --role data`.
5. The first apply makes everything but the registry's grants and the app's
   service. shared-infra then sets `data_registry_made = true`, which lets
   this stack set IAM on its registry, and a pull request here sets
   `registry_granted = true` (`infra/variables.tf`).
6. Set `DEPLOY_CI=on`, run **deploy app** and **deploy ingest pipeline**
   once (the second builds the store from nothing), set `serve_app = true`,
   then `APP_SERVICE=on`.
7. shared-infra maps data.sustenaut.eu to the service. Its Terraform account
   must be an Owner of sustenaut.eu in Search Console (Settings, Users and
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
realm), GitHub Actions on GitHub's hosted runners (the repository is public), and SonarQube Cloud.

The code that runs is described in [Developing the app](app.md) and
[Developing the ingest pipeline](ingest.md).
