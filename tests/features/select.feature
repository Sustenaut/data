Feature: Stage 3, select: the monthly GO Global Results files, once each
  The select stage keeps the files that hold one auction's results each,
  named like EEX names them, whether they came loose or from an archive. A
  file stored twice is kept once, from the archive. Any other spreadsheet or
  csv is left out with a note, so a new kind of file is seen, not dropped
  quietly. Archives and PDFs are passed over.

  Background:
    Given the program under test is "soldera"
    And a scratch directory
    And the repository's pipeline "eex-french-power-auctions"
    And the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20261118_July_2026_21_GLOBAL_Results_detailedresults.xlsx">xlsx</a>
      <a href="/fileadmin/GO/results.zip">zip</a>
      <a href="/fileadmin/GO/FAQ.pdf">pdf</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20261118_July_2026_21_GLOBAL_Results_detailedresults.xlsx" with 200 and:
      """
      july 21
      """
    And the "eex" service answers "GET /fileadmin/GO/FAQ.pdf" with 200 and:
      """
      questions
      """

  Scenario: Each results file is kept once, and anything else is noted
    Given the "eex" service answers "GET /fileadmin/GO/results.zip" with a zip holding:
      | path                                                          | content  |
      | 2026/20261118_July_2026_21_GLOBAL_Results_detailedresults.xlsx | july 21  |
      | 2026/20261021_July_2026_19_GLOBAL_Results_detailedresults.xlsx | july 19  |
      | 2019/20190918_April_2019_global_results.xlsx                   | april    |
      | 2020/20210120_October_2020_Global_Results.csv                  | october  |
      | 2022/20230315_November_2022_47_2_GLOBAL_Results_detailedresults.xlsx | november |
      | 2020/Resultats_encheres_20.xlsx                                | summary  |
    When I run "soldera run pipeline.yaml"
    Then it succeeds
    And it prints "select: eex-go-global-results-select@1.0.0 succeeded: 7 items, 7 built, 0 cached, 0 failed"
    And the published outputs of "select" are:
      | item                                                                        | name                                                           | holds    |
      | results.zip/2026/20261118_July_2026_21_GLOBAL_Results_detailedresults.xlsx  | 20261118_July_2026_21_GLOBAL_Results_detailedresults.xlsx      | july 21  |
      | results.zip/2026/20261021_July_2026_19_GLOBAL_Results_detailedresults.xlsx  | 20261021_July_2026_19_GLOBAL_Results_detailedresults.xlsx      | july 19  |
      | results.zip/2019/20190918_April_2019_global_results.xlsx                    | 20190918_April_2019_global_results.xlsx                        | april    |
      | results.zip/2020/20210120_October_2020_Global_Results.csv                   | 20210120_October_2020_Global_Results.csv                       | october  |
      | results.zip/2022/20230315_November_2022_47_2_GLOBAL_Results_detailedresults.xlsx | 20230315_November_2022_47_2_GLOBAL_Results_detailedresults.xlsx | november |
    And the notes of "select" in the latest run are:
      | kind             | severity | subject                                                   |
      | file_duplicate   | info     | 20261118_July_2026_21_GLOBAL_Results_detailedresults.xlsx |
      | file_not_results | info     | results.zip/2020/Resultats_encheres_20.xlsx               |

  Scenario: Files that have not changed are not selected again
    Given the "eex" service answers "GET /fileadmin/GO/results.zip" with a zip holding:
      | path                                          | content |
      | 2019/20190918_April_2019_global_results.xlsx  | april   |
    And I ran "soldera run pipeline.yaml"
    When I run "soldera run pipeline.yaml"
    Then it succeeds
    And it prints "select: eex-go-global-results-select@1.0.0 succeeded: 2 items, 0 built, 2 cached, 0 failed"

  Scenario: Two different files that would be kept under one name fail the stage
    Given the "eex" service answers "GET /fileadmin/GO/results.zip" with a zip holding:
      | path                                         | content       |
      | a/20190918_April_2019_global_results.xlsx    | april         |
      | b/20190918_April_2019_global_results.xlsx    | april, again  |
    When I run "soldera run pipeline.yaml"
    Then the exit code is 1
    And stderr mentions "would both be kept as 20190918_April_2019_global_results.xlsx"
