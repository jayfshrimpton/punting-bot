# Model protocol v1.3 — fixed specification, class-adjusted form and New Zealand starts

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

Use public Australian thoroughbred WIN market archives only; from v1.3, New Zealand starts in the same archives count as horse form but are never training or evaluation targets. 2024 is a history warm-up. Train on 2025-01-01 through 2026-05-31. June 2026 is chronological development validation. July–August 2026 is a chronological diagnostic, **not an untouched holdout**: the earlier research task has already inspected this period. The next genuine holdout is predictions logged prospectively from 2026-09-23 onward, after this specification is frozen.

User amendment, 23 September: September results are required for current horse histories. Free daily Betfair Australian WIN files now refresh histories through 22 September, without refitting coefficients, scaling, or historical evaluation. Daily publication filenames are not meeting dates: use the local date in the meeting label and cross-check the event date. A thoroughbred race-type allowlist and unambiguous track/state mapping exclude harness and unknown records. Whole-market settlement and BSP checks still apply. An overlap audit matched 236 August runner records with no name, result or BSP discrepancies beyond monthly rounding. The first refresh accepted 944 races; two thoroughbred markets failed settlement/completeness validation. Later days need another refresh before the weekend. Raw source files and hashes stay separate from the fixed training dataset.

User amendment, 23 September: rank emergencies too. An explicitly experimental `includes_emergencies` snapshot covers all active and emergency runners, summing to one under a hypothetical full declared field. Emergencies may not start; scratchings require new projections. Quotes still require resolved starters and experimental scenarios cannot generate actionable candidates.

Editorial rule: popular horses and trainers attract more coverage. Mention counts, repeated articles and absent commentary never change model probabilities. Source opinions are attributed context, not confidence scores.

No tuning against the July–August diagnostic. Fixed L2 penalty 0.01, maximum 300 optimiser iterations. Fit feature mean/scale on training runners only. Persist coefficients, training bounds, source hashes, schema version and metrics. Exclude whole markets with conflicting duplicate runners, invalid BSP, unknown outcomes, multiple winners/dead heats, mismatched identity, or non-Australian jurisdiction. Expose exclusion counts.

## Features available before the target race

For each runner, use only starts from earlier calendar dates. Same-day results never update another race's inputs. Horse identity uses exact normalised names within the Australian and New Zealand thoroughbred archive. The archive's names carry no country suffix, punctuation or accents. Same-day duplicates are not merged. An upcoming Racing Australia name first needs an exact match, then a unique match with its suffix, punctuation and accents removed; those matches are listed for identity checks. Unseen names, names matching several archive names, and different runners in one meeting resolving to one archive name use a flagged cold-start prior. This is an explicit identity assumption. Because the archive omits suffixes, a local and an imported horse sharing a name share one archive history; this, name reuse and the lack of authoritative cross-provider horse IDs remain unresolved.

Correctness amendment after the initial run: selection IDs in this export change across starts (verified using Alabama State and My Gladiola). v1 incorrectly treated them as persistent horse IDs, yielding mostly cold starts. Its model, metrics and projections are superseded. v1.1 fixes the join and adds regression tests without changing features, splits, penalty or selection policy. All previously inspected periods remain diagnostic.

Second correctness amendment, 23 September 2026 (v1.2). The April 2025 archive file writes dates as D/MM/YYYY. v1.1 silently excluded all 1,455 of its races under an invalid-price label, which removed a month of training races and left a gap in every horse's history. v1.2 parses both date formats and counts date failures separately. Separately, v1.1 required exact official-name matches, so every imported horse and every name with an apostrophe became a cold start (51 of 226 active weekend runners). Features, splits, penalty and selection policy are unchanged. v1.1 metrics and projections are superseded; retrain before projecting.

Third amendment, 23 September 2026 (v1.3), at the user's request after reviewing the weekend summary. The findings came from the matched histories of weekend runners before any v1.3 fit:

- **New Zealand form was missing.** Lara Antipova's four New Zealand wins, including a Group 1, were excluded, leaving two Australian starts. New Zealand thoroughbred starts in the same archives now update horse histories. The fit learns a weight on each horse's New Zealand share of recent starts. Targets, splits and market exclusions are unchanged.
- **The model was class-blind.** Previous-race BSP measures strength only within that race's field. A short price in a weak maiden therefore outranked a longer price in a Group 1: Guest House won the Golden Slipper at 14.17. Each past race now gets a class level from collateral form. A start's rating is the log of its normalised BSP probability plus the log-sum-exp of the field's prior ratings. An unrated horse counts as 0, and a horse's prior rating is the mean over its last five starts. A race's class is the log-mean-exp of those prior ratings, which doesn't depend on field size. Two features are added: mean class over the last five starts, and last-start class. No race titles, prize money or post-race fields are used.
- **Old wins counted fully.** Treasurethe Moment's career record (11 wins from 21, mostly before 2026) outweighed her recent form. The smoothed win rate now decays with a 365-day half-life.

The half-life and the unrated rating were fixed before fitting and are not tuned. The penalty, iteration limit, training-only scaling, splits, exclusions and same-day lag are unchanged. June development validation decides whether v1.3 replaces v1.2. July–August stays a diagnostic, reported once and never tuned against. If v1.3 is adopted, v1.2 projections are superseded and the September refresh reruns on v1.3 histories.

Result: June log loss was 2.0792, against 2.1063 for v1.2 on the same 1,386 races, so v1.3 is adopted. Brier score improved from 0.8555 to 0.8494 and the top-ranked win rate from 22.2% to 23.3%. The July–August diagnostic moved from 2.0788 to 2.0334, reported once. The fitted class weights (recent 0.30, last 0.39) are among the largest. The New Zealand share weight is about zero, so New Zealand form counts at face value.

Features: log prior start count; smoothed prior win rate, decayed with a 365-day half-life from v1.3; mean negative log BSP over previous five starts; last-start negative log BSP; mean win-minus-normalised-BSP expectation over previous five starts; log days since last start; distance difference from last start; missing-history indicator; from v1.3, mean class over the previous five starts, last-start class, and the share of the previous five starts run in New Zealand. Historical BSP is used **only from previous races** as a market-informed performance proxy. Current-race BSP, results, preplay aggregate prices/volume, archive model ratings, and post-race speed fields never enter features. No jockey/trainer/sectional claims: those point-in-time inputs are absent from these files.

## Evaluation and limits

Report winner log loss, race-summed Brier score, top-ranked win rate, calibration bins and race/date counts. Show paired daily-block bootstrap interval for the log-loss difference against the hindsight BSP diagnostic (500 resamples, seed 20260923). Display after-commission paper returns only as a settlement diagnostic for one unit on the model leader, under explicit 0%, 5% and 8% scenarios; BSP is a settlement reference, not an observed earlier executable quote. No stakes or bets are placed.

This is a deliberately small **history-based statistical baseline**, not Betfair's Punting Form model. Reports show the actual history cutoff, excluded-market gaps and emergency assumptions. Updating history does not establish model quality: experimental projections remain unable to generate actionable candidates. A weak benchmark result is a finding, not a reason to tune on the diagnostic period.

Market-blend check (`python -m punting.blend_check`): fit p ∝ exp(a·log p_model + b·log p_market) on training races and score June. A gap between the model's rating and the market price counts as evidence of value only if the model's weight a is reliably above zero. For v1.3, a = −0.004 against BSP and a = 0.001 against the best back price at the scheduled off. Blending leaves June log loss unchanged (95% intervals within ±0.0002). The model adds no information beyond the market: an apparent overlay against a late price is model error, not value.
