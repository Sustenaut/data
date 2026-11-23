Feature: The power-auctions app's numbers
  The app at data.sustenaut.eu/power-auctions plots the merged auction
  results. EEX publishes one volume-weighted average price per auction,
  region and technology, so a "segment" (one region and technology in one
  auction) is what every plot is drawn from: a price distribution is of
  segments' prices, counted once or by the MWh they sold, and a point in time
  is the statistics of one auction's regional prices. A segment that sold
  nothing has no price: it is left out of the plots and counted beside them.

  These scenarios check those numbers on a small database, and that the app
  draws both pages from it without an error.

  Background:
    Given a scratch directory
    And a merged database holding:
      | auction | number | date       | production | region | technology | offered | sold | price | bidders |
      | a1      | 1      | 2025-01-15 | 2024-11-01 | FR-ARA | wind       | 100     | 100  | 1.0   | 10      |
      | a1      | 1      | 2025-01-15 | 2024-11-01 | FR-BRE | wind       | 300     | 300  | 3.0   | 10      |
      | a1      | 1      | 2025-01-15 | 2024-11-01 | FR-ARA | solar      | 100     | 50   | 2.0   | 10      |
      | a1      | 1      | 2025-01-15 | 2024-11-01 | FR-BRE | solar      | 100     | 0    |       | 10      |
      | a2      | 2      | 2025-02-19 | 2024-12-01 | FR-ARA | wind       | 200     | 200  | 2.0   | 20      |
      | a2      | 2      | 2025-02-19 | 2024-12-01 | FR-BRE | wind       | 200     | 100  | 4.0   | 20      |
      | a2      | 2      | 2025-02-19 | 2024-12-01 | FR-ARA | solar      | 100     | 100  | 1.0   | 20      |
      | a2      | 2      | 2025-02-19 | 2024-12-01 | FR-BRE | solar      | 100     | 100  | 3.0   | 20      |

  Scenario: Each technology's prices fall in the same bins, weighted by the MWh each segment sold
    When the price distribution is drawn with 3 bins spaced "linear", counting "mwh"
    Then the bin edges are "1.00, 2.00, 3.00, 4.00"
    And the bins hold:
      | technology | heights           |
      | wind       | 100, 200, 400     |
      | solar      | 100, 50, 100      |

  Scenario: Counted once, each segment adds one to its bin
    When the price distribution is drawn with 3 bins spaced "linear", counting "segments"
    Then the bins hold:
      | technology | heights |
      | wind       | 1, 1, 2 |
      | solar      | 1, 1, 1 |

  Scenario: Logarithmic bins are equal in ratio, which spreads the many low prices out
    When the price distribution is drawn with 2 bins spaced "log", counting "mwh"
    Then the bin edges are "1.00, 2.00, 4.00"
    And the bins hold:
      | technology | heights  |
      | wind       | 100, 600 |
      | solar      | 100, 150 |

  Scenario: The summary says what the plots are drawn from, and what they leave out
    When the summary is made, weighted by MWh
    Then the summary is:
      | technology | auctions | segments | unsold_segments | mwh_sold | min  | p10  | median | mean | p90  | max  |
      | wind       | 2        | 4        | 0               | 700      | 1.00 | 1.13 | 2.60   | 2.57 | 3.90 | 4.00 |
      | solar      | 2        | 3        | 1               | 250      | 1.00 | 1.00 | 2.00   | 2.00 | 3.00 | 3.00 |

  Scenario: Each point in time is the statistics of one auction's regional prices
    When the points over time are made by "auction" date, weighted by MWh
    Then the points are:
      | auction | at         | technology | regions | unsold_regions | min  | p10  | median | mean | p90  | max  |
      | a1      | 2025-01-15 | wind       | 2       | 0              | 1.00 | 1.00 | 2.50   | 2.50 | 3.00 | 3.00 |
      | a1      | 2025-01-15 | solar      | 1       | 1              | 2.00 | 2.00 | 2.00   | 2.00 | 2.00 | 2.00 |
      | a2      | 2025-02-19 | wind       | 2       | 0              | 2.00 | 2.00 | 2.67   | 2.67 | 4.00 | 4.00 |
      | a2      | 2025-02-19 | solar      | 2       | 0              | 1.00 | 1.00 | 2.00   | 2.00 | 3.00 | 3.00 |

  Scenario: Unweighted, each region counts once, and points can sit at their production month
    When the points over time are made by "production" date, not weighted
    Then the points are:
      | auction | at         | technology | regions | unsold_regions | min  | p10  | median | mean | p90  | max  |
      | a1      | 2024-11-01 | wind       | 2       | 0              | 1.00 | 1.00 | 2.00   | 2.00 | 3.00 | 3.00 |
      | a1      | 2024-11-01 | solar      | 1       | 1              | 2.00 | 2.00 | 2.00   | 2.00 | 2.00 | 2.00 |
      | a2      | 2024-12-01 | wind       | 2       | 0              | 2.00 | 2.00 | 3.00   | 3.00 | 4.00 | 4.00 |
      | a2      | 2024-12-01 | solar      | 2       | 0              | 1.00 | 1.00 | 2.00   | 2.00 | 3.00 | 3.00 |

  Scenario Outline: The filters keep the segments of the auctions they match
    When the segments are filtered with <filter> set to "<value>"
    Then <count> segments are kept, from the auctions "<auctions>"

    Examples:
      | filter          | value              | count | auctions |
      | dates           | 2025-02-01         | 4     | a2       |
      | production from | 2024-12-01         | 4     | a2       |
      | regions         | FR-ARA             | 4     | a1, a2   |
      | technologies    | solar              | 4     | a1, a2   |
      | min_share_sold  | 0.8                | 4     | a2       |
      | min_bidders     | 15                 | 4     | a2       |
      | min_segment_mwh | 100                | 6     | a1, a2   |
      | auction_numbers | 1                  | 4     | a1       |

  Scenario: The app draws both pages from the database without an error
    When the app is opened on the database
    Then the app shows no error
    And the app has the tabs "Price distribution, Prices over time"
    And the app's distribution page describes "2 auctions by auction date from January 2025 to February 2025, in every region."

  Scenario: Every control redraws the pages without an error
    When the app is opened on the database
    And each control is set in turn:
      | control     | label                           | value       |
      | radio       | Bin spacing                     | log         |
      | radio       | Each segment counts             | segments    |
      | radio       | Bar height                      | absolute    |
      | radio       | Layout                          | overlay     |
      | slider      | Bins                            | 5           |
      | multiselect | Statistics                      | min, max    |
      | toggle      | Weight by MWh sold              | false       |
      | radio       | Hover shows                     | all         |
      | radio       | #time_layout                    | overlay     |
      | radio       | Date by                         | production  |
      | multiselect | Regions                         | FR-ARA      |
      | multiselect | Technologies                    | solar       |
      | slider      | At least this many bidders      | 15          |
      | slider      | Share of offered volume sold    | 80, 100     |
      | slider      | Auction numbers                 | 2, 2        |
      | number      | Segments that sold at least (MWh) | 100       |
    Then the app shows no error
    And the app's distribution page describes "1 auction by production month from November 2024 to December 2024, in Auvergne-Rhône-Alpes."

  Scenario: Filters that keep nothing say so
    When the app is opened on the database
    And each control is set in turn:
      | control | label                      | value |
      | slider  | At least this many bidders | 20    |
      | number  | Segments that sold at least (MWh) | 1000 |
    Then the app shows no error
    And the app says "No auction matches these filters."

  Scenario: data.sustenaut.eu's landing page links to the app
    When the site's landing page is opened
    Then the landing page links to "power-auctions" as "French guarantees of origin auctions"

  Scenario: The app says so when the store has no published database
    When the app is opened on an empty store
    Then the app shows the error "The auction results cannot be read: the merge stage (auction-results-duckdb@1.0.0) has published nothing in"
