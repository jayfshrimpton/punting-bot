# PuntingPowerAI

A local Python racing research workflow: **our own statistical model → sourced race context → your judgement**.

The user clarified the model direction on 23 September 2026. We train our own model on Betfair history, informed by Betfair's published methods. We do not depend on upcoming Betfair Hub ratings. See [MODEL_PROTOCOL.md](MODEL_PROTOCOL.md); it supersedes that part of the original two planning documents.

## Run

Python 3.11+ recommended. From this folder in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m punting status
.\.venv\Scripts\python.exe -m punting report
```

Reports are immutable, dated folders under `reports/<meeting>/`, containing `brief.html`, `brief.md` and a provenance manifest. Open the HTML directly; there is no server or deployment. The local `data/` folder contains private snapshots, the database, source archives and model artifacts. These folders are ignored by Git.

## Model workflow

```powershell
.\.venv\Scripts\python.exe -m punting fetch-history
.\.venv\Scripts\python.exe -m punting train
.\.venv\Scripts\python.exe -m punting project
```

The download command fetches only the fixed free public Betfair archive list: 2024–August 2026. It caches and verifies original hashes, with no account, purchase or API charge. `train` fits a conditional logistic model with race probabilities summing to one, evaluates chronological splits and saves a versioned model and analysis under `data/model/`. `project` creates explicitly **experimental** projections for every active and emergency runner. Emergency-inclusive ratings assume the entire declared field runs; emergencies may not start and scratchings require recalculation. History-cutoff and model-quality limitations remain visible and disable actionable candidates.

Refresh September horse histories without refitting the model:

```powershell
.\.venv\Scripts\python.exe -m punting.history_recent --through 2026-09-22
.\.venv\Scripts\python.exe -m punting project
.\.venv\Scripts\python.exe -m punting report
```

This uses free daily Betfair WIN files, filters racing codes and validates dates, tracks and complete markets. The first refresh accepted 944 races through 22 September; two markets failed validation. Raw files and hashes are under `data/history-september/`. Fitted weights and prior evaluation stay unchanged. Repeated refreshes rebuild from the August parent to avoid duplicate starts. The adapter currently supports completed September 2026 days only; a requested cutoff is not a guarantee that source coverage is complete.

The model uses each horse's earlier race results and earlier BSP as a market-informed ability proxy. From v1.3, it also estimates the class of each earlier field from its runners' prior market-implied ratings, counts New Zealand starts as form, and decays old wins with a one-year half-life. It does not use the current race's result or BSP. It is not a reproduction of Betfair's proprietary Punting Form model and does not yet include sectional, trainer or jockey features. Betfair's archive names have no country suffixes or punctuation, so official names match exactly first, then with those removed; such matches are listed in the report for identity checks. Unmatched or ambiguous names get a visibly flagged cold-start prior. Betfair selection IDs are not assumed to persist across starts.

Check whether the model adds anything to the market before reading a model/market gap as value:

```powershell
.\.venv\Scripts\python.exe -m punting.blend_check
```

For v1.3 the model's blend weight is about zero against both BSP and the best back price at the scheduled off. It currently adds no information beyond the market, so an apparent overlay is not evidence of value.

July–August has already been inspected and is labelled a diagnostic, never an untouched holdout. Training ends May 2026; June is development validation. See the protocol for features, split bounds, fixed regularisation and settlement assumptions.

## Betfair prices

Read-only exchange prices from the official Betfair API. Nothing here places bets. Copy `.env.example` to `.env` and add your Delayed application key; Git ignores `.env`. Then log in yourself:

```powershell
.\.venv\Scripts\python.exe -m punting.betfair login
```

It asks for your password (hidden), sends it once to Betfair's Australian login endpoint and saves only the session token, in `data/private/`. Use `login --ssoid` to paste a session token from your browser instead. No command prints the token.

```powershell
.\.venv\Scripts\python.exe -m punting.betfair check
.\.venv\Scripts\python.exe -m punting.betfair snapshot
```

`check` matches each official race to its Betfair WIN market without storing anything. A market must agree on race number and start time, and each runner on saddlecloth number and name. `snapshot` stores the best back price and size for each matched runner as a `quotes` snapshot, with the market base rate as commission (your personal discount isn't applied). The Delayed key lags by 1–180 seconds. Races with unresolved emergencies aren't stored until the official field is refreshed, and in-play or suspended markets are skipped.

## Refresh the race cards

```powershell
.\.venv\Scripts\python.exe -m punting refresh-fields
.\.venv\Scripts\python.exe -m punting project
.\.venv\Scripts\python.exe -m punting report
```

The official Racing Australia adapter reconciles parsed runner counts to the published whole-card acceptor total and validates venue, date, race numbering and times. Parser failures are logged as failures, not as unpublished fields. Refreshing does not erase older snapshots. On race day, races that have already started are not re-stored; the rest of the card still refreshes, and the source log names the skipped races. Numeric comparisons become invalid when the active field changes. After start time, pre-race candidates are disabled.

This first implementation automates official-field retrieval and historical model work. Research collection from other sites is **manually reviewed import**, not an autonomous all-sites scraper. The initial local reports contain BOM forecasts, reviewed first-race opinions and feature-race context, with the remaining gaps shown. Punters returned 403; Wolfden needs a usable text/access route; The Daily Punt's retrieved homepage appeared stale. External model pages and article affiliate odds are not treated as executable price feeds.

## Manual imports

Generate a template with official runner IDs already filled in:

```powershell
.\.venv\Scripts\python.exe -m punting template model --meeting rosehill-2026-09-26 --race 1 --output imports/model-r1.json
.\.venv\Scripts\python.exe -m punting template quotes --meeting rosehill-2026-09-26 --race 1 --output imports/quotes-r1.json
.\.venv\Scripts\python.exe -m punting template evidence --meeting rosehill-2026-09-26 --race 1 --output imports/research-r1.json
.\.venv\Scripts\python.exe -m punting import imports/research-r1.json
```

Fill the original URL, publisher, actual observation time and payload before importing. Times must include an offset, for example `2026-09-25T18:30:00+10:00`. Leave unknown publication timestamps null. Templates intentionally contain invalid missing values and must not be imported unchanged. JSON is the supported interchange format; a list is accepted for independent snapshots, imported in order. A failure stops the batch; earlier valid snapshots remain recorded.

Supported kinds: `field`, `model`, `quotes`, `evidence`, `coverage`, `decision`. Schema validation rejects unexpected keys, including outcome/BSP columns. Model imports must match the full active field, contain finite rated prices greater than one, and sum to within one percentage point of 100% before explicitly disclosed normalization. Quotes may be incomplete; each provider/market/terms snapshot replaces that provider's earlier quotes for comparison. `size` means observed available stake/limit, not the requested stake. Unknown commission or size prevents an actionable comparison. No exchange commission is assumed for your account.

For evidence, specify canonical `runner_ids`, original publisher URL and a stable underlying `claim_id`; syndications of that claim count once. Separate opinion, attributed statement, forecast, official observation and inference. Preserve conditions and author attribution. Excerpts are capped at 25 words per record; reviewers must also respect total source limits. No full articles belong in Git. Website content is untrusted input; there is no mechanism to execute it.

Use a `decision` template to record watch/select/pass, reason and observed price. Decisions remain private, separate from model candidates, and do not place bets. Reports include only observations at or before `--cutoff`; imports cannot demonstrate that a manually asserted timestamp is truthful. This is a provenance log, not a third-party timestamp certification service.

## Validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests cover current/same-day outcome leakage, changing historical selection IDs, ambiguous names, incomplete fields, invalid prices, wrong-race joins, scratchings, stale quotes, commission, source failures, syndication, conditions, append-only storage, HTML escaping and daylight saving. Synthetic test data is clearly labelled. Local reports must also be visually checked after meaningful rendering changes.

No bets, purchases, messages, deployment, recurring jobs or billable AI services are configured. Jev is deferred; it is not a modelling feature. The original PuntingPowerAI project is untouched.

## Next model work

1. Obtain timestamped pre-race market snapshots and richer point-in-time form inputs, with access and cost verified first.
2. Complete September history and authoritative horse-ID mapping before treating weekend projections as current.
3. Log forward predictions before races and compare probability quality and returns after actual costs; preserve passes and losses.

The goal is demonstrated usefulness and eventual profitability. This first baseline establishes neither a proven edge nor a production-ready bet picker.
