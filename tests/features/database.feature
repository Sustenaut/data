Feature: Stage 5, database: every parsed file into the app's DuckDB
  The database stage puts every auction_results file into one DuckDB file, the
  one data.sustenaut.eu/go-auctions reads: the rows, every note the
  stages before it wrote (copied, so they say the same everywhere), a row of
  build information, and views with each auction's totals. It notes what
  only the whole series shows: auction numbers skipped or used twice, and
  production months with no auction. Two rows for the same auction, region
  and technology fail the run.

  Background:
    Given the program under test is "data"
    And a scratch directory
    And the repository's pipeline "eex-french-go-auctions"

  Scenario: Every file's rows go into one database, with views of each auction
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv">file</a>
      <a href="/fileadmin/GO/20210922_June_2021_28_Global_Results_detailedresults.csv">file</a>
      <a href="/fileadmin/GO/Resultats_encheres_20.xlsx">file</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv" with a full results csv for 28 participants, where:
      | region   | technology | offered | sold | price | winners |
      | Bretagne | Solaire    | 1000    | 600  | 1.5   | 3       |
    And the "eex" service answers "GET /fileadmin/GO/20210922_June_2021_28_Global_Results_detailedresults.csv" with a full results csv for 30 participants, where:
      | region | technology | offered | sold | price | winners |
    And the "eex" service answers "GET /fileadmin/GO/Resultats_encheres_20.xlsx" with 200 and:
      """
      a summary
      """
    When I run "data run pipeline.yaml"
    Then it succeeds
    And it prints "database: auction-results-duckdb@1.1.0 succeeded: 1 items, 1 built, 0 cached, 0 failed"
    And the database of "database" answers "SELECT auction_id, auction_number, segments, bidders_count, volume_offered_mwh, volume_allocated_mwh, round(price_weighted_avg_eur_mwh, 4) FROM auctions" with:
      | auction_id           | auction_number | segments | bidders_count | volume_offered_mwh | volume_allocated_mwh | round(price_weighted_avg_eur_mwh, 4) |
      | eex-fr-go-2021-05-27 | 27             | 48       | 28            | 5700.0             | 5300.0               | 0.6132                               |
      | eex-fr-go-2021-06-28 | 28             | 48       | 30            | 4800.0             | 4800.0               | 0.5                                  |
    And the database of "database" answers "SELECT technology, regions, volume_allocated_mwh, round(price_weighted_avg_eur_mwh, 4) FROM auction_technologies WHERE auction_id = 'eex-fr-go-2021-05-27'" with:
      | technology | regions | volume_allocated_mwh | round(price_weighted_avg_eur_mwh, 4) |
      | hydro      | 12      | 1200.0               | 0.5                                  |
      | solar      | 12      | 1700.0               | 0.8529                               |
      | thermal    | 12      | 1200.0               | 0.5                                  |
      | wind       | 12      | 1200.0               | 0.5                                  |
    And the database of "database" answers "SELECT files, rows, auctions, first_auction_date, last_auction_date FROM build_info" with:
      | files | rows | auctions | first_auction_date | last_auction_date |
      | 2     | 96   | 2        | 2021-08-18         | 2021-09-22        |
    And the database of "database" answers "SELECT stage, kind, subject FROM data_notes" with:
      | stage  | kind             | subject                    |
      | select | file_not_results | Resultats_encheres_20.xlsx |

  Scenario: Gaps in the auction numbers and production months are noted
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv">file</a>
      <a href="/fileadmin/GO/20211020_July_2021_29_Global_Results_detailedresults.csv">file</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv" with a full results csv for 28 participants, where:
      | region | technology | offered | sold | price | winners |
    And the "eex" service answers "GET /fileadmin/GO/20211020_July_2021_29_Global_Results_detailedresults.csv" with a full results csv for 30 participants, where:
      | region | technology | offered | sold | price | winners |
    When I run "data run pipeline.yaml"
    Then it succeeds
    And the notes of "database" in the latest run are:
      | kind                     | severity | subject                                     | message                                                                                                             |
      | auction_number_gap       | info     | eex-fr-go-2021-05-27..eex-fr-go-2021-07-29  | No results for auction number 28: the auctions go from eex-fr-go-2021-05-27 (2021-08-18) to eex-fr-go-2021-07-29 (2021-10-20). |
      | production_month_missing | warning  | 2021-06                                     | No auction results for production in June 2021.                                                                     |
    And the database of "database" answers "SELECT stage, kind, subject FROM data_notes" with:
      | stage | kind                     | subject                                    |
      | database | auction_number_gap       | eex-fr-go-2021-05-27..eex-fr-go-2021-07-29 |
      | database | production_month_missing | 2021-06                                    |

  Scenario: An auction number used again is noted, unless the numbering starts over
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv">file</a>
      <a href="/fileadmin/GO/20210922_June_2021_28_Global_Results_detailedresults.csv">file</a>
      <a href="/fileadmin/GO/20211020_July_2021_27_Global_Results_detailedresults.csv">file</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv" with a full results csv for 28 participants, where:
      | region | technology | offered | sold | price | winners |
    And the "eex" service answers "GET /fileadmin/GO/20210922_June_2021_28_Global_Results_detailedresults.csv" with a full results csv for 30 participants, where:
      | region | technology | offered | sold | price | winners |
    And the "eex" service answers "GET /fileadmin/GO/20211020_July_2021_27_Global_Results_detailedresults.csv" with a full results csv for 31 participants, where:
      | region | technology | offered | sold | price | winners |
    When I run "data run pipeline.yaml"
    Then it succeeds
    And the notes of "database" in the latest run are:
      | kind                    | severity | subject           | message                                                                                                      |
      | auction_number_repeated | info     | auction number 27 | Auction number 27 is used by 2 auctions: eex-fr-go-2021-05-27 (2021-08-18), eex-fr-go-2021-07-27 (2021-10-20). |

  Scenario: The same auction from two files fails the run
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv">csv</a>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.xlsx">xlsx</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv" with a full results csv for 28 participants, where:
      | region | technology | offered | sold | price | winners |
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.xlsx" with a full results workbook for 28 participants, garbled like EEX's, where:
      | region | technology | offered | sold | price | winners |
    When I run "data run pipeline.yaml"
    Then the exit code is 1
    And stderr mentions "eex-fr-go-2021-05-27 has FR-ARA wind twice: 20210818_May_2021_27_Global_Results_detailedresults.csv row 4 and 20210818_May_2021_27_Global_Results_detailedresults.xlsx row 4"
    And stderr mentions "stopped at stage 5 of 5, database"

  Scenario: A second run with nothing new reuses the database
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv">file</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv" with a full results csv for 28 participants, where:
      | region | technology | offered | sold | price | winners |
    And I ran "data run pipeline.yaml"
    When I run "data run pipeline.yaml --from database"
    Then it succeeds
    And it prints "database: auction-results-duckdb@1.1.0 succeeded: 1 items, 0 built, 1 cached, 0 failed"

  Scenario: The newest database can be found, or copied out, by its stage
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv">file</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv" with a full results csv for 28 participants, where:
      | region | technology | offered | sold | price | winners |
    And I ran "data run pipeline.yaml"
    When I run "data output pipeline.yaml database"
    Then it succeeds
    And it prints a line matching "*/store/05-database/auction-results-duckdb@1.1.0/objects/*"
    When I run "data output pipeline.yaml database --copy-to go-auctions.duckdb"
    Then it succeeds
    And it prints a line matching "go-auctions.duckdb: go-auctions.duckdb from run *, sha256 *"
    And the file "go-auctions.duckdb" exists
    When I run "data output pipeline.yaml database --copy-to ../go-auctions.duckdb"
    Then the exit code is 2
    And stderr mentions "--copy-to must name a file inside the working directory"

  Scenario: The newest database can be copied from the store's bucket, as the app reads it
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv">file</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv" with a full results csv for 28 participants, where:
      | region | technology | offered | sold | price | winners |
    And I ran "data run pipeline.yaml"
    And the "metadata" service is the metadata server of a job, giving the token "t0ken"
    And the "storage" service serves the store as the bucket "data-store"
    When I run "data output pipeline.yaml database --store gs://data-store"
    Then it succeeds
    And it prints a line matching "gs://data-store/05-database/auction-results-duckdb@1.1.0/objects/*"
    When I run "data output pipeline.yaml database --store gs://data-store --copy-to go-auctions.duckdb"
    Then it succeeds
    And it prints a line matching "go-auctions.duckdb: go-auctions.duckdb from run *, sha256 *"
    And the file "go-auctions.duckdb" exists
    And the "storage" service was asked "GET /storage/v1/b/data-store/o/05-database%2Fauction-results-duckdb%401.1.0%2Flatest.json" with the header "Authorization" set to "Bearer t0ken"

  Scenario: A bucket with nothing published, or that refuses to be read, says so
    Given the "metadata" service is the metadata server of a job, giving the token "t0ken"
    And the "storage" service answers "GET /storage/v1/b/empty-store/o/05-database%2Fauction-results-duckdb%401.1.0%2Flatest.json" with 404
    And the "storage" service answers "GET /storage/v1/b/closed-store/o/05-database%2Fauction-results-duckdb%401.1.0%2Flatest.json" with 403 and:
      """
      {"error": {"code": 403, "message": "data-app does not have storage.objects.get access"}}
      """
    When I run "data output pipeline.yaml database --store gs://empty-store"
    Then the exit code is 2
    And stderr mentions "stage database (auction-results-duckdb@1.1.0) has published nothing in gs://empty-store"
    When I run "data output pipeline.yaml database --store gs://closed-store"
    Then the exit code is 2
    And stderr mentions "cannot read gs://closed-store/05-database/auction-results-duckdb@1.1.0/latest.json: 403"
    When I run "data output pipeline.yaml database --store gs://"
    Then the exit code is 2
    And stderr mentions "'gs://' is not gs://BUCKET"

  Scenario: A stage with several outputs needs the one to copy named
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv">file</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv" with a full results csv for 28 participants, where:
      | region | technology | offered | sold | price | winners |
    And I ran "data run pipeline.yaml --to discover"
    When I run "data output pipeline.yaml discover --copy-to page.html"
    Then the exit code is 2
    And stderr mentions "stage discover published 2 outputs; name one with --name: page.html, files.json"
    When I run "data output pipeline.yaml discover --name page.html --copy-to page.html"
    Then it succeeds
    And the file "page.html" includes "Guarantees of Origin Data"

  Scenario: A stage that has published nothing has no output to show
    When I run "data output pipeline.yaml database"
    Then the exit code is 2
    And stderr mentions "stage database (auction-results-duckdb@1.1.0) has published nothing in store"
