Feature: Stage 1, discover: the files the EEX page links to
  The discover stage reads the EEX French auctions page and lists every file
  it links to, with the section, title and publishing date the page gives
  each one. It keeps the page itself too. Choosing which files to use is a
  later stage's job. These scenarios run the repository's own pipeline
  against a fake EEX.

  Background:
    Given the program under test is "soldera"
    And a scratch directory
    And the repository's pipeline "eex-french-power-auctions"

  Scenario: Every linked file is listed once, with what the page says about it
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <html><body>
      <a href="/en/markets/other-page">Another page</a>
      <div class="text-teaser">
        <p class="teaserTitle">Guarantees of Origin Data</p>
        <a href="/fileadmin/GO/20261118_July_2026_21_GLOBAL_Results.xlsx" title="download the xlsx file">download the xlsx file</a>
      </div>
      <h2>Guarantees of Origin Data</h2>
      <table><tbody>
        <tr>
          <td data-field="publishing_date" data-date="2026-11-19">2026-11-19</td>
          <td data-field="title">GO 2026 Global Results</td>
          <td data-field="file"><a href="/fileadmin/GO/20261119_GO_2026_GLOBAL_Results.zip">zip (692 KB)</a></td>
        </tr>
        <tr>
          <td data-field="publishing_date" data-date="2026-11-18">2026-11-18</td>
          <td data-field="title">GO July 2026 Results</td>
          <td data-field="file"><a href="/fileadmin/GO/20261118_July_2026_21_GLOBAL_Results.xlsx">xlsx (40 KB)</a></td>
        </tr>
      </tbody></table>
      <h2>Guarantees of Origin - FAQ</h2>
      <table><tbody>
        <tr>
          <td data-field="publishing_date" data-date="2020-10-12">2020-10-12</td>
          <td data-field="title">FAQ (English)</td>
          <td data-field="file"><a href="https://www.eex.com/fileadmin/Docs/FAQ%20GO.pdf">pdf (241 KB)</a></td>
        </tr>
      </tbody></table>
      </body></html>
      """
    When I run "soldera run pipeline.yaml"
    Then it succeeds
    And it prints "discover: eex-french-auction-page@1.0.0 succeeded: 1 items, 1 built, 0 cached, 0 failed"
    And the published "files.json" of "discover" lists:
      | name                                      | extension | section                    | title                | published  | label        |
      | 20261118_July_2026_21_GLOBAL_Results.xlsx | xlsx      | Guarantees of Origin Data  | GO July 2026 Results | 2026-11-18 | xlsx (40 KB) |
      | 20261119_GO_2026_GLOBAL_Results.zip       | zip       | Guarantees of Origin Data  | GO 2026 Global Results | 2026-11-19 | zip (692 KB) |
      | FAQ GO.pdf                                | pdf       | Guarantees of Origin - FAQ | FAQ (English)        | 2020-10-12 | pdf (241 KB) |
    And the published "files.json" of "discover" gives "FAQ GO.pdf" the url "https://www.eex.com/fileadmin/Docs/FAQ%20GO.pdf"
    And the published "files.json" of "discover" gives "20261119_GO_2026_GLOBAL_Results.zip" a url on the "eex" service ending "/fileadmin/GO/20261119_GO_2026_GLOBAL_Results.zip"
    And the published "page.html" of "discover" includes "GO 2026 Global Results"

  Scenario: The page is read again on every run, since EEX publishes new files
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <a href="/fileadmin/GO/results.zip">zip</a>
      """
    And I ran "soldera run pipeline.yaml"
    When I run "soldera run pipeline.yaml"
    Then it succeeds
    And it prints "discover: eex-french-auction-page@1.0.0 succeeded: 1 items, 1 built, 0 cached, 0 failed"
    And the "eex" service was asked "GET /en/markets/energy-certificates/french-auctions-power" 2 times

  Scenario: A page EEX cannot serve fails the stage and says what it answered
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 503
    When I run "soldera run pipeline.yaml"
    Then the exit code is 1
    And stderr mentions "discover: page failed: HttpError"
    And stderr mentions "answered 503"

  Scenario: A page that links to no files fails, since its layout has most likely changed
    Given the "eex" service answers "GET /en/markets/energy-certificates/french-auctions-power" with 200 and:
      """
      <h2>Guarantees of Origin Data</h2>
      <p>Results are now published elsewhere.</p>
      """
    When I run "soldera run pipeline.yaml"
    Then the exit code is 1
    And stderr mentions "has the page layout changed?"
