Feature: The run log and the notes
  Every stage writes a run log row when it starts and another when it ends,
  with what it ran and what came of each item. Notes for readers of the data
  are written once, by the stage that finds them, to notes.parquet beside the
  stage's manifest, and keep the run that found them when a later run reuses
  the stored output.

  Background:
    Given the program under test is "soldera"
    And a scratch directory
    And a file "src/a.txt" holding "alpha"
    And a file "src/b.txt" holding "beta NOTE"
    And a file "pipeline.yaml" holding:
      """
      pipeline: demo
      plugins: [soldera.testing]
      stages:
        - {name: fetch, parser: testing-files@1.0.0, options: {dir: src}}
        - {name: upper, parser: testing-upper@1.0.0}
      """

  Scenario: Each stage logs a running row and a final row
    Given the environment sets "GITHUB_ACTIONS" to "false"
    And the environment sets "CLOUD_RUN_JOB" to ""
    When I run "soldera run pipeline.yaml --run-id r1"
    Then it succeeds
    And the run log has the rows:
      | run_id | stage_name | status    |
      | r1     | fetch      | running   |
      | r1     | fetch      | succeeded |
      | r1     | upper      | running   |
      | r1     | upper      | succeeded |
    And the run log's final row for "upper" in run "r1" has "parser_version" equal to "1.0.0"
    And the run log's final row for "upper" in run "r1" has "items_succeeded" equal to "2"
    And the run log's final row for "upper" in run "r1" has "notes_count" equal to "1"
    And the run log's final row for "upper" in run "r1" has "host" equal to "local"

  Scenario: A run started from GitHub Actions says which workflow run started it
    Given the environment sets "GITHUB_ACTIONS" to "true"
    And the environment sets "GITHUB_REPOSITORY" to "Sustenaut/soldera"
    And the environment sets "GITHUB_RUN_ID" to "123"
    And the environment sets "GITHUB_SHA" to "abc123"
    When I run "soldera run pipeline.yaml --run-id r1 --trigger manual"
    Then it succeeds
    And the run log's final row for "fetch" in run "r1" has "host" equal to "github-actions"
    And the run log's final row for "fetch" in run "r1" has "code_version" equal to "abc123"
    And the run log's final row for "fetch" in run "r1" has "trigger_context.github_run_url" equal to "https://github.com/Sustenaut/soldera/actions/runs/123"

  Scenario: A stage's notes are in notes.parquet with the run that found them
    When I run "soldera run pipeline.yaml --run-id r1"
    Then it succeeds
    And the notes of "upper" in run "r1" are:
      | run_id | item_key | kind         | severity | message             |
      | r1     | b.txt    | testing_note | warning  | b.txt holds a note  |

  Scenario: A reused output keeps its notes and the run that found them
    Given I ran "soldera run pipeline.yaml --run-id r1"
    When I run "soldera run pipeline.yaml --from upper --run-id r2"
    Then it succeeds
    And the notes of "upper" in run "r2" are:
      | run_id | item_key | kind         | severity | message             |
      | r1     | b.txt    | testing_note | warning  | b.txt holds a note  |
    And the note ids of "upper" are the same in runs "r1" and "r2"
