# Research side — sources, evidence and digests

State at 23 Sep 2026, 19:50 AEST. The model, prices and the main brief (`python -m punting report`) belong to the model workstream. This covers the research: which sources we can read and how, turning what they say into verified evidence, and a per-race research digest. Everything goes into the same append-only store, so the main brief shows it too.

Nothing here places bets, logs in, bypasses a block, or fetches a path that a site's robots.txt disallows.

## Source access (checked 23 Sep 2026)

| Source | Route | Evidence for the decision | Status for this weekend |
|---|---|---|---|
| Racing.com | Automated fetch (articles). Browser for form/tips pages | robots.txt allows all. Articles render server-side; form guide and tips are JavaScript-only | 15 articles read, 9 used, 37 claims |
| The Daily Punt (`thedailypunt.com.au`) | Automated fetch | robots.txt allows all but `/admin`, `/api/`. `thedailypunt.com` is an unrelated football site. Ratings are "supplied by PuntersTech": a separate numeric product | Not yet published. Ratings appear the day before. Spring All-Stars round 1 is this weekend; bets are due by 11:00 on each race day |
| Just Horse Racing | Browser only | Returns HTTP 403 to non-browser clients, even for robots.txt. The built-in browser got a Cloudflare "you have been blocked" page | **Blocked.** Card previews exist (Rosehill …/907266, Caulfield …/907272). Needs your browser or pasted text |
| Punters | Browser only | robots.txt: `User-agent: *  Disallow: /`. The built-in browser refuses punters.com.au (its safety policy) | **Blocked.** Needs your browser or pasted excerpts |
| Wolfden | Manual | App-only (wolfden.win redirects to the wolfden.bet app). Betfair Hub's Wolfden lay-challenge page has undated comments that don't say which race they mean | Not used. Paste Wolfden tips to include them |
| BOM | Official anonymous FTP | www.bom.gov.au robots.txt disallows `/fwo/`. The same forecast products are on `ftp.bom.gov.au/anon/gen/fwo/` for automated use | Précis forecasts stored for both meetings |
| Official (Racing NSW, ATC, RV) | Automated fetch | robots allow (ATC rate-limited once with HTTP 429) | Track reports not yet published for race day |
| Racing Australia FreeFields | **Browser or import only** | robots.txt: `User-agent: *` … `Disallow: /FreeFields/` | See "Issues" below |
| AAP via Just Racing / RacingFans | Automated fetch, supplementary | robots allow. Both republish the same AAP wire copy | Read. Counted as one source (AAP) |

Python's `urllib.robotparser` answers BOM's robots.txt wrongly, because the file has two `User-agent: *` groups. `access.robots_rules` merges same-agent groups and uses longest match, as RFC 9309 requires; this is tested.

## Coverage so far (first pass, 23 Sep evening)

34 pages were captured and 19 were used. They gave 53 new claims, and every excerpt was verified against captured text:
- 37 from Racing.com;
- 15 from AAP stories, via Just Racing;
- 1 from Betfair Hub.

Ten first-session records were also labelled with stance and topic. There are 4 researcher notes, all marked as inference.

| Meeting | Races with commentary | No commentary yet |
|---|---|---|
| Rosehill, Sat 26 Sep | R1, R4, R7, R8, R9, R10 | R2, R3, R5, R6 |
| Caulfield, Sun 27 Sep | R2–R8 (R1 only has first-session records, which can't be verified) | R9 |

Most tipster content (Just Horse Racing, Punters, The Daily Punt, Racing.com tips) is either blocked or not published until Friday or race morning. So this pass is mostly stable news, trackwork, gear, and distance/track preferences. Selections should thicken on the race-morning refresh.

## How evidence gets in

1. **Capture.** Redirect destinations are checked against source policy and robots.txt before any request; redirected robots files fail closed. Do one of:
   - `python -m punting.research fetch URL…`: only for sources approved for automated fetching, checked against robots.txt, at most one request every 3 s per host.
   - For browser-only pages: run the script printed by `python -m punting.research checker PACK --page ID` in a normal browser tab.
   - `python -m punting.research links URL --match REGEX` lists same-host article links through the same gates.
2. **Write a pack** (`imports/research/*.json`, gitignored). Each pack lists:
   - the pages read, with route, observation time and text hash;
   - the claims, each with race, runners, type, stance, topic, conditions, a short summary in our own words, and a verbatim excerpt of at most 20 words.
3. **`python -m punting.research check PACK`, then `import PACK`.** Both commands run the same full preflight, including coverage, notes and race-start checks, before import writes anything. Import refuses the whole pack if any of these fail:
   - The excerpt isn't verbatim in the captured text (or in the browser receipt).
   - A claimed horse isn't named within 600 characters of the excerpt. This is the wrong-horse guard; it rejected two real claims tonight, which were rewritten against better excerpts.
   - A runner name doesn't match exactly one official runner in that race. Apostrophes and country suffixes are normalised; nothing is fuzzy-matched.
   - The page was observed after the race start, or a publication time is later than the observation.
   - Researcher inference is written as a source claim, a note is future-dated or has an invalid race number, or a note cites something observed after the note.
4. **`python -m punting.research digest`** writes `reports/<meeting>/research/<version>/digest.html`.

Rules the digest applies:
- **For / Against count independent voices, not articles.**
  - A quoted person is one voice whichever outlet carries the quote ("Michael Kent Jnr" = "Michael Kent Jnr, reported by …").
  - Syndicated copies share a voice.
  - Silence is never a negative signal.
- **Stance and topic are classifications, stored separately** (`data/research_notes.sqlite`, append-only) with the classifier's identity. First-session records can be labelled without being re-created.
- **Researcher inference is shown as inference**, with its basis linked.
- **`reviewed: true` on our evidence means the excerpt was verified** against the captured text and read in context. It is not a claim that you have reviewed it.

Captured article text sits in `data/private/pages/` only so excerpts can be re-verified. The plan says full articles shouldn't be retained where permission is unclear, so run `python -m punting.research purge-text` after the weekend. Metadata and hashes stay.

Just Horse Racing, Punters, Wolfden and The Daily Punt are deferred as sources for now, per the user. Their unavailable coverage is informational and does not block the workflow.

## Race-morning refresh (Sat for Rosehill, Sun for Caulfield)

1. `python -m punting.research weather`: BOM re-issues around 04:15 and 16:00 AEST.
2. Official track report, rail and scratchings. Track is Soft 5 at Rosehill and Good 4 at Caulfield as of Wednesday's acceptances. Forecasts point to a possible Rosehill upgrade (dry, 34°C Saturday) and a possible Caulfield downgrade (showers Fri–Sat).
3. Refresh available Racing.com and supplementary commentary; the four deferred sources above do not need fetching.
4. Anything you paste from Punters, Just Horse Racing or Wolfden goes in as a `manual` page and shows as UNVERIFIED unless text is captured.
5. `python -m punting.research digest`, then the main brief.

## Issues found (not fixed here: they are in the model workstream's files)

1. **`sources.fetch_fields` requests `racingaustralia.horse/FreeFields/Acceptances.aspx`, which robots.txt disallows for generic agents.** Options:
   - read the page in a browser and import it;
   - use Racing NSW / Racing Victoria field pages;
   - get explicit permission.
2. **The first-session evidence records have empty excerpts but `reviewed: true`**, and use the summary text as `claim_id`, so they cannot be verified or linked to a syndicated copy. They are labelled "no excerpt to verify" in the digest. The two whose source pages were re-read here had their horse confirmed on the page.
3. **Cosmetic, in `report.py`:**
   - empty conditions print as "Conditions: Unknown";
   - race-level claims print as "Meeting".
