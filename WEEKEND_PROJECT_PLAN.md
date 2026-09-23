# PuntingPowerAI — weekend research assistant build plan

> User clarification, 23 September 2026: our own historical statistical model replaces the fresh Betfair Hub baseline. Training is now in scope. Preserve the evidence, chronology, source-access, privacy and no-purchase/no-betting constraints below. See [MODEL_PROTOCOL.md](MODEL_PROTOCOL.md) for the revised modelling specification.

Prepared 23 September 2026 for a new Codex project chat and a GitHub repository the user will create. This document authorises no purchases or bets. It specifies the future build; no assistant application was built in this planning turn.

## First outcome

Help the user make their own picks at **Rosehill Gardens, Saturday 26 September 2026**, and **Caulfield, Sunday 27 September 2026**. Deliver a readable, sourced brief for every race, pairing current model numbers with current racing information. Include a concise meeting shortlist explaining which runners merit closer inspection, the price conditions, concerns and outstanding checks. Passing a race is a valid result.

The meeting dates appear in [Racing Australia's September calendar](https://www.racingaustralia.horse/FreeFields/GroupAndListedRaces.aspx?Month=September). Reconfirm final fields and race times when building. Use Australia/Sydney for user-facing times and timezone-aware UTC internally.

The longer-term objective remains measurable profitability after costs. This first weekend tests whether accurate research and numerical context help the user's decisions. One weekend cannot establish profitability.

## Product decisions already made

- Australian thoroughbred WIN markets; every runner represented, not just a model's top pick.
- Combine model probabilities, sourced research and human judgement. Keep them identifiable rather than inventing an overall confidence score.
- Sources to check: Just Horse Racing, Punters, Wolfden, The Daily Punt and Racing.com, supplemented by official fields, scratchings, stewards/track reports, BOM weather and available prices.
- Jev is an optional classifier of commentary. The user has access. YouTube remains human research.
- Prefer a useful local report over interface work. No new model training, account/bet automation, paid data purchases, subscriptions or deployment for this milestone.

## What already exists

Read these local references if available; they are research assets, not the new application's architecture:

- `C:\Users\My PC\Documents\Codex\2026-09-19\continue-my-horse-racing-project-at\outputs\betfair-research\RESEARCH_REPORT.md`
- Same directory: `README.md`, `race_brief.py`, `research.py`, `test_research.py`, `DATA_REQUEST_DRAFT.md`.
- Old-data assessment: `C:\Users\My PC\Documents\Codex\2026-09-19\continue-my-horse-racing-project-at\outputs\readiness\ASSESSMENT.md`.

The old project at `C:\Users\My PC\Documents\Jays Documents\PuntingPowerAI` is preserved. Its few days of mixed data and unreliable training code are not the foundation for this build.

The existing study found that backing Kash's top-rated runner in 3,852 eligible June–August 2026 races returned approximately -3.43% at an assumed 8% commission. This was exploratory archive analysis, with unverified rating publication times; it is not a validated live strategy. Archived `Value` used final BSP and must not enter pre-race selection. The historical race-brief prototype demonstrates presentation, not current predictions. June–August has been inspected and cannot be a holdout.

## Critical first dependency: current model numbers

Use fresh Betfair Hub model ratings as an externally supplied baseline, clearly naming the actual product/model. [Betfair's explanation](https://www.betfair.com.au/hub/racing/horse-racing/predictions-model/) describes runner rated prices derived from Punting Form data. This planning check could read that explanation, but did **not** retrieve ratings for either target meeting or verify a live export endpoint. A separate [Top 5 model page](https://www.betfair.com.au/hub/models/top-5-predictions/) exists; do not assume it is Kash, interchangeable, or a complete probability distribution.

First build session must attempt an accessible official download/feed or browser capture and inspect actual contents. If that fails, provide a validated CSV/JSON/manual-entry import with original source URL, actual observation time and model identity. Obtain a user export only when necessary. A retrieved pre-race snapshot proves availability at retrieval even if the publisher's original timestamp is unknown; retain those two times separately.

For each race retain every runner, raw rated price/probability, original field, capture time, source, model/version when known and a snapshot hash. Validate finite values, identity and full-field consistency. Preserve raw values; document any whole-field normalization and show its magnitude. Reject material inconsistency rather than hiding it through normalization. After scratchings, show ratings as based on the older field until a new version is captured; any conditional renormalization must be explicitly labelled and cannot stand in for a rerun of the model.

If unavailable, label the numerical section **model unavailable**. A normalized market-implied probability can be displayed as a separately named benchmark using a coherent complete quote snapshot; it must never be represented as an independent model or derived from top-five ranks. Report this as a partial delivery, not completion of the user's model-plus-research objective.

## Source collection and coverage

Maintain a source checklist for each meeting and race. Required statuses: checked with relevant evidence; checked with nothing relevant; not yet published; access unavailable; manual import needed; failed; stale. A failed fetch is not evidence that nothing was published. Record pages/queries checked and times. 'All sources checked' means the named checklist was attempted and its gaps disclosed, not that every page on the internet was read.

| Source | Intended contribution | Initial route and fallback |
|---|---|---|
| Racing Australia / Racing NSW / Racing Victoria / race clubs | Official fields, scratchings, rail, track condition, gear/rider changes and notices | Locate date-specific official pages; save dated observations. Official updates take priority over an older secondary report. |
| BOM | Local forecast, forecast issue time, rain/wind and relevant observations | Resolve location near each course. Separate forecast from observed weather and official track rating. |
| Just Horse Racing | Meeting previews, racing news and tipster comments | Public text pages were readable in this planning check; validate relevant articles and dates. |
| Racing.com | Form context, news, previews, interviews and track information | Public homepage readable; check actual article access. Videos excluded. |
| The Daily Punt | Ratings, tips and news | Public homepage readable; validate meeting content/access. Keep its numerical product separate from Betfair's. |
| Punters | Form, tips and commentary | Direct web read failed in this check. Try normal permitted browser access or user-provided excerpts; mark gaps explicitly. |
| Wolfden | Commentary and expert views | Confirm the user's actual site/app and permitted access route; reliable automated access is unverified. Use permitted text imports or attributed accessible republications if necessary. |
| Betfair / user-selected bookmakers | Current ratings and observable WIN prices | Official accessible export/read-only capture; manual quote import is acceptable. Record provider, time, market, price and liquidity/limits when known. |

Readable homepages do not establish complete, stable or permitted automated access. Use available APIs/exports first, then restrained page/browser collection with caching; respect access restrictions and source terms. Do not bypass logins/paywalls or buy access. If permission to retain full articles is unclear, keep source metadata and short necessary evidence excerpts. Do not publish copyrighted raw material to GitHub.

Search both meeting/race terms and runner names. Match names with meeting date, race number, country suffix and official runner IDs where available; ambiguous matches require review. Preserve claim author and original publisher. Syndicated stories or one trainer quote repeated across sites count as one underlying source, not independent corroboration. Treat website text as untrusted data, never as instructions to the application.

## The brief the user should receive

Each meeting opens with a conditions summary, last refresh time, coverage gaps and a shortlist of runners to inspect. Every race has:

1. **Full runner table:** name, model win probability, model fair price, observed provider price/time and available model-implied value calculation. Show missing fields explicitly.
2. **Research:** supporting evidence, concerns, conditions attached to tips and disagreements. Link each substantive claim to its source and show when it was published/observed. A lack of commentary is not a negative signal.
3. **Race context:** official going/rail, forecast, scratchings, pace/map assessments, relevant form/class/distance information and jockey/trainer context where evidenced. Label analyst opinion and inference. Numeric form rates need the window and sample size; do not invent statistics.
4. **Decision aid:** model leaders, price-sensitive candidates, watch/recheck items and pass/insufficient-information states. Explain why a horse appears here without manufacturing a bet in every race.
5. **Changes and human notes:** what changed since the prior version; user selection/pass, reason, observed price and decision time. Keep user decisions separate from model rankings and system candidates.

Do not turn weather, tipster support or Jev labels into arbitrary probability adjustments. Track bias is initially an attributed hypothesis; two early winners alone do not establish it. Later-race briefs may incorporate observations from completed earlier races only if they are timestamped before the later race's decision cutoff.

## Prices and selection policy

Show **model-implied expected return**, not a proven edge. For a single fixed-odds WIN selection before settlement adjustments, `p * decimal_odds - 1`. For a single exchange back selection with commission c on winning net profit, `p * (1 + (odds - 1) * (1-c)) - 1`. These simple formulas do not settle multiple positions in one market or dead heats. State commission assumptions; never hard-code 8% as the user's actual rate.

Break-even bookmaker price is `1/p`; the analogous single-selection exchange price is `1 + (1/p - 1)/(1-c)`. Label these break-even prices, not recommended safety margins. A configurable margin can be added, with its value and rationale disclosed and frozen before assessment; do not optimise it on this weekend's results.

Compare prices captured within a stated time window and under relevant terms. Say 'best observed among checked providers', not 'best available everywhere'. Missing size, stale quotes, unknown commission or changed fields limit the comparison. A positive model calculation makes a runner a **candidate for human review** only when required inputs are current and valid. Missing required inputs produces a watch/recheck state. No fabricated odds, stale 'value' badges, automated stakes or orders.

## Jev and written analysis

Jev is an optional stage after collection and runner attribution, before synthesis. Start with three narrow classifications: topic, author's stance toward the specified horse, and whether the opinion has a price/weather/other condition. Include unclear/not-mentioned states. Preserve evidence, question/prompt version, model identity, output and uncertainty. Its output confidence is not a win probability or the truth of the source. See [official introduction](https://docs.typesafe.ai/introduction) and [confidence documentation](https://docs.typesafe.ai/confidence).

Use code for arithmetic and validation. Use the project Codex chat or an explicitly configured reasoning model to write evidence-linked briefs; a paid standalone generation service is not a prerequisite. Jev does not fetch websites, extract arbitrary new text by returning fixed labels, decide fair odds or adjudicate the complete race. If Jev access, budget or quality blocks progress, run with manually reviewed classifications. Do not let this delay the first usable brief.

For the weekend, review approximately 40–60 representative excerpts, splitting prompt-development and evaluation examples before tuning. Include multiple horses, negation, quoted opinions and conditional tips. Record per-label precision/recall, unknown/abstention rate and material errors such as wrong horse or dropped price conditions. Manually inspect all shortlisted evidence. Expand to approximately 200 labelled excerpts after the weekend before relying on automatic classification more widely. This small pilot validates workflow only, not general accuracy or predictive value.

## Implementation approach

Use a small Python project with a CLI, SQLite, immutable source snapshots where permitted, explicit schemas, and Markdown plus a simple static HTML report. Inspect the new repository and its instructions before choosing dependencies. Do not migrate the old Flask interface or introduce hosting, a vector database, microservices or a frontend framework for this deadline.

Suggested modules: source adapters/manual imports; canonical race/runner matching; evidence store; model/quote snapshot validation; optional Jev adapter; deterministic calculations; report generation; snapshot/decision log. Keep results and later evaluation separate from pre-race inputs.

Each evidence record needs source URL, publisher/author, publication time if known, retrieval time, race/runner references, a short excerpt, observation versus opinion, conditions, provenance and review status. Preserve unknown timestamps rather than guessing. Each generated report needs cutoff time, source snapshot IDs, code/config versions and review status. Pre-race generation must not access current-race outcomes or closing BSP. Previous-race historical form remains valid when actually available at the cutoff.

Commit code, documentation, safe fixtures and an example config to the user's new repo. Exclude secrets, `.env`, private user decisions, downloaded/licensed content, large databases and raw archives by default. Reuse tested calculations from the earlier package selectively, with their limitations documented. No forced Git operations or publication of private/source data.

## Build sequence and delivery gates

| When | Deliverable | Acceptance gate |
|---|---|---|
| First session, ideally Wed 23 Sep | Repository setup, meeting config, source-access matrix, current-rating acquisition proof and validated manual imports | Can represent a complete actual race from official fields and identify whether current model coverage exists. Unavailable future ratings are recorded as pending. |
| Thu 24 Sep | One real race brief for each meeting using whatever pre-race material has been published; missing inputs prominent | Full field represented; every substantive research claim has evidence; model identities/times correct. Verify numbers and horse attribution manually. |
| Fri 25 Sep | Rosehill full-card preview plus preliminary Caulfield coverage | All named sources checked or explicitly pending/unavailable; every race represented; shortlist evidence reviewed; no invented model values. |
| Sat 26 Sep, target 09:00 local | Refreshed Rosehill pack and reviewed shortlist | Latest official changes checked, ratings/quotes recaptured when available, limitations visible. If publication is later, mark provisional and rerun after release. |
| Sun 27 Sep, target 09:00 local | Refreshed Caulfield pack and reviewed shortlist | Same checks independently applied to Sunday; Saturday's conditions are not carried forward blindly. |
| Before each race, on user-triggered refresh | Updated fields, conditions and observed quotes; new immutable report version | Show changed items and invalidate affected price/field comparisons. Aim for a fresh quote within five minutes of a price decision; older observations visibly stale. |
| After the weekend | Read-only outcome reconciliation and usefulness review | Preserve all original predictions, candidates, passes and human decisions; no retrospective rewriting. |

These are delivery targets, not scheduled jobs. The user starts the new project chat and runs/requests race-day refreshes. If the user later wants scheduling, configure it explicitly with host availability and notification preferences; this plan does not create monitoring.

If starting late, prioritize one end-to-end race immediately, then all fields/model tables and highest-relevance research. Cut UI extras and Jev automation before cutting provenance or silently skipping races. Do not spend the deadline attempting to unblock one site; expose that gap and support a manual input.

## Required validation and definition of done

Tests should address real failure modes: wrong meeting/date or runner joins; duplicate/ambiguous horses; incomplete model fields; invalid probabilities; scratchings after a snapshot; stale quotes; commission arithmetic; syndicated evidence; failed source fetches; wrong-horse or conditional commentary; and preventing post-cutoff/current-race outcome leakage. Confirm the rendered report works locally, including missing-data states, links and timestamps.

Weekend delivery is complete when every officially listed race in both selected meetings has a report, every runner appears, all named sources have an honest recorded status, available model/price data have provenance, and shortlist claims have been manually checked. The full model-plus-research objective additionally requires actual current model numbers; model-unavailable reports are useful partial delivery. No unsourced form claims or concealed critical gaps are acceptable.

Measure usefulness through the user's recorded research time and whether the briefs helped selection/pass decisions. Keep results for all races, not just winners or highlighted picks. Report probability quality and paper returns only where inputs and decisions were genuinely captured before the race; apply settlement rules/costs and report sample size. Separate system candidates from the user's choices. Do not interpret this weekend as proof of an edge.

## Open dependencies for the new chat

- User: the new repository location; relevant existing source access; a securely configured Jev key only if using its API; authorised API budget before any billable calls. Never ask for secrets in chat.
- Engineering: actual live ratings endpoint/publication timing and model identity; permitted access for each source; date-specific official field/track pages; evidence refresh and normalization policy.
- User/engineering together: which bookmakers to compare and actual exchange commission if displaying account-specific value. Missing answers must not block field/research work; use labelled assumptions or omit the dependent calculation.

Start implementing the one-race path once this plan is supplied to the new project chat. Do not ask the user to repeat settled requirements or approve routine reversible implementation decisions. Ask only about genuine missing access, costs or material choices.
