Feature: Stage 2, download: every file the page links to
  The download stage fetches each file the discover stage listed, one item
  per file, and stores it as fetched. An archive's files are stored too, each
  as an output of its own, so later stages see every file whether it came
  loose or in an archive. Outputs are stored by their content, so a file that
  has not changed costs nothing to fetch again.

  Background:
    Given the program under test is "soldera"
    And a scratch directory
    And the repository's pipeline "eex-french-power-auctions"

  Scenario: Every file is downloaded, and each file in an archive is stored too
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/latest.xlsx">xlsx</a>
      <a href="/fileadmin/GO/results.zip">zip</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/latest.xlsx" with 200 and:
      """
      the latest results
      """
    And the "eex" service answers "GET /fileadmin/GO/results.zip" with a zip holding:
      | path                     | content     |
      | 2025/january.xlsx        | january     |
      | february.csv             | february    |
      | __MACOSX/2025/._jan.xlsx | macos stuff |
    When I run "soldera run pipeline.yaml --to download"
    Then it succeeds
    And it prints "download: eex-french-auction-download@1.0.0 succeeded: 2 items, 2 built, 0 cached, 0 failed"
    And the published outputs of "download" are:
      | item        | name              | holds              |
      | latest.xlsx | latest.xlsx       | the latest results |
      | results.zip | results.zip       |                    |
      | results.zip | 2025/january.xlsx | january            |
      | results.zip | february.csv      | february           |
    And the notes of "download" in the latest run are:
      | kind                   | severity | subject                              |
      | archive_member_skipped | info     | results.zip/__MACOSX/2025/._jan.xlsx |

  Scenario: Files are fetched again on every run, but an unchanged file is stored once
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/latest.xlsx">xlsx</a>
      <a href="/fileadmin/GO/results.zip">zip</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/latest.xlsx" with 200 and:
      """
      the latest results
      """
    And the "eex" service answers "GET /fileadmin/GO/results.zip" with a zip holding:
      | path                     | content     |
      | 2025/january.xlsx        | january     |
      | february.csv             | february    |
      | __MACOSX/2025/._jan.xlsx | macos stuff |
    And I ran "soldera run pipeline.yaml --to download"
    When I run "soldera run pipeline.yaml --to download"
    Then it succeeds
    And the "eex" service was asked "GET /fileadmin/GO/results.zip" 2 times
    And the stage "download" stores 4 objects

  Scenario: A file that cannot be fetched fails the stage, after the other files are fetched
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/latest.xlsx">xlsx</a>
      <a href="/fileadmin/GO/results.zip">zip</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/latest.xlsx" with 404
    And the "eex" service answers "GET /fileadmin/GO/results.zip" with a zip holding:
      | path         | content  |
      | february.csv | february |
    When I run "soldera run pipeline.yaml --to download"
    Then the exit code is 1
    And it prints "download: eex-french-auction-download@1.0.0 failed: 2 items, 1 built, 0 cached, 1 failed"
    And stderr mentions "download: latest.xlsx failed: HttpError: GET"
    And stderr mentions "answered 404"

  Scenario: A link to another site is not fetched
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="https://elsewhere.example/fileadmin/GO/other.pdf">pdf</a>
      """
    When I run "soldera run pipeline.yaml --to download"
    Then the exit code is 1
    And stderr mentions "download: other.pdf failed: ValueError: https://elsewhere.example/fileadmin/GO/other.pdf is not on"

  Scenario: An archive that is not a readable zip fails its item
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/latest.xlsx">xlsx</a>
      <a href="/fileadmin/GO/results.zip">zip</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/latest.xlsx" with 200 and:
      """
      the latest results
      """
    And the "eex" service answers "GET /fileadmin/GO/results.zip" with 200 and:
      """
      not a zip at all
      """
    When I run "soldera run pipeline.yaml --to download"
    Then the exit code is 1
    And stderr mentions "download: results.zip failed: ValueError: results.zip is not a readable zip archive"

  Scenario: A damaged file inside an archive fails the archive's item, naming the file
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/results.zip">zip</a>
      """
    And the "eex" service answers "GET /fileadmin/GO/results.zip" with a zip whose "2021/march.xlsx" is corrupt
    When I run "soldera run pipeline.yaml --to download"
    Then the exit code is 1
    And stderr mentions "download: results.zip failed: ValueError: results.zip: cannot read 2021/march.xlsx: Bad CRC-32"
