Feature: Where a deploy goes
  deploy app and deploy ingest pipeline ask bin/deploy-environments where a
  run deploys to: live from main, and an environment from a pull request
  labelled deploy-to-NAME, with its ingest code only where it has its own
  data. The environments are infra/environments.json's: staging has its own
  data, and branch reads staging's.

  Scenario Outline: A push to main deploys the app to live, and the pipeline to live and the environments with their own data
    Given a push to main, with the environments <environments>
    When the <part> deploy asks where it goes
    Then it goes to <where>

    Examples:
      | environments | part   | where         |
      | on           | app    | live          |
      | on           | ingest | live, staging |
      | off          | ingest | live          |

  Scenario Outline: A labelled pull request deploys to the environments its labels name
    Given a pull request labelled <labels>, just <action>
    When the <part> deploy asks where it goes
    Then it goes to <where>

    Examples:
      | labels                              | action                     | part   | where           |
      | deploy-to-branch                    | pushed to                  | app    | branch          |
      | deploy-to-branch                    | pushed to                  | ingest | nowhere         |
      | deploy-to-staging, deploy-to-branch | pushed to                  | app    | staging, branch |
      | deploy-to-staging, deploy-to-branch | pushed to                  | ingest | staging         |
      | deploy-to-staging, deploy-to-branch | given deploy-to-branch     | app    | branch          |
      | deploy-to-staging, bug              | given bug                  | app    | nowhere         |

  Scenario: No label reaches live, or an environment there is none of
    Given a pull request labelled deploy-to-live, deploy-to-nowhere, bug, just pushed to
    When the app deploy asks where it goes
    Then it goes to nowhere
