# Injection precision

Every number on this page comes from one of four measurement records of the site where the plugin was built: a read-only analysis of stored judge labels, a replay with blind labels, a calibration of the judge against a second labeller, and a series of settings sweeps. No number was computed anew for this page. Where a figure that a reader would expect is not in those records, the page says "not measured".

Counts and percentages only. No message text, no bullet text and no recalled text appears here.

## Terms

- Bullet: one recalled memory injected into one turn.
- Strict precision: share of bullets labelled Relevant (R) by the rubric. Lenient precision: share labelled Relevant or Borderline (R or B).
- Rubric labels: R relevant, B borderline, S stale, W wrong, N not relevant. In some sweep rounds the labels were Relevant, Irrelevant, Stale, Wrong.
- Judge: an automated scheduled labeller. It runs on the same model that wrote the bank (self-grading risk, stated by the source).
- Labeller: the reviewer agent (Agent C), labelling blind to the arm or the setting, one labeller per round. The orchestrator agent (Agent A) labelled the first sample round.
- Turn: one user message with its injected bullets. Interval: 95 percent interval from a paired bootstrap over turns, as the source states (5000 resamples in the replay; the sweep README states 95 percent intervals without stating the method for each).
- Arm A: the recall query is the first 800 characters of the message (the plugin default without a cut). Arm B: the text before the `Output:` marker (the notice cut).

## 1. Cut of the query on background-process notices (replay)

Source: replay record of October 28. Setup as stated by the source: 31 background-process notices of the October 28 window (test) and 10 short dispatch notices of October 22 (control). The bank was settled; each query ran twice with 0 differences. One labeller (Agent C) labelled the union of both arms blind to the arm (131 bullets: R 59, B 47, N 25; 19 unverified). Replay differs from live in one way: the short-query context patch was not applied, and no arm B query is under 60 characters.

| Group | Turns | Strict A | Strict B | Strict B minus A (points) | 95% interval | Lenient A | Lenient B | Lenient B minus A | 95% interval |
|---|---|---|---|---|---|---|---|---|---|
| Test, all | 31 | 8.8% (5/57) | 52.9% (27/51) | +44.2 | +29.2 to +58.9 | 61.4% (35/57) | 96.1% (49/51) | +34.7 | +21.2 to +49.4 |
| Test, message 700 characters or more | 15 | 3.3% (1/30) | 69.2% (18/26) | +65.9 | +46.2 to +85.2 | 43.3% (13/30) | 92.3% (24/26) | +49.0 | +29.8 to +70.4 |
| Test, message under 700 characters | 16 | 14.8% (4/27) | 36.0% (9/25) | +21.2 | +5.8 to +37.2 | 81.5% (22/27) | 100.0% (25/25) | +18.5 | +3.7 to +35.7 |
| Control, short dispatch notices | 10 | 95.0% (19/20) | 67.9% (19/28) | -27.1 | -35.7 to -14.6 | 100.0% (20/20) | 96.4% (27/28) | -3.6 | -11.5 to +0.0 |
| All 41 turns | 41 | 31.2% (24/77) | 58.2% (46/79) | +27.1 | +14.0 to +40.9 | 71.4% (55/77) | 96.2% (76/79) | +24.8 | +13.4 to +36.8 |

Reading, limited to what the data say:

- On the 31 test turns the cut raised strict precision from 8.8 percent to 52.9 percent, and the interval (+29.2 to +58.9) excludes zero.
- On the 10 control turns, strict precision FELL from 95.0 percent to 67.9 percent (interval -35.7 to -14.6, excludes zero). The lenient figure moved from 100.0 to 96.4 percent and its interval ends at +0.0, so the lenient and strict numbers do not tell the same story on the controls. The cut query returned more bullets per turn on the controls (2.8 against 2.0, as the source states) and the extra ones were on the subject but borderline.
- The strict gain on the test turns is much larger for the long notices (message 700 characters or more) than for the short ones.
- Bullets that only one arm returned, by label: only in arm A: R 13, B 17, N 22. Only in arm B: R 35, B 16, N 3. In both: R 11, B 14, N 0. Six test turns had identical bullet sets in both arms.
- The data do not show what dropping injection for notices would do; the controls gave 19 R in 20 bullets under arm A.

Limits stated by the source: one labeller (not the author of the bank); four pairs of identical notices count as separate turns; 19 bullets are unverified; the controls come from a different date and bank state; the strict R/B split on dispatch notices follows the labeller's own reading of the rubric. The live change (cut the query, drop injection for notices, or nothing) was left to the operator and is not decided in the source.

## 2. Why relevance fell over three review ticks (judge labels)

Source: read-only analysis of October 28 on the stored judge labels (rubric version 5).

| Tick (date) | Bullets | Strict | Lenient |
|---|---|---|---|
| October 25 | 39 | 46.2% | 89.7% |
| October 26 | 56 | 48.2% | 69.6% |
| October 28 | 173 | 19.7% | 50.9% |

Observed in the October 28 window (judge labels, regular-expression turn classes):

- Recall settings, rubric and bank content were ruled out as causes by the source (same stored settings in every run; bullets seen in an earlier tick 42, relevant 19 percent; new bullets 131, relevant 20 percent).
- Content-bearing turn classes alone: strict 20 percent, lenient 51 percent (137 bullets); earlier ticks scored 46 to 62 percent strict on the same classes.
- Background-process notices: 16 of 33 were 700 characters or longer; those scored strict 10 percent. Short notices scored 34 percent (earlier ticks 53 to 100 percent).
- Dispatch scripts alone: 60, 91, 84, 67 and 100 percent in the five earlier ticks, in order, then 27 percent.
- The window held 108 injection turns against 21 to 37 in the three ticks before (a two-day burst of work).

Limits stated by the source: the judge is the same model that wrote the bank; four of the five earlier ticks hold 21 to 37 turns each (the first holds 114) and their intervals are wide (a first tick on October 23: 25 to 84 percent strict); turn classes come from regular expressions on the start of the message.

## 3. Calibration of the judge against a second labeller

Source: calibration round 2 (October 28 tick, 100 turns, 173 bullets, rubric version 5). Judge J is the scheduled judge (self-grading risk). Labeller L is the reviewer agent, blind. Credential strings were redacted from its packet.

| Measure | Value |
|---|---|
| Agreement on the five labels | 150 of 173 = 86.7% |
| Agreement in round 1 (tick of October 22, rubric version 4) | 76.5% |
| Kappa, lenient (R and B against S, W, N) | 0.850 |
| Kappa, strict (R against the rest) | 0.776 |
| Strict relevance, Labeller L against Judge J | 14.5% against 19.7% (as stated in the analysis record) |
| Bullets labelled R: Labeller L, Judge J | 25 and 34 |
| Bullets labelled N: both | 84 |

Confusion table of counts (rows Judge J, columns Labeller L):

| J \ L | R | B | S | W | N |
|---|---|---|---|---|---|
| R | 24 | 9 | 0 | 0 | 1 |
| B | 1 | 46 | 2 | 1 | 4 |
| S | 0 | 0 | 1 | 0 | 0 |
| W | 0 | 0 | 0 | 0 | 0 |
| N | 0 | 5 | 0 | 0 | 79 |

Limits stated by the source: the packet history quoted some earlier verdicts, so agreement may be higher than a fully blind round would give; 12 bullets are unverified and 1 turn needed context; 23 of the 173 bullets carry a wrong weekday for a correct date, and nine of those carry an R or B label (a strict reading of the rubric would label those W). The source concludes the fall in relevance is not judge drift.

## 4. Floor and cap sweeps

Source: the sweep record of October 17 to 18, with a database of every 100-question run (13,331 returned bullets, 1,068 blind label rows). Each round was labelled blind by one labeller, the reviewer agent (Agent C); the first sample round was labelled by both Agent A and Agent C. No interval is stated by the source for the comparisons of Section 4.2; where a table has none, none was measured or reported. All settings below were chosen and measured on the same questions, so every comparison is in-sample.

### 4.1 First sample (19 labelled questions, October 17)

- 317 blind bullets, scores hidden, order shuffled. Agreement between the two labellers: 3 classes 85.8% (kappa 0.70); relevant against not relevant 87.7% (kappa 0.61). Counts: Agent A R 75, S 33, N 209; Agent C R 46, S 41, N 230.
- After a cleanup of the bank, with cap 8 and floor 0.05: precision on the 19 questions went from 26.8% to 33.3% (Agent C labels) and from 30.4% to 38.1% (Agent A labels plus 13 verified stale). Stale bullets fell from 20 to 1 and from 23 to 3. Interval: not stated. Sample: 19 questions; bullet counts not stated in the record.

### 4.2 Hundred-question runs (October 18)

Columns "Cap" is the number of results injected. "Candidates" is the number of candidates the server returns before the floor. Percentages are shares of the bullets returned in that run.

| Run | Budget, max tokens | Candidates | Cap | Floor | Bullets | Relevant | Irrelevant | Stale | Wrong | Questions injected | With a relevant bullet | Seconds per question |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| V3, the then-live setting | not stated for this run | not stated | 8 | 0.93 | 459 | 35.3% (162) | 62.1% (285) | 1.3% (6) | 1.3% (6) | not stated | 67 | not stated |
| V4, low budget, 400 tokens | low, 400 | not stated | not stated | not stated | 341 | 45.7% (156) | 51.0% | 1.5% | 1.8% | not stated | 62 | not stated |
| Config C | low, 400 | 16 | 4 | 0.8 | 356 | 38.5% | 59.8% | 1.1% | 0.6% | 99 of 100 | not stated | 5.8 |
| Config D | low, 400 | 8 | 4 | 0.93 | 209 | 52.2% | 46.4% | 1.0% | 0.5% | 82 | 55 | 2.9 |
| Config E | low, 400 | 24 | 4 | 0.91 | 289 | 47.4% | 51.2% | 1.0% | 0.3% | 87 | 65 | 9.6 |
| Config F | low, 400 | 8 | 4 | 0.91 | 239 | 49.0% | 49.8% | 1.3% | 0 | 86 | 60 | 2.7 |
| Config G | low, 400 | 18 | 4 | 0.91 | 277 | 48.7% | 49.8% | 1.1% | 0.4% | 87 | 64 | 7.1 |
| Config H | low, 400 | 16 | 4 | 0.92 | 267 | 48.7% | 49.8% | 1.1% | 0.4% | 86 | 63 | 6.6 |
| V11, live setting at the time | low, 400 | 16 | 3 | 0.92 | 227 | 52.4% | 45.8% | 1.3% | 0.4% | not stated | 63 | 6.3 |

Notes from the source: V3 was captured at a raw cap of 24 and a floor of 0.01, and the cap 8 and floor 0.93 were applied to that capture. The record gives a mean latency of 66.9 seconds per question for a run with 50 candidates, without naming which row that run is. The database also holds nine inferred lower-cap windows; their values are not in the record: not measured here. The relevant share of V11 equals that of an inferred window (cap 3 of config H) according to the record.

Reading, limited to what the table says: the point estimate of the relevant share was higher in V4, configs D to H and V11 (45.7 to 52.4 percent) than in V3 (35.3 percent). Config C, with floor 0.8, was 38.5 percent. The number of questions with a relevant bullet was 62 and 67 in V4 and V3, and 55 to 65 in configs D to H and V11 where stated. A higher relevant share came with fewer questions injected in config D (82 against 99 in config C), so the share and the reach moved in opposite directions. No interval is stated, so no comparison here is shown to be more than a difference in point estimates.

### 4.3 Ninety-three real-life questions (October 18)

The labeller saw the previous assistant statement and the job for these rounds (rule change against rounds 1 to 10) and listed 23 questions that needed it. Intervals are from resampling questions, as the record states. "Without cron prompts" excludes scheduled-job prompts.

| Setting | Bullets | Relevant | Irrelevant | Stale | Wrong | Questions injected | With a relevant bullet | Seconds per question |
|---|---|---|---|---|---|---|---|---|
| Baseline live (low, 400, cap 3, floor 0.92, 16 candidates) | 150 | 57 (38.0%) | 72 (48.0%) | 17 (11.3%) | 4 (2.7%) | not stated | not stated | not stated |
| Context variant of the baseline | 122 | 38.5% | not stated | not stated | not stated | 59 against 69 | 27 against 37 | not stated |
| Old live (mid, 4096 tokens, cap 8, floor 0.93, 50 candidates) | 264 | 93 (35.2%) | 134 | 31 | 6 | 73 | 41 | 26.0 |
| Current settings, repeat run | 153 | 56 (36.6%) | 77 | 16 | 4 | 70 | 36 | 7.8 |
| S60: current settings plus previous statement for messages under 60 characters (25 of 93) | 143 | 64 (44.8%) | 56 | 19 | 4 | 64 | 41 | 7.8 |
| M500: mid, 500 tokens, 18 candidates, cap 3, floor 0.90, with the S60 rule | 202 | 68 (33.7%) | 102 | 24 | 8 | 78 | 43 | 8.7 |
| M93: as M500 but floor 0.93 | 129 | 61 (47.3%) | 44 | 20 | 4 | 63 | 40 | 9.2 |

Further figures stated by the record:

- Baseline: precision 95 percent interval 29.2 to 47.1 (resampling 93 questions). With the message-only rule: 34.7 percent.
- Old live relevant share by rank (relevant bullets of bullets at that rank, ranks 1 to 8): 30 of 73, 19 of 48, 9 of 35, 10 of 28, 10 of 24, 5 of 23, 4 of 18, 6 of 15.
- S60 without cron prompts: 124 bullets, 50.0 percent relevant. M93 without cron prompts: 117 bullets, 50.4 percent.
- Control for S60: of 68 unchanged queries, 61 returned the same list as the repeat run; 7 differed (bank drift). One returned bullet had no blind label and was labelled by Agent A, not blind; the effect is at most 0.7 points.
- M500 read at floor 0.92 from the same raw capture: 152 bullets, 42.1 percent relevant, against 44.8 percent for S60. The 50 bullets between 0.90 and 0.92 hold 4 relevant ones (8 percent).
- M93: 89 of 93 lists equal the earlier capture read at 0.93.

Paired differences in strict precision (points, 95% interval as stated):

| Comparison | Difference | Interval | Interval spans zero |
|---|---|---|---|
| Current settings against old live | +1.4 | -4.4 to +6.9 | yes |
| Current settings against old live, without cron prompts | +3.6 | -2.4 to +9.3 | yes |
| Context variant (query with context for all) against the repeat run | +1.9 | -10.0 to +14.1 | yes |
| S60 against the repeat run of the current settings | +8.2 | +2.5 to +14.6 | no |
| S60 against old live | +9.5 | +1.4 to +17.7 | no |
| M500 against S60 | -11.1 | -16.1 to -6.9 | no (precision FELL) |
| M500 against the repeat run | -2.9 | -9.4 to +3.6 | yes |
| M93 against S60 | +2.5 | -1.1 to +6.0 | yes |
| M93 against the repeat run of the current settings | +10.7 | +3.9 to +18.1 | no |
| M93 against old live | +12.1 | +3.9 to +20.2 | no |
| M93 against M500 | +13.6 | +8.7 to +19.2 | no |

Offline floor sweep at cap 3 on the S60 capture (in-sample, all bullets labelled):

| Floor | Relevant share of labelled bullets | Relevant bullets | Questions with a relevant bullet |
|---|---|---|---|
| 0.90 | 37.6% | 68 | 43 |
| 0.91 | 39.3% | 66 | 42 |
| 0.92 | 44.8% | 64 | 41 |
| 0.93 | 48.4% | 62 | 40 |
| 0.94 | 54.1% | 59 | 39 |

Reading, limited to what the data say: a higher floor raised the relevant share and lowered both the number of relevant bullets and the number of questions with a relevant bullet. Precision therefore rose while reach fell. The source says budget, tokens and candidates did not matter in this comparison; the floor did.

Caution stated by the source: the 60-character threshold of S60 was chosen on the same labels (offline estimate 49.6 percent without cron prompts, measured 50.0 percent). A held-out set is still needed.

### 4.4 Four context variants for the 25 short messages (October 18)

Query = a context line plus the user message. Current settings, floor 0.92, cap 3. Round of 42 bullets, one labeller.

| Arm | Context | Bullets | Relevant | Share | Questions with a relevant bullet |
|---|---|---|---|---|---|
| none | no context | 37 | 11 | 29.7% | 6 |
| A | tail of 400 characters | 29 | 17 | 58.6% | 9 |
| B | tail of 600 characters | 40 | 16 | 40.0% | 11 |
| C | extractive, 600 characters | 46 | 18 | 39.1% | 12 |
| D2 | model summary of at most 600 characters | 40 | 17 | 42.5% | 13 |

Paired differences against arm A: B -18.6 points (interval -39.1 to 0.0), C -19.5 (-39.5 to -1.1), D2 -16.1 (-37.1 to +5.9). Arm A against no context: +28.9 (+4.0 to +54.5). Stale plus wrong bullets: none 3, A 6, B 9, C 11, D2 11. Longer or summarised context reached 2 to 4 more questions with a relevant bullet and added irrelevant and stale bullets. A first summary pass was discarded because 21 of 25 outputs ran over 600 characters. Sample: 25 messages. The source's decision basis for keeping arm A is that the summary adds a model call and does not beat the tail on precision. Intervals of B and D2 reach zero or cross it; do not read B or D2 as lower than A with certainty.

## 5. Limits that apply to every table

- One blind labeller per round (the reviewer agent), except the first sample round of 4.1, which two agents labelled. The judge of Sections 2 and 3 is the same model that wrote the bank.
- Small samples: 19 questions in 4.1, 25 messages in 4.4, 10 control turns in Section 1, 93 questions in 4.3, 100 questions in 4.2.
- The controls in Section 1 come from another date and another bank state than the test turns.
- Bank content changes between runs. Drift controls are stated where the source ran them.
- Settings were chosen on the same labels they were measured on. No held-out set exists.
- Strict and lenient numbers disagree in places (the controls in Section 1). Neither alone is the answer.
- Not measured: precision after the plugin was installed on a live profile (no record exists in the sources used here); intervals for the Section 4.2 comparisons; values of the nine inferred lower-cap windows; a held-out test of the 60-character threshold.
