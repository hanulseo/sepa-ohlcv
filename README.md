# SEPA / Minervini Whole-Market Scanner

Scheduled scans: 08:00 and 19:00 Asia/Seoul; GitHub may delay the execution.

## Exchanges
- United States: NASDAQ, NYSE, AMEX exchange listings via FinanceDataReader
- Republic of Korea: KOSPI and KOSDAQ listings via FinanceDataReader
- Exchange listings are partitioned into 16 parallel GitHub Actions jobs.
- All eligible listed symbols are attempted; some providers may refuse or omit symbols.
- ETF, ETN, warrants, and special instrument exclusion is heuristic and subject to verification.

## Reports (download sepa-whole-market from the Actions run)
- report.md: Company name (ticker), including Korean company names, US top six / KR top four
- full_universe.csv: listing of discovered securities
- coverage.csv: per-security retrieval outcomes, failures, and exclusions
- coverage_summary.json: actual total listed, attempted, scored and all-shard completion
- all_scores.csv: scored securities, ranked across both markets
- top10.csv: the high-scoring ten with company names
- all_approved.csv: quantitative buy-screen positives, not independent chart confirmation

## Data and privacy
- Price history: yfinance and fallback FinanceDataReader; benchmarks S&P 500, KOSPI, KOSDAQ.
- 20+ session short-history proxy is differentiated from a 200-day trend score.
- 252 observed sessions are needed for verified 52-week low +100%; unavailable gates block BUY.
- VCP is a computed proxy, not discretionary pattern verification.
- This repository is PUBLIC. Do not commit personal positions, cost basis or API secrets.
- A successful GitHub job alone is not proof that every listed security was successfully scored. Consult the coverage report.
- SEC/DART financials and retrospective recommendation checking are not included yet.