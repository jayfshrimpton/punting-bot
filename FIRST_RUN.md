# First working build — 23 September 2026

**Our own statistical model is trained, and both official weekend cards have local reports. This remains an experimental research build.**

## What works

- Download and hash verification for Betfair's free 2024–August 2026 thoroughbred archives.
- Our fitted race-level probability model, chronological evaluation, calibration and uncertainty reports.
- Official fields: Rosehill 26 September, 10 races / 127 acceptors; Caulfield 27 September, 9 races / 108 acceptors.
- Immutable SQLite/JSON observations, manual research/quote/model imports, Markdown/HTML reports, cutoff and freshness checks.
- 22 regression tests, including current-race and same-day outcome leakage, unstable horse selection IDs, scratchings and invalid joins.

## Corrected model result

> **Correction, 23 September 2026 (v1.2).** The v1.1 run below had two defects. It silently excluded every April 2025 race, because that archive file writes dates as D/MM/YYYY. It also required exact official-name matches, so 51 of the 226 active weekend runners with a country suffix or an apostrophe became cold starts. After retraining with both fixed:
>
> - 24,056 training races.
> - July–August model log loss 2.0788 (equal chance 2.2465, BSP 1.7751).
> - Top-pick win rate 23.8%.
> - BSP paper return −2.58% at 5% commission (95% interval −13.26% to +8.24%), and −4.91% at 8%.
> - Cold starts in the 14 projected weekend races fall from 36 to 2.
>
> One extra month of training moved the return estimate by 2.6 points, well inside its interval. Treat it as noise, not break-even. The v1.1 figures below are kept for the record and are superseded; retrain and re-project before use.

PuntingPowerAI History v1.1 trained on **22,603 races** from January 2025 through May 2026, after using 2024 as a history warm-up. June validation contains 1,386 races. July–August diagnostics contain 2,834 races and are **not an untouched holdout**.

| July–August diagnostic | Result |
|---|---:|
| Model winner log loss | 2.0797 |
| Equal-chance log loss | 2.2465 |
| Final BSP hindsight log loss | 1.7751 |
| Model top-pick win rate | 24.0% |
| BSP paper return, 5% assumed commission | +0.05% |
| Daily-block 95% return interval, 5% commission | −10.92% to +10.75% |
| BSP paper return, 8% assumed commission | −2.35% |

The model beats equal chances but trails the final-price market's probability quality. Returns are inconclusive, and commission matters. This is not evidence of a profitable live strategy. The original selection-ID-based v1 result is superseded: IDs changed across starts and fragmented histories. v1.1 fixes that correctness error, without changing features, regularisation or date splits.

Model artifact SHA256: `91a7566e25ae3bbbe538b2118141bf44f3d6c15273e311c2a30705d0cf69f0a1`. The full fitted model, source hashes and statistics are kept locally under `data/model/`, outside Git. A future rerun produces a new artifact with its own capture time.

## Weekend limitations

Reports represent all **19 races / 235 acceptor records**. Experimental model projections exist for 14 races. Five races retain missing probabilities because emergency starters are unresolved. Historical inputs end 31 August; missing September starts and exact-name matching limitations are prominently flagged. These projections cannot generate actionable candidates.

Reviewed research currently covers both first races, BOM forecasts, Guest House's trainer interview and Manikato context. Other race-specific research remains incomplete. The source matrix records failures, stale pages and manual-import needs. Current executable provider prices, size/limits and account-specific commission are unavailable; no invented quotes or value claims are displayed.

The reports preserve model numbers, source opinions and user decisions separately. External Betfair Hub ratings are optional. Jev, purchases, deployment and betting are absent.

## Next dependency

Improve the data before increasing model complexity: refresh historical coverage through the latest completed day, establish reliable cross-provider horse IDs, and obtain timestamped form/sectional and pre-race market inputs. The free archive supplies a useful baseline but not all inputs used by Betfair's published Punting Form models. See [the model protocol](MODEL_PROTOCOL.md) and [run instructions](README.md).
