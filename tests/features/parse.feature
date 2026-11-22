Feature: Stage 4, parse: each results file into canonical auction rows
  The parse stage reads each file the select stage kept, xlsx or csv, and
  writes it as auction_results rows: one per region and technology, with the
  auction's date, production month and EEX number from the file name and the
  participant count from the sheet. It repairs EEX's garbled accents, reads
  "-" as nothing, and codes regions (ISO 3166-2) and technologies. A file
  that does not hold what an EEX results file holds fails the run, unless a
  rule in the corrections file corrects that exact row; a rule that is no
  longer needed fails the run too. So does a file that leaves out any of the
  48 region and technology pairs, or lists them out of EEX's usual order
  (regions alphabetically, each with Eolien onshore, Hydraulique, Solaire,
  Thermique), unless a rule says that file is known to.

  Background:
    Given the program under test is "soldera"
    And a scratch directory
    And the repository's pipeline "eex-french-power-auctions"

  Scenario: A workbook becomes one canonical row per region and technology
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20230215_December_2022_48_GLOBAL_Results_detailedresults.xlsx">file</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20230215_December_2022_48_GLOBAL_Results_detailedresults.xlsx" with a full results workbook for 24 participants, garbled like EEX's, where:
      | region               | technology     | offered | sold  | price | winners |
      | Auvergne-Rhône-Alpes | Eolien onshore | 59529   | 59529 | 0.78  | 8       |
      | Haut-de-France       | Solaire        | 2172    | 11    | 0.41  | 1       |
      | Île-de-France        | Hydraulique    | 335     | -     | -     | 0       |
    When I run "soldera run pipeline.yaml"
    Then it succeeds
    And it prints "parse: eex-french-auction@1.0.0 succeeded: 1 items, 1 built, 0 cached, 0 failed"
    And the parse stage wrote 48 rows
    And the parsed rows of "parse" include, in order:
      | auction_id          | auction_number | auction_date | production_period_start | production_period_end | region | technology | volume_offered_mwh | volume_allocated_mwh | price_weighted_avg_eur_mwh | bidders_count | winners_count | source_row |
      | eex-fr-go-2022-12-48 | 48            | 2023-02-15   | 2022-12-01              | 2022-12-31            | FR-ARA | wind       | 59529.0            | 59529.0              | 0.78                       | 24            | 8             | 4          |
      | eex-fr-go-2022-12-48 | 48            | 2023-02-15   | 2022-12-01              | 2022-12-31            | FR-HDF | solar      | 2172.0             | 11.0                 | 0.41                       | 24            | 1             | 26         |
      | eex-fr-go-2022-12-48 | 48            | 2023-02-15   | 2022-12-01              | 2022-12-31            | FR-IDF | hydro      | 335.0              | 0.0                  |                            | 24            | 0             | 29         |
    And the parsed rows of "parse" include, in order:
      | extras                                                                         |
      | {"region_label": "Auvergne-Rhône-Alpes", "technology_label": "Eolien onshore"} |
      | {"region_label": "Île-de-France", "technology_label": "Hydraulique"}           |

  Scenario: A csv with semicolons and decimal commas reads the same way
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv">file</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv" with a full results csv for 28 participants, where:
      | region    | technology | offered | sold | price | winners |
      | Bretagne  | Solaire    | 6225    | 6225 | 0.4   | 4       |
      | Grand Est | Thermique  | 5246    | -    | -     | 0       |
    When I run "soldera run pipeline.yaml"
    Then it succeeds
    And the parse stage wrote 48 rows
    And the parsed rows of "parse" include, in order:
      | auction_id           | auction_date | region | technology | volume_offered_mwh | volume_allocated_mwh | price_weighted_avg_eur_mwh | bidders_count | source_sheet |
      | eex-fr-go-2021-05-27 | 2021-08-18   | FR-BRE | solar      | 6225.0             | 6225.0               | 0.4                        | 28            |              |
      | eex-fr-go-2021-05-27 | 2021-08-18   | FR-GES | thermal    | 5246.0             | 0.0                  |                            | 28            |              |

  Scenario Outline: A file that does not hold what is expected fails the run, saying where
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv">csv</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv" with 200 and:
      """
      Number of Participants to the Auction;28
      Région / Region;Technologie / Technology;Total Volume Auctionned;Total Volume Sold;Weighted Average Price (€ / MWh);Number of winners per couple region/technology
      Bretagne;Solaire;6225;6225;0,4;4
      <row>
      """
    When I run "soldera run pipeline.yaml"
    Then the exit code is 1
    And stderr mentions "20210818_May_2021_27_Global_Results_detailedresults.csv row 4: <problem>"
    And stderr mentions "stopped at stage 4 of 4, parse"

    Examples:
      | row                          | problem                                          |
      | Bretagne;Solaire;10;10;0,5;1 | Bretagne Solaire appears twice                   |
      | Corsica;Solaire;10;10;0,5;1  | unknown region 'Corsica'                         |
      | Bretagne;Marémotrice;10;10;0,5;1 | unknown technology 'Marémotrice'            |
      | Normandie;Solaire;10;20;0,5;1 | 20 MWh sold is more than the 10 MWh offered     |
      | Normandie;Solaire;10;-;0,5;0 | a price of 0.5 with nothing sold                 |
      | Normandie;Solaire;ten;10;0,5;1 | the volume offered is 'ten', not a number      |

  Scenario: A file that leaves out a region and technology fails, naming it
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv">file</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv" with a full results csv for 28 participants, where:
      | region   | technology | offered | sold | price | winners |
      | Bretagne | Solaire    | absent  |      |       |         |
    When I run "soldera run pipeline.yaml"
    Then the exit code is 1
    And stderr mentions "20210818_May_2021_27_Global_Results_detailedresults.csv lacks 1 of the 48 region and technology segments: Bretagne Solaire"

  Scenario: A file that lists its rows out of the usual order fails, saying where
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv">file</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv" with a full results csv for 28 participants, where:
      | region               | technology     | offered | sold | price | winners | after                              |
      | Auvergne-Rhône-Alpes | Eolien onshore | absent  |      |       |         |                                    |
      | Auvergne-Rhône-Alpes | Eolien onshore | 100     | 100  | 0.5   | 1       | Auvergne-Rhône-Alpes / Hydraulique |
    When I run "soldera run pipeline.yaml"
    Then the exit code is 1
    And stderr mentions "20210818_May_2021_27_Global_Results_detailedresults.csv row 4: Auvergne-Rhône-Alpes Hydraulique is out of EEX's usual order, where Auvergne-Rhône-Alpes Eolien onshore belongs"

  Scenario: A rule can say a file is known to list its rows in another order, or to be partial
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv">file</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv" with a full results csv for 28 participants, where:
      | region               | technology     | offered | sold | price | winners | after                              |
      | Auvergne-Rhône-Alpes | Eolien onshore | absent  |      |       |         |                                    |
      | Auvergne-Rhône-Alpes | Eolien onshore | 100     | 100  | 0.5   | 1       | Auvergne-Rhône-Alpes / Hydraulique |
      | Bretagne             | Solaire        | absent  |      |       |         |                                    |
    And the corrections file holds:
      """
      corrections:
        - id: another-order
          file: 20210818_May_2021_27_Global_Results_detailedresults.csv
          kind: row_order
          problem: The rows are in another order.
          evidence: The file as published.
          reported_to_provider: "no"
        - id: partial
          file: 20210818_May_2021_27_Global_Results_detailedresults.csv
          kind: partial_auction
          problem: Only some segments were auctioned.
          evidence: The file as published.
          reported_to_provider: "no"
      """
    When I run "soldera run pipeline.yaml"
    Then it succeeds
    And the parse stage wrote 47 rows
    And the notes of "parse" in the latest run are:
      | kind            | severity | subject | message                                         |
      | data_correction | info     | 20210818_May_2021_27_Global_Results_detailedresults.csv | The rows are in another order. (another-order)  |
      | data_correction | info     | 20210818_May_2021_27_Global_Results_detailedresults.csv | Only some segments were auctioned. (partial)    |

  Scenario Outline: A rule for a file's order or completeness that is no longer needed fails the run
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv">file</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv" with a full results csv for 28 participants, where:
      | region | technology | offered | sold | price | winners |
    And the corrections file holds:
      """
      corrections:
        - id: the-rule
          file: 20210818_May_2021_27_Global_Results_detailedresults.csv
          kind: <kind>
          problem: A mistake EEX has since fixed.
          evidence: It was there before.
          reported_to_provider: "no"
      """
    When I run "soldera run pipeline.yaml"
    Then the exit code is 1
    And stderr mentions "correction the-rule is no longer needed: 20210818_May_2021_27_Global_Results_detailedresults.csv <problem>"

    Examples:
      | kind            | problem                             |
      | row_order       | lists its rows in the usual order   |
      | partial_auction | lists every segment                 |

  Scenario: A correction rule drops a wrong row and notes a missing one
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20260121_October_2025_7_GLOBAL_Results_detailedresults.csv">file</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20260121_October_2025_7_GLOBAL_Results_detailedresults.csv" with a full results csv for 31 participants, where:
      | region                     | technology  | offered | sold | price | winners | after                                  |
      | Provence-Alpes-Côte d'Azur | Thermique   | 2975    | 2975 | 0.17  | 1       |                                        |
      | Provence-Alpes-Côte d'Azur | Thermique   | 2959    | 2959 | 0.17  | 1       | Provence-Alpes-Côte d'Azur / Thermique |
      | Île-de-France              | Hydraulique | absent  |      |       |         |                                        |
    And the corrections file holds:
      """
      corrections:
        - id: repeated-row
          file: 20260121_October_2025_7_GLOBAL_Results_detailedresults.csv
          kind: wrong_row
          row: {region: Provence-Alpes-Côte d'Azur, technology: Thermique, volume_offered: 2959}
          action: drop
          problem: PACA Thermique is listed twice.
          evidence: The second row is September's.
          reported_to_provider: "no"
          source_sha256: "0000"
          excerpt:
            - {row: 50, region: Provence-Alpes-Côte d'Azur, technology: Thermique, volume_offered: 2975}
            - {row: 51, region: Provence-Alpes-Côte d'Azur, technology: Thermique, volume_offered: 2959}
        - id: missing-row
          file: 20260121_October_2025_7_GLOBAL_Results_detailedresults.csv
          kind: missing_row
          row: {region: Île-de-France, technology: Hydraulique}
          problem: Île-de-France Hydraulique is missing.
          evidence: Every other auction has it.
          reported_to_provider: "no"
          source_sha256: "0000"
          excerpt:
            - {row: 28, region: Île-de-France, technology: Eolien onshore}
            - {row: 29, region: Île-de-France, technology: Solaire}
      """
    When I run "soldera run pipeline.yaml"
    Then it succeeds
    And the parse stage wrote 47 rows
    And the parsed rows of "parse" include, in order:
      | region | technology | volume_offered_mwh | source_row |
      | FR-PAC | thermal    | 2975.0             | 50         |
    And the notes of "parse" in the latest run are:
      | kind            | severity | subject   | message                                                                         |
      | data_correction | warning  | 20260121_October_2025_7_GLOBAL_Results_detailedresults.csv row 51 | PACA Thermique is listed twice. Corrected: the row was left out. (repeated-row) |
      | data_correction | info     | 20260121_October_2025_7_GLOBAL_Results_detailedresults.csv        | Île-de-France Hydraulique is missing. (missing-row)                             |

  Scenario: A correction can set fields of a wrong row
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20260121_October_2025_7_GLOBAL_Results_detailedresults.csv">file</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20260121_October_2025_7_GLOBAL_Results_detailedresults.csv" with a full results csv for 31 participants, where:
      | region               | technology  | offered | sold | price | winners | after                                 |
      | Auvergne-Rhône-Alpes | Hydraulique | absent  |      |       |         |                                       |
      | Bretagne             | Hydraulique | 7       | 7    | 0.5   | 1       | Auvergne-Rhône-Alpes / Eolien onshore |
    And the corrections file holds:
      """
      corrections:
        - id: mislabelled-row
          file: 20260121_October_2025_7_GLOBAL_Results_detailedresults.csv
          kind: wrong_row
          row: {region: Bretagne, technology: Hydraulique, volume_offered: 7}
          action: set
          set: {region: Auvergne-Rhône-Alpes}
          problem: The row is labelled with the wrong region.
          evidence: EEX confirmed it.
          reported_to_provider: "2026-11-22"
          source_sha256: "0000"
          excerpt:
            - {row: 5, region: Bretagne, technology: Hydraulique, volume_offered: 7}
      """
    When I run "soldera run pipeline.yaml"
    Then it succeeds
    And the parse stage wrote 48 rows
    And the parsed rows of "parse" include, in order:
      | region | technology | volume_offered_mwh | source_row |
      | FR-ARA | hydro      | 7.0                | 5          |
      | FR-BRE | hydro      | 100.0              | 13         |

  Scenario Outline: A correction that is no longer needed fails the run, so EEX's fix is noticed
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20260121_October_2025_7_GLOBAL_Results_detailedresults.csv">file</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20260121_October_2025_7_GLOBAL_Results_detailedresults.csv" with a full results csv for 31 participants, where:
      | region | technology | offered | sold | price | winners |
    And the corrections file holds:
      """
      corrections:
        - id: the-rule
          file: 20260121_October_2025_7_GLOBAL_Results_detailedresults.csv
          kind: <kind>
          row: <row>
          action: drop
          problem: A mistake EEX has since fixed.
          evidence: It was there before.
          reported_to_provider: "2026-11-22"
          source_sha256: "0000"
          excerpt:
            - {row: 51, region: Provence-Alpes-Côte d'Azur, technology: Thermique, volume_offered: 2959}
      """
    When I run "soldera run pipeline.yaml"
    Then the exit code is 1
    And stderr mentions "<problem>"

    Examples:
      | kind        | row                                                                              | problem                                                                                                                         |
      | wrong_row   | {region: Provence-Alpes-Côte d'Azur, technology: Thermique, volume_offered: 2959} | correction the-rule is no longer needed as written: no row of 20260121_October_2025_7_GLOBAL_Results_detailedresults.csv match |
      | missing_row | {region: Île-de-France, technology: Hydraulique}                                 | correction the-rule is no longer needed: 20260121_October_2025_7_GLOBAL_Results_detailedresults.csv now has the row (row 29)                                                        |

  Scenario: A corrections file that is not well formed stops the stage before it starts
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv">csv</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv" with 200 and:
      """
      Number of Participants to the Auction;28
      Région / Region;Technologie / Technology;Total Volume Auctionned;Total Volume Sold;Weighted Average Price (€ / MWh);Number of winners per couple region/technology
      Bretagne;Solaire;6225;6225;0,4;4
      """
    And the corrections file holds:
      """
      corrections:
        - id: no-evidence
          file: 20210818_May_2021_27_Global_Results_detailedresults.csv
          kind: wrong_row
          row: {region: Bretagne}
          action: drop
          problem: Something.
      """
    When I run "soldera run pipeline.yaml"
    Then the exit code is 1
    And stderr mentions "correction 'no-evidence' lacks evidence, reported_to_provider"

  Scenario: A file named like a workbook that is not one fails, saying so
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20190918_April_2019_global_results.xlsx">xlsx</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20190918_April_2019_global_results.xlsx" with 200 and:
      """
      not a workbook
      """
    When I run "soldera run pipeline.yaml"
    Then the exit code is 1
    And stderr mentions "20190918_April_2019_global_results.xlsx is not a readable xlsx workbook"

  Scenario: The repository's corrections each match the excerpt they keep
    When I run "soldera corrections check corrections/eex-french-power-auctions.yaml"
    Then it succeeds
    And it prints "0 problems"

  Scenario Outline: A corrections file must be a YAML file inside the working directory
    When I run "soldera corrections check <path>"
    Then the exit code is 2
    And stderr mentions "<problem>"

    Examples:
      | path                  | problem                                                     |
      | ../elsewhere.yaml     | a corrections file must be inside the working directory     |
      | pipeline.yaml.txt     | pipeline.yaml.txt is not a .yaml file                       |

  Scenario: A rule that does not match its own excerpt fails the check
    Given the corrections file holds:
      """
      corrections:
        - id: off-by-one
          file: 20260121_October_2025_7_GLOBAL_Results_detailedresults.csv
          kind: wrong_row
          row: {region: Provence-Alpes-Côte d'Azur, technology: Thermique, volume_offered: 2959}
          action: drop
          problem: PACA Thermique is listed twice.
          evidence: The second row is September's.
          reported_to_provider: "no"
          source_sha256: "0000"
          excerpt:
            - {row: 52, region: Provence-Alpes-Côte d'Azur, technology: Thermique, volume_offered: 2975}
      """
    When I run "soldera corrections check corrections/eex-french-power-auctions.yaml"
    Then the exit code is 1
    And stderr mentions "off-by-one: on its excerpt, correction off-by-one is no longer needed as written: no row of 20260121_October_2025_7_GLOBAL_Results_detailedresults.csv match"
    And it prints "1 rules, 1 checked against their excerpts, 1 problems"

  Scenario Outline: A correction with a typo fails before any file is read
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv">csv</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv" with 200 and:
      """
      Number of Participants to the Auction;28
      Région / Region;Technologie / Technology;Total Volume Auctionned;Total Volume Sold;Weighted Average Price (€ / MWh);Number of winners per couple region/technology
      Bretagne;Solaire;6225;6225;0,4;4
      """
    And the corrections file holds:
      """
      corrections:
        - id: typo
          file: <file>
          kind: wrong_row
          row: <row>
          action: drop
          problem: Something.
          evidence: Something else.
          reported_to_provider: "no"
          source_sha256: "0000"
          excerpt:
            - {row: 4, region: Bretagne}
      """
    When I run "soldera run pipeline.yaml"
    Then the exit code is 1
    And stderr mentions "correction typo: <problem>"

    Examples:
      | file                                                     | row                    | problem                                                   |
      | October_2025.xlsx                                        | {region: Bretagne}     | October_2025.xlsx is not named like an EEX results file   |
      | 20210818_May_2021_27_Global_Results_detailedresults.csv | {region: Bretange}     | unknown region 'Bretange'                                 |
      | 20210818_May_2021_27_Global_Results_detailedresults.csv | {technology: Solar}    | unknown technology 'Solar'                                |
      | 20210818_May_2021_27_Global_Results_detailedresults.csv | {volume: 3}            | unknown fields volume                                     |
