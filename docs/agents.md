# Working as an agent

You are an AI agent working in this repository. Your job is to help the
people who own it do theirs. You don't decide for them: you make sure every
change meets the rules and needs of each role below, and when a choice
belongs to one of them, you ask.

**First read [AGENTS.md](../AGENTS.md).** It holds the rules every Sustenaut
repository shares: pull requests, branches, and the like. pubrules writes it,
so don't edit it here. This page adds what is particular to this repository.

## Who you work for

| Role | Owns | Ask them about |
| --- | --- | --- |
| [App user](using.md) | nothing in the code | whether a page answers their question, and what words they use for things |
| [App developer](app.md) | [`src/app/`](../src/app/), [`.streamlit/`](../.streamlit/) | what a chart should show, how people explore the data, colours and layout |
| [Ingest developer](ingest.md) | [`src/ingest/`](../src/ingest/), [`pipelines/`](../pipelines/), [`corrections/`](../corrections/) | what the data means, whether a number is right, EEX's mistakes, parser versions |
| [Operations](operations.md) | [`infra/`](../infra/), [`.github/workflows/`](../.github/workflows/), the cloud | anything that creates, changes or deletes a cloud resource, secrets, costs, access |

Read the page of each role a change touches before you start, and follow its
conventions table.

## How to work

- **Ask before you build** when a request can be read two ways, changes what
  the data means, or touches another role's area. One good question saves a
  rewrite. Offer a recommendation with the question.
- **Small, separate pieces.** Make each change compact, readable and
  logical, so it can be tested and debugged on its own. Use one pull request
  per step. Keep app, pipeline and infrastructure changes apart where you can.
- **Tests first-class.** Every behaviour gets a Gherkin scenario with a
  **When**, run against [`bin/data`](../bin/data) or the app as a person would use them.
  Show a failing test before a fix where you can.
- **Fail loudly.** Never hide an error, swallow a failed item, or publish
  partial data.
- **Bump a parser's version** whenever its output changes. Correct EEX's
  mistakes in [`corrections/`](../corrections/), never in code.
- **Mark temporary code** `DEBUG(#N)` with an open issue that says when it
  goes. CI fails once that issue closes.
- **Never edit what pubrules manages** ([`AGENTS.md`](../AGENTS.md), the CI workflows,
  [`tests/requirements-pubrules.txt`](../tests/requirements-pubrules.txt)). Change [`pubrules.json`](../pubrules.json) and run
  `./pubrules sync`.
- **Say what you verified**, with the command or link, and what you didn't.
- **Irreversible steps wait for a person**: deleting cloud resources or
  data, anything in production that cannot be rolled back, and messages
  outside the team.

Before you push:

```sh
make functional              # the whole suite, with coverage
./pubrules sync --check      # managed files in step, Gherkin rules
bin/check-debug-markers --list
```

## The Sustenaut ecosystem

Sustenaut's repositories share tools, all under
[github.com/Sustenaut](https://github.com/Sustenaut):

| Tool | What it gives this repository |
| --- | --- |
| [pubrules](https://github.com/Sustenaut/pubrules) | the shared CI workflows, the files every repository keeps in step ([`AGENTS.md`](../AGENTS.md) among them), the rules `pubrules sync --check` enforces, and [`pubrules.json`](../pubrules.json), which declares this repository a `service` |
| [pubtest](https://github.com/Sustenaut/pubtest) | the Gherkin steps and fake services every suite runs on. Its [GRAMMAR.md](https://github.com/Sustenaut/pubtest/blob/main/GRAMMAR.md) lists the steps you can use before writing new ones |
| [pubhost](https://github.com/Sustenaut/pubhost) | the Terraform workflow and the image build action |
| [pubsec](https://github.com/Sustenaut/pubsec) | secrets from Bitwarden, handed to a command without being written anywhere (`./pubsec`, `./with-secrets`) |
| [pubdeploy](https://github.com/Sustenaut/pubdeploy) and [pubrel](https://github.com/Sustenaut/pubrel) | deploy checks and releases, for repositories that use them (this one deploys through its own workflows) |
| [theme](https://github.com/Sustenaut/theme) | the design tokens and fonts every site uses. The app copies its colours into [`.streamlit/config.toml`](../.streamlit/config.toml) |
| shared-infra | the Google Cloud project, the Workload Identity pool, the service accounts and roles this stack may not make, and DNS |
| auth.sustenaut.eu | the team sign-in. A site lets in people with its role (`data` here) |

When a rule seems to come from nowhere, look in pubrules first. When you
need a step, a workflow or a fake service, look in pubtest and pubhost
before you write one.
