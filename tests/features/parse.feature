Feature: Stage 4, parse: each results file into canonical auction rows
  The parse stage reads each file the select stage kept, xlsx or csv, and
  writes it as auction_results rows: one per region and technology, with the
  auction's date, production month and EEX number from the file name and the
  participant count from the sheet. It repairs EEX's garbled accents, reads
  "-" as nothing, and codes regions (ISO 3166-2) and technologies. A file
  that does not hold what an EEX results file holds fails the run, unless
  that exact problem in that exact file has been accepted in the pipeline.

  Background:
    Given the program under test is "soldera"
    And a scratch directory
    And the repository's pipeline "eex-french-power-auctions"

  Scenario: A workbook becomes one canonical row per region and technology
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20230315_November_2022_47_2_GLOBAL_Results_detailedresults.xlsx">xlsx</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20230315_November_2022_47_2_GLOBAL_Results_detailedresults.xlsx" with a workbook:
      | Aggregated Auction Results            |                          |                         |                   |                                    |                 |                                       |                                                |
      | Number of Participants to the Auction | 24                       |                         |                   |                                    |                 |                                       |                                                |
      | RÃ©gion / Region                      | Technologie / Technology | Total Volume Auctionned | Total Volume Sold | Weighted Average Price (â‚¬ / MWh) | My Total Volume | My Weighted Average Price (â‚¬ / MWh) | Number of winners per couple region/technology |
      | Auvergne-RhÃ´ne-Alpes                | Eolien onshore           | 59529                   | 59529             | 0.78                               | -               | -                                     | 8                                              |
      | ÃŽle-de-France                       | Hydraulique              | 335                     | -                 | -                                  | -               | -                                     | 0                                              |
      | Haut-de-France                        | Solaire                  | 2172                    | 11                | 0.41                               | -               | -                                     | 1                                              |
    When I run "soldera run pipeline.yaml"
    Then it succeeds
    And it prints "parse: eex-french-auction@1.0.0 succeeded: 1 items, 1 built, 0 cached, 0 failed"
    And the parsed rows of "parse" are:
      | auction_id             | auction_number | auction_date | production_period_start | production_period_end | region | technology | volume_offered_mwh | volume_allocated_mwh | price_weighted_avg_eur_mwh | bidders_count | winners_count | source_row |
      | eex-fr-go-2022-11-47-2 | 47-2           | 2023-03-15   | 2022-11-01              | 2022-11-30            | FR-ARA | wind       | 59529.0            | 59529.0              | 0.78                       | 24            | 8             | 4          |
      | eex-fr-go-2022-11-47-2 | 47-2           | 2023-03-15   | 2022-11-01              | 2022-11-30            | FR-IDF | hydro      | 335.0              | 0.0                  |                            | 24            | 0             | 5          |
      | eex-fr-go-2022-11-47-2 | 47-2           | 2023-03-15   | 2022-11-01              | 2022-11-30            | FR-HDF | solar      | 2172.0             | 11.0                 | 0.41                       | 24            | 1             | 6          |
    And the parsed rows of "parse" are:
      | extras                                                                    |
      | {"region_label": "Auvergne-Rhône-Alpes", "technology_label": "Eolien onshore"} |
      | {"region_label": "Île-de-France", "technology_label": "Hydraulique"}           |
      | {"region_label": "Haut-de-France", "technology_label": "Solaire"}             |

  Scenario: A csv with semicolons and decimal commas reads the same way
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv">csv</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20210818_May_2021_27_Global_Results_detailedresults.csv" with 200 and:
      """
      Aggregated Auction Results;;;;;;;
      ;;;;;;;
      Number of Participants to the Auction;28;;;;;;
      ;;;;;;;
      Région / Region;Technologie / Technology;Total Volume Auctionned;Total Volume Sold;Weighted Average Price (€ / MWh);My Total Volume;My Weighted Average Price (€ / MWh);Number of winners per couple region/technology
      Bretagne;Solaire;6225;6225;0,4;-;-;4
      Grand Est;Thermique;5246;-;-;-;-;0
      """
    When I run "soldera run pipeline.yaml"
    Then it succeeds
    And the parsed rows of "parse" are:
      | auction_id          | auction_date | region | technology | volume_offered_mwh | volume_allocated_mwh | price_weighted_avg_eur_mwh | bidders_count | source_sheet |
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

  Scenario: A mistake in EEX's file that has been accepted keeps the row, region unknown, with a warning
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20260121_October_2025_7_GLOBAL_Results_detailedresults.csv">csv</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20260121_October_2025_7_GLOBAL_Results_detailedresults.csv" with 200 and:
      """
      Number of Participants to the Auction;31
      Région / Region;Technologie / Technology;Total Volume Auctionned;Total Volume Sold;Weighted Average Price (€ / MWh);Number of winners per couple region/technology
      Provence-Alpes-Côte d'Azur;Thermique;2975;2975;0,17;1
      Provence-Alpes-Côte d'Azur;Thermique;2959;2959;0,17;1
      """
    And the pipeline accepts a "duplicate_segment" at row 4 of "20260121_October_2025_7_GLOBAL_Results_detailedresults.csv" as the "eex" service serves it, noting "EEX lists PACA Thermique twice"
    When I run "soldera run pipeline.yaml"
    Then it succeeds
    And the parsed rows of "parse" are:
      | region | technology | volume_offered_mwh | source_row |
      | FR-PAC | thermal    | 2975.0             | 3          |
      |        | thermal    | 2959.0             | 4          |
    And the notes of "parse" in the latest run are:
      | kind           | severity | subject                                                         | message                        |
      | accepted_issue | warning  | 20260121_October_2025_7_GLOBAL_Results_detailedresults.csv row 4 | EEX lists PACA Thermique twice |

  Scenario: An accepted issue that is no longer in its file fails it, so the list cannot go stale
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/20260121_October_2025_7_GLOBAL_Results_detailedresults.csv">csv</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/20260121_October_2025_7_GLOBAL_Results_detailedresults.csv" with 200 and:
      """
      Number of Participants to the Auction;31
      Région / Region;Technologie / Technology;Total Volume Auctionned;Total Volume Sold;Weighted Average Price (€ / MWh);Number of winners per couple region/technology
      Provence-Alpes-Côte d'Azur;Thermique;2975;2975;0,17;1
      Île-de-France;Thermique;2959;2959;0,17;1
      """
    And the pipeline accepts a "duplicate_segment" at row 4 of "20260121_October_2025_7_GLOBAL_Results_detailedresults.csv" as the "eex" service serves it, noting "EEX lists PACA Thermique twice"
    When I run "soldera run pipeline.yaml"
    Then the exit code is 1
    And stderr mentions "the accepted issue at row 4 is no longer in the file"

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
