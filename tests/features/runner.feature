Feature: Running a pipeline's stages
  `soldera run` runs a pipeline's stages in order. Each stage is the same
  runner with one pinned, versioned parser, and keeps its outputs in the
  store, so a later run can start at any stage and reuse what is stored.
  These scenarios use the testing parsers: testing-files reads a directory,
  testing-upper upper-cases each file (a file holding FAIL fails, one holding
  NOTE gets a note; version 2.0.0 also adds "!"), and testing-join joins
  them.

  Background:
    Given the program under test is "soldera"
    And a scratch directory
    And a file "src/a.txt" holding "alpha"
    And a file "src/b.txt" holding "beta"
    And a file "pipeline.yaml" holding:
      """
      pipeline: demo
      plugins: [soldera.testing]
      stages:
        - {name: fetch, parser: testing-files@1.0.0, options: {dir: src}}
        - {name: upper, parser: testing-upper@1.0.0}
        - {name: join, parser: testing-join@1.0.0}
      """

  Scenario: A first run builds every stage in order
    When I run "soldera run pipeline.yaml --run-id r1"
    Then it succeeds
    And it prints "upper: testing-upper@1.0.0 succeeded: 2 items, 2 built, 0 cached, 0 failed"
    And the published output of "join" holds:
      """
      ALPHA
      BETA
      """

  Scenario: A run from a later stage reuses what is stored
    Given I ran "soldera run pipeline.yaml --run-id r1"
    When I run "soldera run pipeline.yaml --from upper --run-id r2"
    Then it succeeds
    And it does not print "fetch:"
    And it prints "upper: testing-upper@1.0.0 succeeded: 2 items, 0 built, 2 cached, 0 failed"
    And it prints "join: testing-join@1.0.0 succeeded: 1 items, 0 built, 1 cached, 0 failed"

  Scenario: --force builds every item again
    Given I ran "soldera run pipeline.yaml --run-id r1"
    When I run "soldera run pipeline.yaml --from upper --force --run-id r2"
    Then it succeeds
    And it prints "upper: testing-upper@1.0.0 succeeded: 2 items, 2 built, 0 cached, 0 failed"

  Scenario: One failed item does not stop the others
    Given a file "src/c.txt" holding "FAIL here"
    When I run "soldera run pipeline.yaml --run-id r1"
    Then it fails
    And it prints "upper: testing-upper@1.0.0 partial: 3 items, 2 built, 0 cached, 1 failed"
    And stderr mentions "upper: c.txt failed: ValueError: c.txt asks to fail"
    And the published output of "join" holds:
      """
      ALPHA
      BETA
      """
    And the run log's final row for "upper" in run "r1" has "status" equal to "partial"
    And the run log's final row for "upper" in run "r1" has "items_failed" equal to "1"
    And the run log's final row for "upper" in run "r1" has "items.2.error_message" equal to "c.txt asks to fail"

  Scenario: A bumped parser version runs from its stage and keeps the old outputs
    Given I ran "soldera run pipeline.yaml --run-id r1"
    And the file "pipeline.yaml" now pins "testing-upper@2.0.0"
    When I run "soldera run pipeline.yaml --from auto --run-id r2"
    Then it succeeds
    And it does not print "fetch:"
    And it prints "upper: testing-upper@2.0.0 succeeded: 2 items, 2 built, 0 cached, 0 failed"
    And the published output of "join" holds:
      """
      ALPHA!
      BETA!
      """
    And the stored outputs of "testing-upper@1.0.0" are still there

  Scenario: Reverting a version pin reuses the outputs that version stored
    Given I ran "soldera run pipeline.yaml --run-id r1"
    And the file "pipeline.yaml" now pins "testing-upper@2.0.0"
    And I ran "soldera run pipeline.yaml --from auto --run-id r2"
    And the file "pipeline.yaml" now pins "testing-upper@1.0.0"
    When I run "soldera run pipeline.yaml --from upper --run-id r3"
    Then it succeeds
    And it prints "upper: testing-upper@1.0.0 succeeded: 2 items, 0 built, 2 cached, 0 failed"
    And the published output of "join" holds:
      """
      ALPHA
      BETA
      """

  Scenario: --from auto runs nothing when every stage is up to date
    Given I ran "soldera run pipeline.yaml --run-id r1"
    When I run "soldera run pipeline.yaml --from auto"
    Then it succeeds
    And it prints "demo: every stage is up to date; nothing to run"

  Scenario: A stage cannot start without the stored output of the one before it
    When I run "soldera run pipeline.yaml --from upper"
    Then the exit code is 2
    And stderr mentions "no stored output of stage fetch (testing-files@1.0.0): run from fetch or earlier first"

  Scenario: A pin to a parser version that does not exist is refused
    Given the file "pipeline.yaml" now pins "testing-upper@9.9.9"
    When I run "soldera run pipeline.yaml"
    Then the exit code is 2
    And stderr mentions "testing-upper has no version 9.9.9; it has 1.0.0, 2.0.0"
