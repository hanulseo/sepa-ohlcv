# SEPA OHLCV Market Scanner

Python-based US/KR daily OHLCV scanner and quantitative trend/relative-strength/VCP/volume/pivot scoring. No brokerage API key is required.

The repository is **public**. Do not commit portfolio positions, cost bases, API tokens, or other confidential information.

Once the workflow is installed, open **Actions → SEPA Market Scan → Run workflow**. Download its `sepa-analysis` artifact to inspect `report.json`, `scores.csv`, and available OHLCV CSVs.

The scheduled times are 08:00 / 19:00 Asia/Seoul (23:00 / 10:00 UTC). GitHub scheduled runs may be delayed.

Scores are computed only from actual retrieved OHLCV; incomplete verification never results in BUY NOW or BUY WAIT. The scanner is a technical research tool, not a trade execution service.
