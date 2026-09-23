# Insider Trades

A tracker for insider trades on Oslo Børs and Nasdaq Stockholm. It pulls the
official disclosures, normalises them into one schema, stores them in SQLite, and
serves a small web app with filters, a summary, and a price chart around each trade.

## Data sources

| Market | Source | Format | Notes |
|---|---|---|---|
| Norway | Oslo Børs NewsWeb, category 1102 (mandatory notification of trade, primary insiders) | Free text announcements | Parsed with heuristics; each trade carries a confidence score and the original text |
| Sweden | Finansinspektionen's insider register (insynsregistret) CSV export | Structured | One row per transaction |

Share prices come from Yahoo Finance and are cached for six hours.

## Quick start

```bash
pip install -e ".[dev]"
insider-trades sync          # fetch the last 60 days from both markets into insider_trades.db
insider-trades serve         # http://127.0.0.1:8000
```

The server also syncs on startup and every 30 minutes. Both can be changed with
environment variables, see `.env.example`.

To try the interface without network access, seed the database from the recorded
test fixtures:

```bash
INSIDER_DB=demo.db python scripts/seed_fixtures.py
INSIDER_DB=demo.db INSIDER_SYNC_ON_STARTUP=0 insider-trades serve
```

### Docker

```bash
docker build -t insider-trades .
docker run -p 8000:8000 -v insider-data:/data insider-trades
```

## CLI

```
insider-trades sync [--market NO|SE] [--since YYYY-MM-DD]
insider-trades serve [--host H] [--port P] [--reload]
insider-trades export [--market NO|SE] [--type buy|sell|...] [--since YYYY-MM-DD] > trades.csv
```

Sync is incremental: it restarts three days before the newest stored announcement
so corrections are picked up. Trades are upserted by source id, so re-running is safe.

## HTTP API

| Endpoint | Purpose |
|---|---|
| `GET /api/trades` | List trades. Filters: `market`, `type`, `q`, `issuer`, `from`, `to`, `min_value`. Paging: `limit`, `offset`. Sorting: `sort`, `order`. |
| `GET /api/trades/{id}` | One trade with the original text |
| `GET /api/summary?days=30` | Counts and values by type, most bought and sold issuers, last sync per market |
| `GET /api/issuers?q=` | Issuer autocomplete |
| `GET /api/prices/{id}` | Daily closes from 30 days before the trade to today, plus the change since the trade |
| `POST /api/sync` | Run a sync now, optionally for one `market` and from a `since` date |
| `GET /api/health` | Liveness |

Interactive docs are at `/docs`.

## Trade types

`buy`, `sell`, `option_exercise`, `allotment` (share programmes, vesting, grants),
`other` (share lending, transfers, pledges) and `unknown` when the text could not
be classified. For Norway, rows with confidence below 60% are dimmed in the table.
The details panel always shows the original announcement so a reader can verify.

## Layout

```
insider_trades/
  models.py          Trade schema shared by both markets
  store.py           SQLite storage, queries, summary, price cache
  sources/           oslo_bors.py and finansinspektionen.py
  parsers/           norway.py (free text) and numbers.py (Nordic number and date formats)
  prices.py          Yahoo Finance client
  sync.py            Incremental sync
  api.py             FastAPI app
  cli.py             Command line
  web/               Frontend, plain HTML, CSS and JavaScript
tests/               pytest suite; fixtures include a recorded Oslo Børs response
scripts/             seed_fixtures.py
```

## Development

```bash
make test
make lint
```

## Known limitations

- The Norwegian parser is heuristic. Announcements that only reference a PDF
  attachment get a type from the title and no quantity or price. The source link
  leads to the attachment.
- The Finansinspektionen export has no documented contract. The column mapping
  accepts both the Swedish and English site and is tolerant of encoding and
  delimiter changes, but a format change on their side will need a parser update.
- Yahoo Finance is an unofficial price source and may rate limit.
