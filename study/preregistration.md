# Main pre-registration

**Status.** Registered 24.11.2026; choices marked `[proposed]` and the budget await the author's confirmation; revisions
before the first pool session (01.12.2026) are dated commits made before any data B–F exists.

Registered before any pool of data sets B–F is recorded and before any score of the drift job is opened. Data set A,
Experiment 1 and the drift-job part of Experiment 2 are registered in `drift-job.md`; this document adds the rules and
parameters that `drift-job.md` refers to, and everything else. Changes after this commit go to `deviations.md` (date,
section, what changed, why, whether any score had been seen). An analysis not described here is reported as
exploratory. `[proposed: …]` marks a choice made in this plan, with its reason; `[to measure]` marks a quantity that the
recorded data will give, by the rule stated where it is used.

## Questions

- **RQ1 (design).** Do existing release gates for LLM pipelines and agents make sequential non-inferiority decisions, and
  if not, how can a gate that does be designed? Answered by the grey-literature review, not registered here.
- **RQ2 (decision quality).** Does a sequential non-inferiority gate keep its error guarantee under real run-to-run noise,
  how often does it leave a change undecided, and does adapting the evidence pay off against a fixed sample at equal cost?
- **RQ3 (assumptions).** Do the assumptions of the sequential test hold in CI, namely that rounds within a job are
  independent and that conditions stay stable across sessions, and what follows for the unit of observation and for
  reusing baselines?

| Exp. | Question | Data | Output | RQ |
|---|---|---|---|---|
| 1 | Noise and drift, unit of observation | A | Table 10, Fig. 5, 8.2.6 | 3 |
| 2 | False blocks; reusing a baseline | A, F, A/A pools of B | Table 9b, Fig. 6, 8.2.7 | 2, 3 |
| 3 | False passes and detection | B, C | Table 9a, Fig. 3, 8.2.1 | 2 |
| 4 | Adaptive evidence against a fixed sample | decisions of 3 | Fig. 4, 8.2.2 | 2 |
| 5 | Undecided verdicts and the money limit | decisions of 3, token logs | 8.2.3 | 2 |
| 6 | Burden of proof | decisions of 3 | 8.2.4 | 2 |
| 7 | Use in practice: sweep, retries, chain | B, C, D | 8.2.5 | 2 |
| 8 | Synthetic: known effect, correlation, drift | none (simulation) | 8.2.1; Sections 6.2, 10 | 2, 3 |
| 9 | Stress: whole sessions go bad | A | 8.2.1, 8.2.6 | 2, 3 |
| 10 | Held-out: Experiments 2 and 3 once on E | E | next to 8.2.1, 8.2.7 | 2 |

A second model (Experiment 11) is decided on 11.12.2026; if it goes ahead, it joins through an amendment registered
before its first run.

## The gate under test

AgentiCI is the gate in this repository (`llm-release-gate`) at the feature-freeze tag `v0.1.0-dev.22`
(`8a60927`, 24.11.2026). The simulator calls the gate's own decision functions from that tag (the rule on the mean, the rule on checks,
the error split) and reimplements only the loop that buys rounds (below).

- **Score.** A run executes all `N` cases of a set; its score `S ∈ [0, 1]` is the mean case score. A case score is the
  share of passed checks (`aggregate: mean`; receipts, one check per field) or 1 if all checks pass, else 0
  (`aggregate: all`; support agent, telecom). No check in the sets has a level (`critical`, `minor`).
- **Rule on the mean** (`mean.py`, method `cases-c0.75`). Round `t` gives one run of each version, `D_t = S_c,t − S_b,t`;
  repetition `k` of a case is paired with repetition `k` of the base. One-sided betting tests at `m = (1 − δ) / 2` on
  `Y = (D + 1) / 2`, one bet per case run, the bet held fixed for all cases of a run: pass when the capital for "at most δ
  worse" reaches `1 / α_mean` (lower bound `L_t > −δ`), block when the capital for "more than δ worse" reaches
  `1 / α_mean` (upper bound `U_t < −δ`). A block needs `U_t < −δ`, not `U_t < 0`.
- **Rule on checks** (`criterion.whole_runs`, commit `ac714f0`): a permutation test over whole runs, the minimum p over
  checks against its distribution over the splits of the runs between the versions (every split when they are few,
  random splits otherwise), step-down adjusted, at `α_checks`, read once on rounds 1…`K_c` (at most 10 runs per
  version). A check that the candidate passes significantly less often blocks.
- **Error split.** `α = 0.05` for the whole gate: `α_mean = 0.025` per side of the rule on the mean, `α_checks = 0.025`.
  Only the rule on the mean can pass a change, so a change worse than δ passes with probability at most **0.025**; an
  unchanged version is blocked with probability at most 0.05.
- **Rounds and money** (`pr.buy`). All rounds of a decision run in one job: round 1 alone, then rounds 2…`K_c`, then one
  round at a time; the gate decides from round `K_c = 5` on. A round starts only if the money spent plus the estimate of
  the next round (the cost of the last round of each version) fits under the money limit `L`; otherwise the verdict is
  undecided.
- **Outcomes.** Pass, block (by the mean, by checks, or both) or undecided.
- **Cost and latency budgets** (`budgets` in `gate.yaml`) are left out of every simulated decision: all rules decide on
  quality only `[proposed: a budget block would mix a second question into the error rates]`. In F, where the gate runs
  for real, a budget block is recorded and reported apart from quality blocks.

## Settings

All on `claude-haiku-5-5`: no dated snapshot exists; every run records the model the API reports. The release (the old
version of every change unless stated) is frozen by the tag `drift/base` of each application's repository, the commits
listed in `drift-job.md`.

| Setting | Repository, pipeline, set | Cases | Checks | Case score | Notes |
|---|---|---|---|---|---|
| Receipts, one call | `receipt-intake`, `sroie-image`, `golden/sroie` | 30 | 120 (4 fields each) | mean | scan as input |
| Receipts, two calls | `receipt-intake`, `sroie-steps`, `golden/sroie` | 30 | 120 | mean | OCR text as input; extract, then check |
| Support agent alone | `workbench-support`, `support`, `golden/solo` | 53 | 324 (5–7 each) | all | one ticket, no dialogue |
| Support agent, simulated user | `workbench-support`, `support`, `golden/chat` | 53 | 324 | all | the user is simulated by `claude-sonnet-5-5` |
| Telecom | `telecom-support`, `telecom`, `golden/telecom-pr` | 10 | 78 (4–10 each) | all | τ²-bench v1.0.1 telecom, tau2's solo mode, as in the drift job |

- **Simulated user.** `drift/base`'s `gate.yaml` runs `golden/solo`. The simulated-user sessions run from tags that differ
  from the solo ones only in `gate.yaml`, whose pipeline reads `golden/chat`: `study/chat-base` and `study/chat-<id>`.
- **Receipts with two calls** is registered here in full. Its pipeline is frozen at the tag `study/steps-base`
  (`drift/base` plus the finished pipeline) by 06.12.2026; all its sessions fall in 07.–11.12. If the tag is not ready
  by then, the setting is dropped (a deviation) and its budget is not spent. It is not in the drift job.
- **Not used:** the held-out case sets of the support agent (13 cases each) `[proposed: a 13-case set is another setting,
  a pass needs more rounds, so its rates would not compare]`. Data set E is a held-out *pool*: the same sets, another
  calendar week.

### Parameters

| Setting | δ (points) | α gate / mean / checks | `K_c` | `K_pass` | Budget `B` (rounds) | Round cost (both versions) | `L_team` |
|---|---|---|---|---|---|---|---|
| Receipts, one call | 5 | 0.05 / 0.025 / 0.025 | 5 | 5 | 10 | ≈ $0.021 | ≈ $0.22 |
| Receipts, two calls | 5 | same | 5 | 5 | 10 | [to measure] | 10.5 rounds |
| Support agent alone | 5 | same | 5 | 5 | 10 | ≈ $0.158 | ≈ $1.66 |
| Support agent, simulated user | 5 | same | 5 | 5 | 10 | ≈ $0.23 [to measure] | ≈ $2.42 |
| Telecom | 5 | same | 5 | 10 | 20 | ≈ $0.556 | ≈ $11.40 |

- **δ = 5 points** in every setting: the author's choice of 15.11.2026, the value in each application's `gate.yaml`.
- `K_pass = max(K_c, mean.runs_for_pass(N, δ, α_mean))`, the first round at which the gate can pass an unchanged version
  (`runs_for_pass`: 2 rounds for 53 cases, 4 for 30, 10 for 10).
- **Budget** `B = min(2 · K_pass, R)` rounds per decision, `R` the rounds per version in the pool `[proposed: a change not
  settled at the earliest possible pass gets as many rounds again]`. Decisions built from one drift job: `B = 5`.
- **Two money limits.**
  - `L_team = (B + 0.5) · c̄_release`, `c̄_release` the mean cost of a round of the release (both versions): what a team
    would set; it buys `B` rounds at the release's mean round cost `[proposed: half a round of headroom; the gate's docs
    advise 20 %]`. For S12 and R09, whose old version runs Sonnet 5.5, the release is that old version. Used in
    Experiment 5 and in the sweep. With it, AgentiCI buys more rounds for a cheaper candidate and fewer for a dearer one.
  - `L_pair = (B + 0.5) · c̄_pair`, `c̄_pair` the mean round cost of the change's own pair over its pool, **plus a hard cap
    of `B` rounds**: used wherever rules are compared at equal model calls (Tables 9, Figs. 3 and 4, Experiments 3, 4, 6, 7
    except the sweep of the limit). AgentiCI then gets at most the `B` rounds every other rule gets, and fewer only when
    rounds cost more than the pair's mean.
  - Round costs: tokens × each application's `prices.yaml`, as the gate computes them; the records carry tokens, not
    cost. `c̄_release` comes from the drift job's records up to 30.11. (an operational field), for the two settings outside
    the drift job from their first A/A session, and is fixed before the first pool. The table uses the costs in
    `drift-job.md`. For telecom, `L_team` replaces the `$4` in `gate.yaml`, which buys 7 rounds, fewer than the 10 a pass
    needs.

## Definitions

- **Run, round, session.** A run: one version, all cases once. A round: one run of each version. A session: one CI job
  running `pr --rounds 5`, both versions in parallel, each in its own tree and process; each side's runner runs every case
  5 times in one call with 4 workers, case by case, so a round is a repetition index, not a slice of time.
- **True effect** `Δ` of a change: mean `S` of the new version minus mean `S` of the old version over all usable runs of
  both versions recorded for that change in the data set analysed (B and C together in the main analysis; E alone in
  Experiment 10). With the cases held fixed (below), every decision on a change has this one truth.
- **Classes**, by a change's own `Δ`: **worse than δ** `Δ ≤ −δ`; **harmless at δ** `Δ > −δ`; **clearly harmless**
  `Δ ≥ −δ/2`. **Size of a break**: `−Δ`. Size bins are half-open: `< 0`, `[0, 2.5)`, `[2.5, 5)`, `[5, 7.5)`, `[7.5, 10)`,
  `[10, 15)`, `[15, ∞)` points; a size of exactly 5 is worse than δ. **Boundary bin**: `[5, 7.5)`.
- **False pass:** a pass on a change worse than δ (the error `α_mean` bounds). **False block:** a block when both sides
  are the same version. A block of a change harmless at δ appears in the detection curves, not as a false block.
- **Detection:** the share of decisions that block, by size of break; the decisions not blocked are split into pass and
  undecided and reported apart.
- **Per decision:** outcome; which rule blocked (mean, checks, both); rounds used; cost (tokens × prices of the runs used,
  both versions, or the candidate only for rules that run no baseline); time (model below).
- **Time model.** For each session a decision uses: the session's wall time (earliest record start, `timestamp −
  wall_s`, to latest record end, both sides) × rounds used from it / 5; summed over sessions `[proposed: rounds are not
  slices of time in a `--rounds 5` session; the real gate's rounds beyond `K_c` run one at a time and take longer, so
  this understates them]`.

## Data

**A: drift job.** As registered in `drift-job.md` (≈ $148, 25.11.2026–05.01.2027). Its declared changes are S05 (support
agent) and R03 (receipts).

### Recording B–E

- **Session.** A `workflow_dispatch` job checks out the tag of the new version and runs `llm-release-gate pr --base <tag
  of the old version> --rounds 5`, as the drift job does. Each change is a tag `study/<id>`: its old version plus one
  commit. The orchestration comes from the gate's freeze tag; each side's runner comes from its own tree's lock (on
  `drift/base`: gate `v0.1.0-dev.20`, record version 7).
- **Schedule.** The 4 sessions of a change fall on 4 distinct days, at three slots of the day in turn (07:00, 13:00,
  19:00 UTC), away from the drift job's times. Within a slot, sessions run back to back, at most 3 at once; the order of
  changes is drawn with seed 20261201 `[proposed: spread sessions over days and times, stay under rate limits]`. About
  196 sessions fall in 01.–11.12. The schedule is committed as `study/schedule.csv` before the first session. Each week
  carries about half of B: sessions 1–2 of every change and D in 30.11.–06.12.; sessions 3–4, C and receipts with two
  calls in 07.–13.12.
- **Records.** As in the drift job (record version 7): `model`, `requested_model`, `request_id`, `timestamp`, `wall_s`,
  `retries`, token counts, `ci_job`, `config_hash`, `set_hash`, `error`, `score_error`, per-check results, case score;
  `meta.json` per job. Stored in `data/runs/study/<set>/` and archived with the replication package; nothing is deleted
  or rewritten.
- **Blinding.** Until the analysis code is frozen (tag `study/analysis-1`, before 14.12.2026), only operational fields are
  read: errors, retries, tokens and cost, `ci_job`, counts. The end-to-end check of the analysis on real pools prints
  counts and hashes only. True effects are computed by the frozen code. F is not blind (below).
- **Stop and cuts.** Before each slot, a forecast: the cost so far plus the scheduled sessions left × the mean cost of
  their kind so far (before a kind has run, its estimate below). If a calendar week's forecast, drift job included,
  exceeds $150, or the total exceeds the sum the author approved, cut in this order until it fits: (1) F's remaining
  pull requests; (2) S16; (3) S12; (4) E's simulated-user pools. If a week still exceeds $150, its remaining sessions
  move to the next week within their window (B–D until 13.12., E until 20.12.); what does not fit then is a deviation,
  decided by the author. Nothing else of B, C and D is cut.

### Exclusions

- **Usable record**, as in the drift job: `error` is null and `score` is not null.
- **Provider errors** are records whose `error` comes from the provider side after the runner's retries: an exit 75 of
  the application (it reports a temporary provider failure), `stopped during backoff`, or `Fatal` (exit 78: credit or
  configuration). A record missing entirely (a version stopped by `Fatal` writes none for its remaining cases) counts as
  a provider error. Such a case is dropped from that round on both sides. A side's round in which more than 10 % of the
  cases have a provider error is dropped with its partner.
- **Version errors** are all other errors: no answer within the timeout, another exit code, an answer that is not valid
  JSON or fails the protocol, and `score_error`. For the rule on the mean they count as a failed case, score 0
  `[proposed: a version's own timeouts and broken output are part of its effect; dropping them would pull Δ toward 0 for
  exactly the breaks that cause them]`. The rule on checks gets no result from such a record (`None`, as the gate's
  `check_runs` gives it), so it cannot see the failure. Reported per side. Sensitivity: version errors dropped as in the
  drift job.
- **Sessions.** A session with no usable records, or keeping fewer than 4 of its 5 rounds, is dropped and recorded once
  more at the end of the window. A session is dropped if a version records a `config_hash` other than its tag's, or if
  both versions requested the same model and the API reported different ones (the gate's own rule; S12, R09 and S16
  request different models by design). A change whose new version cannot run at all is fixed without changing its intent
  and recorded again; a deviation.

### B: declared changes (01.–11.12.2026)

Each change: 4 sessions of 5 rounds, 20 rounds per version `[proposed: twice the budget B = 10, which leaves rounds for a
second budget (Experiment 5) and for retries; for telecom, 20 = B]`. Each setting except telecom also gets an **A/A
pool**: the release against itself, 4 sessions. "Upper bound" is the size if every targeted case failed in every run; one
support case is 1.9 points, one receipt field 0.83, one telecom task 10. **Origin**: *organic* changes come from the
applications' own history (only S12 and R09); *demo* changes are the applications' demo pull requests of 25.–30.10.2026
(`demo #n` = pull request #n of that repository); *study* changes are written for this plan. An **anchor** is the
difference a demo pull request showed when the gate ran it once on 15.11.2026 (2–5 rounds, exploratory, a different gate
version), not a truth.

**Support agent alone** (15 changes, S16 pending):

| Id | Change (`policy.md` unless stated) | Origin, type | Cases that should catch it | Expected size |
|---|---|---|---|---|
| S01 | "A booking lasts 1 to 4 whole hours and must start…" → "A booking must start…" | study, break | `book-5h` | ≤ 1.9 |
| S02 | drop "Book the smallest room that fits the group." | study, break | `room-for-4`, `room-for-one` | ≤ 3.8 |
| S03 | drop "If several bookings could match the request, ask which one the member means. Do not guess." | study, break | `which-booking-solo`, `two-desks-same-day` | ≤ 3.8 |
| S04 | drop "and must start and end within opening hours" from the booking-length line | study, break | `book-before-opening`, `book-past-closing`, `book-sunday-5-to-9pm` | ≤ 5.7 |
| S05 | drop the member check and the overlap rule (`drift/change-1`, `fddf8cd`) | demo #2, break | `name-mismatch`, `wrong-name`, `unknown-email`, `email-plus-alias`, `overlap` | anchor −6.4 |
| S06 | credit limit €30 → €75 (`b3609ba`; the cases know €30) | demo #6, break | `cancel-big-credit`, `credit-45-escalates`, `cancel-45-at-24h`, `split-big-credit`, `cancel-all-ill` | anchor −8.7 |
| S07 | the two 24-hour bullets → "The member gets a credit of the full price…" | study, break | `cancel-23h`, `cancel-23h45`, `cancel-45-at-23h`, `cancel-late`, `late-refund-manager`, `move-23h`, `move-within-24h`, `claims-12h-rule`, `cancel-all-ill` | ≤ 17.0 |
| S08 | confirm every booking with the member first (`77d07a8`) | demo #8, break | `book-4h`, `book-adjacent`, `book-at-opening`, `book-desk`, `book-room`, `book-saturday-4-to-8`, `book-until-closing`, `move-23h`, `move-booking`, `move-exactly-24h`, `move-within-24h`, `room-for-10`, `room-for-4`, `room-for-5`, `room-for-one` | anchor −23.4 |
| S09 | `tools.yaml`: `cancel_booking` "…future booking. Issues no credit." → "…future booking." | study, tool | `cancel-early`, `cancel-exactly-24h`, `cancel-30-at-24h`, `credit-exactly-30`, `which-booking`, `cancel-mine-and-colleagues`, `complaint-and-cancel`, `move-booking`, `move-exactly-24h` | ≤ 17.0 |
| S10 | `tools.yaml`: `list_bookings` "List a member's active bookings, earliest first." → "List a member's bookings." | study, tool | `overlap`, `two-desks-same-day`, `which-booking-solo`, `cancel-all-ill` | ≤ 7.5 |
| S11 | `configs/support.yaml`: `effort: high` → `low` | study, model setting | all | [to measure] |
| S12 | old `study/S12-old` (`drift/base` with `model: claude-sonnet-5-5`), new `drift/base`: the switch of 03.11.2026 (`7a579c2`, #17) | organic, smaller model | all | [to measure] |
| S13 | reorder the policy sections (`8c88351`) | demo #1, harmless | none | anchor −0.8 |
| S14 | rewrite the Style section in other words, same three rules | study, harmless | none | 0 |
| S15 | offer the nearest free slot when the requested one is taken (`2f0e2f7`) | demo #7, harmless | `move-to-full-slot`, `room-for-6-large-taken` must not break | anchor +0.4 |
| S16 | new side on `claude-haiku-4-5-20251001`, with a thinking budget in place of adaptive thinking and `effort`; the tag adds the model's price to `prices.yaml` `[pending the author's approval of its cost; removed before the commit if not approved]` | study, older model | all | [to measure] |

**Support agent, simulated user** (7 changes): S03, S05, S06, S08 (in a dialogue the agent can get the confirmation, so
it may be harmless), S09, S11, S13.

**Receipts, one call** (9 changes; `prompts/sroie_image.md` unless stated):

| Id | Change | Origin, type | Fields that should catch it | Expected size |
|---|---|---|---|---|
| R01 | company as the trading name, without the legal form (`11e79c9`) | demo #5, break | `company` | ≤ 25, anchor −13.7 |
| R02 | read the total after the rounding adjustment (`274c7ac`) | demo #6, harmless at δ | `total` where a rounding line is printed | anchor +0.2 |
| R03 | list the fields in the order a receipt prints them (`drift/change-1`, `1d899a0`) | demo #1, harmless | none | anchor −0.2 |
| R04 | total: "the amount paid" → "the subtotal before tax and rounding" | study, break | `total` on receipts that print tax or rounding | ≤ 25 |
| R05 | drop "Copy values as printed." | study, break | `company`, `address` | ≤ 50 |
| R06 | address: drop "on one line" | study, harmless (whitespace is normalised) | `address` must not break | 0 |
| R07 | the pipeline halves the scan's width and height before the call | study, break | all fields | [to measure] |
| R08 | `effort: high` → `low` | study, model setting | all | [to measure] |
| R09 | old `study/R09-old` (`drift/base` with `model: claude-sonnet-5-5`), new `drift/base`: the switch of 03.11.2026 (`1775ff7`, #13) | organic, smaller model | all | [to measure] |

**Receipts, two calls** (5 study changes, on `study/steps-base`): Q01 the check prompt's "Keep a field when the receipt
confirms it and fix it when the receipt shows another value." → "Return the fields as given." (the second call stops
correcting); Q02 R04 in the extract prompt only (can the check repair it); Q03 R01 in the extract prompt only; Q04
`effort: low` in both calls; Q05 R03 in both prompts (harmless). Sizes [to measure].

**Telecom** (4 changes, `policy/` unless stated). Tasks are named by their position in `golden/telecom-pr.yaml` (1–10):

| Id | Change | Origin, type | Tasks that should catch it | Expected size |
|---|---|---|---|---|
| T01 | drop the roaming, Data Saver and VPN steps from the manual (`671f6ec`) | demo #2, break | 3–8 (a `user_abroad_roaming_*`, `bad_vpn` or `data_saver_mode_on` issue) | ≤ 60, anchor 0 (1 run) |
| T02 | data roaming becomes a paid add-on, enabled only after consent (`b917893`; the tasks do not know it) | demo #6, break | 3–8 (a `user_abroad_roaming_*` issue) | ≤ 60, anchor −50 (1 run) |
| T03 | fix typos in the policy (`d0e443e`) | demo #1, harmless | none | anchor 0 (1 run) |
| T04 | `effort: high` → `low` | study, model setting | all | [to measure] |

**Smaller model.** No Claude model is cheaper than Haiku 5.5. The only other Haiku the API offers is Haiku 4.5
(`claude-haiku-4-5-20251001`, Models API, 24.11.2026), a previous generation at about ten times the token price that
takes a thinking budget instead of `effort`. Three kinds of change stand in for a smaller model: the organic switch from
Sonnet 5.5 to Haiku 5.5 (S12, R09; too expensive for telecom), the cheaper setting `effort: low` of the same model (S11,
R08, Q04, T04), and, if approved, Haiku 4.5 as the new side (S16) `[proposed: the smaller-model breaks available with
one provider]`.

In all: 40 declared changes (support alone 15, with simulated user 7, receipts 9 + 5, telecom 4), plus S16 if approved.

### C: ground truth (01.–11.12.2026)

S03, S06, S09 and S11 (support agent alone) get 4 more sessions each: 40 rounds per version `[proposed: 40, the middle
of 30–50; these four lie near δ or have unknown size and cover a policy line, a tool description and a model setting]`.
Their true effect, with a 95 % interval resampling whole sessions, is the reference for decisions made on fewer rounds.
S05 is not in C: its true effect comes from its B pool, and its 42 drift jobs give a check in January.

### D: chain of small breaks (01.–11.12.2026)

Support agent alone. Release `V0 = drift/base`; each version adds one study break of two cases to the previous:

| Version | Adds | Cases that should catch it | Upper bound of the step |
|---|---|---|---|
| V1 | drop "Bookings are for the future only." and the 4-hour limit (as S01) | `book-in-the-past`, `book-5h` | 3.8 |
| V2 | as S02 (smallest room) | `room-for-4`, `room-for-one` | 3.8 |
| V3 | as S03 (do not guess) | `which-booking-solo`, `two-desks-same-day` | 3.8 |
| V4 | drop the Basic-plan rule and "Check that the new slot is free before you cancel the old booking." | `room-on-basic`, `move-to-full-slot` | 3.8 |
| V5 | drop "Members can cancel their own future bookings." | `cancel-someone-elses`, `cancel-mine-and-colleagues` | 3.8 |

Every step stays below δ even if its cases always fail; together the chain reaches 18.9 points against V0, more than δ
if the targeted cases fail in more than about 27 % of the runs `[proposed: length 5, two cases a step]`. A session is one
job that runs all six versions in parallel, 5 rounds each, with the gate's runner, so every pair of versions has both
sides from the same job; 4 sessions. If a step's true effect is worse than δ, or V5 is not worse than δ against V0, the
chain is analysed as recorded and the failed premise reported.

### E: held-out pool (Mon 14.12.–Sun 20.12.2026)

Recorded like B in a different calendar week, 4 sessions per change (the depth of B, not of C: cost), analysed once
(Experiment 10). Support alone: A/A, S03, S05, S06, S09, S11, S13. Simulated user: A/A, S05, S06, S13. Receipts one call:
A/A, R01, R02, R04, R07. Receipts two calls: A/A, Q01, Q03. Telecom: T01, T02. True effects for E come from E's own
runs. E's A/A pools are held-out too: no main analysis reads them.

### F: real same-version pull requests (01.–25.12.2026)

25 pull requests in `workbench-support` and 25 in `receipt-intake`, one a day per repository; none in telecom
`[proposed: 50, the upper end named; telecom costs $5–11 a decision]`. Each edits a code comment in the pipeline's
source, so the gate runs both versions and their behaviour is identical `[proposed: a pull request with no code change
is skipped by the gate]`. Before the first one, a commit on each repository's `main` sets the gate to the freeze tag
with `delta: 5`, `alpha: 0.05`, `max_spend_usd` = `L_team` and `base_max_age_hours: 0`. One job per pull request; a
re-run is a retry, analysed apart. F is not blind: the gate's comment shows each verdict; F's design is fixed here and
does not change with them. Measure: the gate's own verdict; the recorded rounds are also replayed through every rule (a
rule that needs more rounds than the job ran is undecided). Telecom's false blocks rest on its 12 drift jobs only and
are descriptive, as in `drift-job.md`.

## Decision rules

**Equal model calls** means equal rounds: every rule reads at most `B` rounds per decision, AgentiCI with `L_pair` and
the same cap. Rules without a baseline spend less: the confidence bound reads `B` candidate runs (half the calls), the
single run reads one; their cost says so.

**AgentiCI**: as above.

**Comparators**, each built to change one property while keeping the rule on checks and the error split:

1. **Fixed-sample non-inferiority (FS-n)**, as ARCI documents: "per arm, an exact Clopper-Pearson interval at tail
   alpha / (4K)" (T58-f) and "bounds on the difference by Bonferroni" (T58-g). With one look, `K = 1`, each arm's tail is
   `α / 4 = 0.0125`, so each bound on the difference errs with probability at most `α / 2 = α_mean`. After exactly `n`
   rounds: pass if the lower bound is above `−δ`, block if the upper bound is below `−δ`, else undecided. The binary trials
   are the units `S` averages: case runs (support, telecom), field results (receipts). The rule on checks looks once at
   round `n` (its first `min(n, 10)` runs) if `n ≥ 5`; with `n < 5` it does not look, as in the gate. Primary `n = B`;
   Experiment 4 also uses `n = 2…B`. Besides fixing the sample, FS-n bounds each arm instead of the paired difference
   and reads more runs for checks, so it does not isolate adaptive stopping alone.
2. **Sequential with a run cap (RC):** AgentiCI stopped by a cap of `B` rounds instead of a money limit, as lcb-gate and
   peeksafe document a cap (T72-c, T72-d, T52-i, T52-j).
3. **AgentiCI, proof of harm (PH):** AgentiCI, but undecided at the end becomes pass. A block still needs `U_t < −δ`, so
   the two differ only in who carries the burden of proof; on the same draws their rounds and cost are identical.

**Reference rules** (current practice; no property of AgentiCI is tested):

| Rule | Decision | Parameters | Source |
|---|---|---|---|
| Single run | one run of the candidate; block if `S_c < τ` | `τ = S̄_release − δ` `[proposed: our applications' levels differ; a team sets its threshold from its own score]`; sensitivity: `τ = 0.80` (T40-d, T97-k); on the suite score `[proposed: T40-c applies the threshold to each case, T33-d to each metric; the suite score is our one metric]` | T33-l, T40-d |
| Fixed n | `n` runs per version; block if `S̄_b − S̄_c > d` | `n = B`; `d` = 5 points `[proposed: T32-u gives the rule without a value; 5 points is T97-l's value and equals δ]` | T32-c, T32-s, T32-u, T97-l |
| Stored baseline | `n` runs of the candidate; block if the mean of `n` stored release runs minus `S̄_c` exceeds `d` | `n = B`; `d` = 5 points. Stored runs: `B` runs of side `b` of the setting's A/A pool in B, its sessions in random order; in a decision on that A/A pool itself, only sessions the candidate does not use. Drift decisions: side `b` of the setting's previous unchanged pair. Not computed for telecom in December (no A/A pool) and for S12 and R09 (no stored release on Sonnet 5.5) | T24-c, T32-b, T32-u |
| McNemar | binary case outcome (all checks, or all fields, right); `n` runs per version; a case whose outcome differs between its runs of either version is excluded `[proposed: T28-h excludes cases that flip between repeated runs, T28-m repeats the candidate; applied to both versions]`; exact one-sided McNemar on the remaining discordant cases; block if `p < 0.05` | `n = B`; level 0.05 `[proposed: the level a census gate documents, T97-m; T26, T28, T29 give none]` | T26-d, T28-b, T28-h, T28-m, T29-b |
| Confidence bound | Wilson lower bound of the candidate's pass rate over `n` runs (trials as in FS-n); block if below `τ` | `n = B`; one-sided 95 %, as lcb-gate documents ("with 95% confidence the true pass rate is at least X", T72-j); `τ` as for single run | T24-f, T26-b, T26-r, T72-a, T72-j |

`S̄_release` is the mean score of the release over both sides of its A/A pool in B (telecom: over the old sides of its
four pools); for S12 and R09 it is the mean of the change's own old side. The frozen code computes it before any
decision is simulated.

## Simulator

- **Primary scheme: fixed cases.** The gate's guarantee holds for the case set it runs, so the cases are not resampled. A
  simulated decision takes the change's sessions in a random order and, within each session, its 5 rounds in a random
  order (rounds are repetition indices, exchangeable within a job); rounds are fed to the rule in that order. **Within one
  decision no session copy and no round is used twice.** A rule stops at its verdict, its budget or its limit; a decision
  that reaches the end of the pool first is undecided ("pool end", counted, and left out of cost means).
- **Orderings.** 1 000 random orderings per change, the same orderings for every rule (common random numbers); seed
  20261214 plus the change's position in this document. Shares over orderings are the point estimates; their Monte Carlo
  standard errors are reported.
- **Disjoint decisions** (the units of every interval and confirmation). For each change and rule: sessions and rounds in
  recorded order; the first decision starts at the first round and runs until it stops; the next starts at the first
  session it has not touched; a decision that runs out of pool is undecided. The `M` disjoint decisions of a change are
  independent if its sessions are (Experiment 1 tests that). Every rate shows `x/M` beside its 1 000-order estimate.
- **Money.** Round costs from tokens × prices; AgentiCI's estimate of the next round is the gate's (the last round of
  each version). The loop reimplements `pr.buy` and is checked against it on recorded runs.
- **Validation before use.** On the runs recorded on 03.11.2026 (model comparison) and 15.11.2026 (demo pull requests)
  and on the gate's test fixtures, the simulator's AgentiCI verdict, round and capital equal those of the freeze tag's
  functions; the reference rules match hand-computed cases in tests. No drift-job score is read for this.
- **Sensitivity analyses**, reported next to the primary, never used to confirm or refute:
  - *Resampled cases* (estimand: cases like these, as Section 8.1 of the paper describes the simulator): `N` cases drawn
    with replacement, true effect recomputed on the drawn cases. A case drawn twice enters one run twice, which breaks the
    independence the bet assumes; error rates in this scheme can exceed `α_mean` without a fault in the gate.
  - *Independent rounds*: rounds drawn without replacement from all sessions of the change, ignoring which job they came
    from.
  - *Version errors dropped*, as in the drift job.

## Intervals

Every rate has a 95 % interval. Rates over disjoint decisions: Clopper–Pearson, so an interval exists with zero events;
drift jobs and F: Wilson, as in `drift-job.md`. A rate pooled over changes weights every change equally. A cell reports
how many changes it rests on; it counts a change only by the change's own `Δ`.

**Bootstrap of differences and ratios** (Experiments 4, 6, 7): 2 000 resamples, percentile intervals. In each resample,
the changes of the setting are drawn with replacement; within each drawn change, its sessions are drawn with replacement
and taken in the drawn order; the disjoint decisions of every rule are then built over that sequence as above, except
that a session copy whose original is already in the current decision is skipped. Statistics that depend on a choice
(`n*` in Experiment 4) are recomputed in each resample. When a decision can need every session of a change (`B = R`:
telecom), only the changes are resampled, with their sessions as recorded.

## Experiments

### Experiment 2: False blocks and reusing a baseline (A, F, A/A pools of B)

- **Measures.** Same-job false-block rate per rule and setting from the drift job, rounds stopped at 5, as Q4 of
  `drift-job.md` (Table 9b); the same rate at the full budget `B` from the A/A pools of B (support alone, simulated user,
  both receipt settings; descriptive, 2–4 disjoint decisions each); the rate by gap (Fig. 6) and the validity window, as
  Q4; F: the gate's verdicts and the replayed rules. Simulated user and receipts with two calls are not in the drift job:
  their Table 9b cells come from the 4 A/A sessions of B, one decision per session at `B = 5`, and are descriptive.
  Telecom's cells are descriptive (12 jobs).
- **Confirmation.** As Q4 of `drift-job.md`, per setting: at its level if the upper Wilson bound of the gate's same-job
  rate is at most 0.05, above if the lower bound exceeds 0.05, else undetermined. F is reported with the same three
  outcomes and does not override the drift job.

### Experiment 3: False passes and detection (B, C)

- **Measures.** Per rule and setting: the false-pass rate over changes worse than δ (Table 9a), and over the changes in
  the boundary bin `[5, 7.5)` (text, next to it); detection, pass and undecided per change (points) and per size bin
  (Fig. 3); for blocks, which rule blocked. Each rate with `x/M`.
- **Confirmation of the bound** (AgentiCI, per setting, over the changes worse than δ):
  - **refuted** if for some change the Clopper–Pearson lower bound of its pass share over its disjoint decisions, at
    one-sided level 0.025 / m (Bonferroni over the setting's `m` changes worse than δ), exceeds 0.025, or the pooled share
    over all their disjoint decisions has a one-sided 0.025 lower bound above 0.025. The two tests together refute a
    gate that keeps its bound with probability at most 0.05 per setting;
  - **at its level** if the pooled Clopper–Pearson upper bound over the disjoint decisions of the boundary-bin changes is
    at most 0.025. With no pass this needs 146 disjoint decisions; the pools give a few per change, so this outcome is not
    reachable and the bound rests on Experiment 8;
  - otherwise **undetermined**, the expected outcome.
  Settings with no change worse than δ by its own `Δ` report none.

### Experiment 4: Adaptive evidence against a fixed sample (decisions of 3)

- **Measures.** Per rule: median and mean cost and rounds per decision against detection over all changes worse than δ
  in the setting (Fig. 4); AgentiCI's rounds and cost per change and size bin; FS-n for `n = 2…B`.
- **Rule.** `n*` is the smallest `n` at which FS-n's block share over the changes worse than δ and its pass share over
  the clearly harmless changes are both `≥` AgentiCI's; it is chosen on the point estimates and again in every
  resample. Adaptive evidence pays off in a setting if the 95 % interval of AgentiCI's mean cost per decision divided by
  FS-`n*`'s (all decisions of the setting) lies below 1, does not if it lies above 1, and is otherwise undetermined. At
  `n* = B` the ratio cannot exceed 1, since AgentiCI never uses more than `B` rounds; the claim is then only that it
  stops earlier on average, and it is reported as such. If no `n ≤ B` reaches both, AgentiCI's quality gap over FS-`B`
  (the shortfall of FS-`B` in block share or in pass share, whichever is larger) must have a bootstrap interval above 0
  for "pays off"; otherwise undetermined. Telecom, and any setting with no change worse than δ or none clearly harmless,
  is described only. The size bins in which FS-`n*` costs less are named.

### Experiment 5: Undecided verdicts and the money limit (decisions of 3, token logs)

- **Measures.** With `L_team`, no cap: share undecided per setting and size bin; rounds per decision; the share of
  undecided decisions that a second budget (the same sequence continued for `B` more rounds, the gate's continue)
  decides, and how many of those correctly (pass with `Δ > −δ`, block with `Δ ≤ −δ`), on pools with at least `2B`
  rounds (not telecom); error of the cost estimate, `(estimate − actual) / actual`, over every recorded round of A–F
  (median, 5th and 95th percentile); share of decisions whose spend exceeds `L_team`, and by how much. Compared with the
  capped run under `L_pair`, the difference shows what a candidate's own cost does to the rounds it gets.
- **Descriptive thresholds** on the point estimates: the limit is adequate in a setting if at most 20 % of decisions on
  clearly harmless changes end undecided and spending exceeds the limit in at most 5 % of decisions `[proposed:
  judgement, no source; the gate allows a small overspend by design]`.

### Experiment 6: Burden of proof (decisions of 3; descriptive)

AgentiCI and PH per change and in the size bins `[0, 2.5)`, `[2.5, 5)`, `[5, 7.5)`, `[7.5, 10)`: pass, block,
undecided. On the same draws PH passes every decision AgentiCI passes, so its false-pass rate cannot be lower; what is
measured is how much higher it is on the changes worse than δ (boundary bin) and how many harmless near-δ changes
(`[2.5, 5)`) AgentiCI leaves undecided or blocks where PH passes. Rounds and cost are equal by construction.

### Experiment 7: Use in practice (B, C, D)

- **Sweep** (one parameter at a time around the registered values): `δ ∈ {2, 3, 5, 7.5, 10}` points, `α ∈ {0.01, 0.025,
  0.05, 0.10}` (split in halves as above), the limit `L_team · {0.5, 1, 2}` with the cap moved alike. `K_pass` and `B`
  follow their rules for each value; a value whose `K_pass` exceeds the pool's rounds is not computed (telecom at δ = 2
  needs 25 rounds); `2 · L_team` only where pools have `2B` rounds. Classes are recomputed at each δ. Reported: false
  passes, undecided share, mean cost, detection over changes worse than δ.
- **Retries** (descriptive). After a block or undecided verdict the developer re-triggers the gate up to `k = 3` times
  `[proposed: no data on how often developers re-trigger; every k from 0 to 3 is reported, and 40 rounds allow 3]`:
  (a) from scratch, a new decision on rounds not used before; (b) continuing the same sequence for another budget, checks
  not read again, as the gate continues. Continuing after a block changes nothing (the first decision is kept,
  `mean.first`), so (b) applies after undecided only. False-pass rate after 0…3 retries. Rounds: whole sessions on the
  C pools; independent rounds without replacement on the other pools, as far as they reach. C holds at most two changes
  worse than δ, so no confirmation is attempted.
- **Chain** (D; descriptive). AgentiCI along V0…V5 over 1 000 orderings of D's sessions: (a) each version against its
  predecessor; (b) against its predecessor and against V0, both needing a pass, δ = 5 for both. A version merges only on
  pass; the chain stops at the first version not merged `[proposed: later versions are built on the blocked one]`.
  Measure: true effect of the last merged version against V0; share of chains that merge more than δ of degradation, for
  (a) and (b). (b) merges no more than (a) by construction; the size of the gap is the result.

### Experiment 8: Synthetic: known effect, correlation and drift (no model calls)

- **Model.** Settings support alone, receipts one call (decisions) and telecom (descriptive), each with its cases, checks
  and per-check pass rates `q` of the release from data set B, clipped to `[0.5 / R, 1 − 0.5 / R]` with `R` the release's
  runs of that case `[proposed: a check never or always passed would sit at ±∞]`. Check `h` of case `i` in run `t` of job
  `j` for version `v` passes if `Z < c · Φ⁻¹(q_{h,i}^v) + ζ_{i,t}^v + u_{j,t}^v + w_j^v`, where `Z` is standard normal;
  `ζ_{i,t}^v` is shared by the checks of one case run of one version, SD 0.5 `[proposed]`, independent across versions;
  `u_{j,t}^v` is shared by all calls of one run, SD `σ_r` (it breaks the independent calls the bet assumes); `w_j^v` is
  shared by all runs of one version in one job, SD `σ_j`, with correlation `r` between the two versions (`r < 1`: drift
  that hits versions differently); `c = √(1 + 0.25 + σ_r² + σ_j²)` keeps each check's marginal pass rate at `q`.
- **Jobs.** Primary: **all rounds of a decision in one job**, sharing one `w_j^v` per version, as `pr.buy` buys them.
  Sensitivity: a new job every 5 rounds.
- **Effects.** The candidate's thresholds are shifted so that the true mean difference is exactly `μ` (numerical
  integration), in four shapes. Cases are ranked by the release's pass rate, most reliable first, ties by id. Diffuse:
  every check shifted alike. One slice: cases fail fully in rank order, the last one partly, until `μ`. Heavy tail: cases
  fail fully in rank order until `μ/2`; every other check shifts alike for the rest. Negative flips: cases fail fully in
  rank order until `1.5 μ`; the least reliable cases, from the bottom of the ranking, improve to pass rate 1 until
  `−0.5 μ`; if their headroom is too small, the shape is skipped for that setting and reported.
- **Grid.** `σ_r ∈ {0, 0.1, 0.3}`, `σ_j ∈ {0, 0.1, 0.3}`, `r ∈ {1, 0.5, 0}` (21 distinct cells), `μ ∈ {0, −δ/2, −δ,
  −1.5δ, −2δ}`. 10 000 decisions per cell at `μ ∈ {0, −δ}`, 2 000 elsewhere. Rules: AgentiCI as built (unit `case`);
  reported beside it: AgentiCI with unit `run` (one bet per run), each of its two rules alone.
- **Measures and rule.** AgentiCI's false pass at `μ = −δ` (each shape) against 0.025 and the whole gate's false block at
  `μ = 0` against 0.05. An error exceeds its level if it is above level + 3 Monte Carlo SE (0.0016 at 0.025, 0.0022 at
  0.05). In the cells with `σ_r = σ_j = 0` no error may exceed; if one does, the code is wrong: stop and fix.
- **January calibration** (support agent, receipts; telecom with point estimates, descriptive). Targets from
  `drift-job.md`, Q1: the design effect of the cases of one run, `ρ_D` of the unchanged pair, `ρ_D` of the change pair
  (each at its upper 95 % bound) and `ρ_S`, the correlation of two runs of one side of one job. In the model, `w_j^v`
  carries all that two runs of one side in one job share: the day, job and side parts of the drift job's variance split;
  its correlation `r` between versions is the part the two sides share (day and job). Procedure: on the grid
  `σ_r, σ_j ∈ {0, 0.025, …, 0.6}`, `r ∈ {0, 0.05, …, 1}` (so `r` stays in `[0, 1]`), simulate 400 series with the
  setting's design (its number of jobs, 5 rounds per side, the unchanged pair, and the change pair with S05's or R03's B
  profile as the candidate), compute the four statistics with the estimators of `drift-job.md` and take each statistic's
  mean over the 400 series; choose the point that minimises the sum of squared differences from the targets, each
  divided by the target's bootstrap SE. Then rerun the error cells at that point, primary job scheme. **Confirmation:**
  neither AgentiCI error exceeds its level at the calibrated point, in any shape; **refuted** if one does. The result is
  stated in Sections 6.2 and 10 as supported by simulation, not as a proof.

### Experiment 9: Stress: whole sessions go bad (A; January)

Drift-job scores open after 05.01.2027, so this runs in January. Per setting, worst jobs: the `max(3, ⌊0.1 · J⌋)` jobs
with the lowest mean `S` of the unchanged pair (`J` = jobs kept; 8 of 84 for the support agent and the receipt reader, 3
for telecom). Each worst job gives one decision at `B = 5` for every rule incl. the rule on checks: false blocks on the
unchanged pair; false passes on S05's pair in the support agent's 14:23 jobs, worst jobs chosen among those 42 (4), if
S05's true effect over all its drift-job runs is worse than δ. R03's pair (harmless) is described. Measure: each rule's
rate in the worst jobs against all jobs, the difference with a bootstrap interval over days. Descriptive.

### Experiment 10: Held-out (E; once)

Run once, after the results of Experiments 2 and 3 on A–D are committed, with the frozen code and the same rules,
parameters and criteria; E's A/A pools give Experiment 2's full-budget rates, its changes Experiment 3. Outcomes per
claim with a decisive main verdict: **replicated** if E gives the same verdict; **contradicted** if E gives the opposite
decisive verdict (at its level against above or refuted); **not replicated (underpowered)** if E is undetermined. If the
main verdict is undetermined, both estimates are reported side by side and no replication is claimed.

## Exploratory

Everything not registered above, including: the full parameter grid beyond one factor at a time; the second model;
other domains of τ²-bench; telecom with the simulated user; any change, rule or setting added after this commit; the
demo pull request runs of 15.11.2026.

## Cost of recording B–F

Round costs (both versions) on Haiku 5.5 from `drift-job.md`: support alone $0.158, receipts $0.021, telecom $0.556;
simulated user ≈ $0.23 [to measure; each $0.01 more adds ≈ $1.60 to B, ≈ $0.80 to each of its two weeks, and ≈ $0.80
to E]. Old sides on other models: ≈ $1.27 per Sonnet 5.5 support run (workbench PR #16, 03.11.), ≈ $0.18 per Sonnet 5.5
receipt run (receipt PR #12). New side of S16: ≈ $0.79 per Haiku 4.5 support run [to measure; ten times the token price
of Haiku 5.5]. Pools: 20 rounds.

| Data | Setting | Pools | Rounds | Cost |
|---|---|---|---|---|
| B | Support alone | 14 changes + A/A | 300 | $47.40 |
| B | Support alone, S12 (old side on Sonnet 5.5) | 1 | 20 | ≈ $27.00 |
| B | Simulated user | 7 + A/A | 160 | ≈ $36.80 |
| B | Receipts, one call | 8 + A/A; R09 (old side on Sonnet 5.5) | 180; 20 | ≈ $7.60 |
| B | Receipts, two calls | 5 + A/A | 120 | ≈ $2.50 [to measure] |
| B | Telecom | 4 | 80 | $44.50 |
| C | Support alone | 4 × 20 more | 80 | $12.60 |
| D | Support alone | 6 versions × 20 runs | 60 | $9.50 |
| E | Support alone | 6 + A/A | 140 | $22.10 |
| E | Simulated user | 3 + A/A | 80 | ≈ $18.40 |
| E | Receipts | 4 + A/A; 2 + A/A | 100; 60 | ≈ $3.40 |
| E | Telecom | 2 | 40 | $22.20 |
| F | Support alone, receipts | 25 + 25 pull requests | ≥ 5 each | ≈ $22.40 (at most ≈ $47) |
| | **B–F** | | | **≈ $276 (at most ≈ $301)** |
| B | S16, if approved (new side on Haiku 4.5) | 1 | 20 | ≈ $17.40 [to measure] |

The drift job (A, ≈ $148, about $25 a week) runs over the same weeks. With the split above (F about $6 a week), the
weeks 30.11.–06.12., 07.–13.12. and 14.–20.12. carry about $122, $128 and $97 of A–F; S16 would add about $9 to each of
the first two.

## Threats known in advance

- One model family and provider; three applications; one case set per setting.
- The two receipt settings differ in input (scan, OCR text) as well as in the number of calls.
- Few changes worse than δ per setting and few disjoint decisions per change: the bound on false passes can be refuted on
  real changes but not confirmed; Experiment 8 carries that check.
- In B–E a decision of more than 5 rounds spans two sessions, while the gate buys all rounds of a decision in one job.
  If job effects hit the versions differently, a pool decision averages two jobs' shifts and can understate the gate's
  errors; Experiment 8's primary scheme keeps a decision in one job.
- FS-n differs from AgentiCI in more than adaptive stopping (per-arm bounds, more runs read for checks); its gap to
  AgentiCI is not due to adaptivity alone.
- The true effect of a change includes the runs its decisions read; near δ this can move a change between classes.
- Sessions follow a schedule: time of day is partly confounded with the change.
