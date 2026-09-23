# Model protocol v1.1 — fixed specification, corrected identity handling

User clarification, 23 September 2026: build our own statistical model from Betfair historical data, informed by their published approach. Fresh Hub ratings are optional comparisons, not the model or a dependency. This supersedes the external-baseline/no-new-training instructions in the original project plan.

## First implemented model

PuntingPowerAI History v1: a regularised race-level conditional logistic model. All runners in a race share a softmax denominator, so probabilities sum to one. Fit coefficients by winner log loss, with equal weight per race. Compare against uniform probabilities and final BSP as an explicitly hindsight-only market diagnostic. No profitability claim or live selection from final BSP.

Betfair describes runner probabilities and assessed prices based on horse, jockey, trainer and sectional information supplied by Punting Form. Their exact fitted model and underlying proprietary form inputs are not published in the public pages checked. We can implement our own approach; we cannot claim to reproduce theirs.

- [Ratings model explanation](https://www.betfair.com.au/hub/racing/horse-racing/predictions-model/)
- [Top 5 feature overview](https://www.betfair.com.au/hub/models/top-5-predictions/)
- [Betfair historical CSVs](https://betfair-datascientists.github.io/data/dataListing/)
- [Betfair warning about BSP leakage](https://betfair-datascientists.github.io/tutorials/analysingAndPredictingBSP/)
- [Backtesting guide](https://betfair-datascientists.github.io/tutorials/backtestingRatingsTutorial/)

## Data and chronology

Use public Australian thoroughbred WIN market archives only. 2024 is a history warm-up. Train on 2025-01-01 through 2026-05-31. June 2026 is chronological development validation. July–August 2026 is a chronological diagnostic, **not an untouched holdout**: the earlier research task has already inspected this period. The next genuine holdout is predictions logged prospectively from 2026-09-23 onward, after this specification is frozen. No historical September results are opened in this first experiment.

No tuning against the July–August diagnostic. Fixed L2 penalty 0.01, maximum 300 optimiser iterations. Fit feature mean/scale on training runners only. Persist coefficients, training bounds, source hashes, schema version and metrics. Exclude whole markets with conflicting duplicate runners, invalid BSP, unknown outcomes, multiple winners/dead heats, mismatched identity, or non-Australian jurisdiction. Expose exclusion counts.

## Features available before the target race

For each runner, use only starts from earlier calendar dates. Same-day results never update another race's inputs. Horse identity uses exact normalised names within the Australian thoroughbred archive, retaining country suffixes. Same-day duplicates are not merged. Upcoming Racing Australia names require an exact match. Ambiguous/unseen names use a cold-start prior and are flagged. This is an explicit identity assumption; authoritative cross-provider horse IDs, name reuse and omitted country suffixes remain unresolved.

Correctness amendment after the initial run: selection IDs in this export change across starts (verified using Alabama State and My Gladiola). v1 incorrectly treated them as persistent horse IDs, yielding mostly cold starts. Its model, metrics and projections are superseded. v1.1 fixes the join and adds regression tests without changing features, splits, penalty or selection policy. All previously inspected periods remain diagnostic.

Features: log prior start count; smoothed prior win rate; mean negative log BSP over previous five starts; last-start negative log BSP; mean win-minus-normalised-BSP expectation over previous five starts; log days since last start; distance difference from last start; missing-history indicator. Historical BSP is used **only from previous races** as a market-informed performance proxy. Current-race BSP, results, preplay aggregate prices/volume, archive model ratings, and post-race speed fields never enter features. No jockey/trainer/sectional claims: those point-in-time inputs are absent from these files.

## Evaluation and limits

Report winner log loss, race-summed Brier score, top-ranked win rate, calibration bins and race/date counts. Show paired daily-block bootstrap interval for the log-loss difference against the hindsight BSP diagnostic (500 resamples, seed 20260923). Display after-commission paper returns only as a settlement diagnostic for one unit on the model leader, under explicit 0%, 5% and 8% scenarios; BSP is a settlement reference, not an observed earlier executable quote. No stakes or bets are placed.

This is a deliberately small **history-based statistical baseline**, not Betfair's Punting Form model. Missing September history prevents treating projections for 26–27 September as current. Reports must flag that gap and block actionable model candidates until the historical coverage is refreshed and model quality reviewed. A weak benchmark result is a finding, not a reason to tune on the diagnostic period.
