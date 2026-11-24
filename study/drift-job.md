# Drift job: pre-registration

Registered 24.11.2026, before the first run (first version `3ee64c8`; this version, after review, also before any run).
Changes after the first scheduled run go to `deviations.md` with their date, whether or not data has been looked at; an
analysis not described here is reported as exploratory. Rules and parameters of the compared decision rules, the
simulator and the other data sets are in the main pre-registration (`preregistration.md`, due 30.11.2026), committed
before any of this data is analysed.

## Questions and expectations

1. Are the rounds of one CI job independent draws, and how much of the variance lies between days, between jobs on the
   same day and between runs within one job? (Experiment 1.) Expected: job effects shared by both sides cancel in the
   difference the gate decides on, so for the unchanged pair the upper bound of `ρ_D` falls below 0.10 (power 0.69 with
   84 jobs); the score of a single side varies between jobs at least for the receipt reader (an earlier look at recorded
   runs found a correlation of about 0.35; descriptive, no threshold).
2. Do shifts between sessions hit two different versions differently: does the difference of a declared change move from
   job to job? (Experiment 1.) No expectation: earlier data were too few.
3. Do jumps in the mean score line up with what the provider reports or with the time of day? (Experiment 1, descriptive.)
4. How often does a rule block an unchanged version within 5 rounds with both sides from one job, and how does the rate
   change when the two sides come from jobs hours apart? (Experiment 2, the drift-job part.)

## Design

**Settings.** All on `claude-haiku-5-5`, the model each application's config asks for. Each application's version is
frozen for the whole series by the tag `drift/base`; the declared changes by `drift/change-1` (commits in the table below).

| Setting | Repository, pipeline | Cases | Unchanged pair (UTC; Vienna is UTC+1) | Declared change |
|---|---|---|---|---|
| Support agent, alone | `workbench-support`, `support` (`golden/solo`) | 53 | daily 02:23 and 14:23 | in the 14:23 job |
| Receipt reader, one call | `receipt-intake`, `sroie-image` (`golden/sroie`) | 30 | daily 02:53 and 14:57 | in the 14:57 job |
| Telecom (tau2-bench) | `telecom-support`, `telecom` (`golden/telecom-pr`) | 10 | Monday and Thursday 15:37 | none (cost) |

Not in the series from the start: the support agent against the simulated user (cost) and the receipt reader with two
calls (its pipeline is not finished). Either may join through an amendment registered before its first run, analysed by
the same rules as a series of its own.

**Declared changes.** Support agent: "Drop the member check and the overlap rule" (10 lines of `policy.md`; demo pull
request workbench #2: −6.4 points, interval [−13.1, −1.9], after 5 rounds on 15.11.), a break near δ. Receipt reader:
"List the fields in the order a receipt prints them" (demo pull request receipt #1: −0.17 points, a pass), a different
prompt with the same meaning: whether a session shifts it differently from the original is the question.

**A job.** The scheduled workflow `.github/workflows/drift.yml` checks out `drift/base` and, in one step, runs the
unchanged pair `llm-release-gate pr --base HEAD --rounds 5` and, where scheduled, the change pair
`pr --base drift/base --rounds 5` from `drift/change-1`. Orchestration comes from gate `v0.1.0-dev.21`, layered over the application's
environment (`uv run --with`, so the application's own checks load); the runner from the application's locked environment,
gate `v0.1.0-dev.20` (record version 7). In each pair both sides run in parallel,
each in its own tree and process; each side's runner runs every case 5 times in one call with 4 workers, case by case, as
the gate does with a fixed `k`. A "round" is therefore the repetition index, not a slice of time. The two pairs of a job
alternate their order: the change pair first on odd UTC dates, second on even ones. The verdict each pair records is the
gate's at a fixed 5 rounds, not the adaptive gate's. That recorded verdict comes from the
tree's gate `v0.1.0-dev.20` (Fisher with Tarone's correction on checks) and is not used: Q4 recomputes every rule from
the records.

**Duration.** From the first scheduled run (25.11.2026) to 05.01.2027 inclusive; then the schedules are removed.
Expected: 84 support jobs (42 with the change), 84 receipt jobs (42 with the change), 12 telecom jobs. Only runs started
by the schedule enter the analysis: manual runs are smoke tests, and failed jobs are not re-run.

**What is recorded.** Every run (record version 7): `model` as the API reports it, `requested_model`, `request_id`,
`timestamp` (end of the run), `retries`, token counts, `ci_job`, `config_hash`, `set_hash`, per-check results and the case
score. The records carry no cost (the gate's runner is not given prices); cost is computed from the tokens with each
application's `prices.yaml`, as the gate's `verdict.json` does. Each job also writes `meta.json`: event, schedule, run id
and attempt, runner name, image OS and version, uv version, gate versions, start and end time and exit code of each pair.
The gate's console output goes to a file in the artifact, not to the Actions log.

**Data.** Each job's output is an artifact (kept 90 days). `fetch-drift.sh` copies every job, with the run's metadata
from the GitHub API, to `data/runs/drift/` at least once a week; nothing is deleted or rewritten.

**Blinding.** Until the analysis (after 05.01.2027), monitoring uses only `drift-status.py`, which prints operational
fields (jobs, runs, errors, retries, cost, `ci_job`, whether a pair hit an infrastructure error), never scores,
checks, verdicts or exit codes.

**Stop and cuts.** Weekly, `drift-status.py` gives the cost so far (smoke tests included) and the forecast: the cost so
far plus, for each kind of job (repository, with or without a change pair), the scheduled jobs left times the mean cost
of that kind's jobs so far (before a kind has run, its estimate below). If the forecast exceeds $150, the series is cut
in this order until it fits: (1) the receipt reader's change pair; (2) the support agent's change pair on every other
day; (3) telecom once a week. The schedules are removed when the cost so far plus one more job of the costliest kind
would exceed $150.

**Cost (estimate).** A round of both sides: support $0.158, receipt $0.021, telecom $0.556 (demo pull requests of
15.–16.11.). Support 84 × $0.79 = $66; its change 42 × $0.79 = $33; receipt 84 × $0.105 = $9; its change 42 × $0.105 =
$4; telecom 12 × $2.78 = $33; smoke tests $1.51 (24.11.): about $148, about $25 a week. The simulated-user setting would add
about $1.15 a job.

**Commits frozen by the tags** (the tags can move; these cannot):

| Repository | `drift/base` | `drift/change-1` |
|---|---|---|
| `workbench-support` | `2d6bac65ece2013982e5fbdcdafe8a10f3ed4aae` | `fddf8cd0108adc9ec870e54137fa446ee6134142` |
| `receipt-intake` | `38e31ef3261b3f87d743c2b3fbcf17d2c5eb0ed1` | `1d899a035f70a4df7ebe903046818c48b70f38f0` |
| `telecom-support` | `2402e1784a26ce6cf9fefc0e7fc2092b8e4e905e` | none |

## Measures

- Usable record: `error` is null and `score` is not null.
- `S`: the score of a run, the mean case score over the set's cases with a usable record.
- `D_t = S_c,t − S_b,t`: the difference between the two sides of a pair for repetition `t`.
- Per check: its pass rate in a run, over the cases it applies to.
- Start time of a side: the earliest `timestamp` of its records. Day: the UTC date of the job's start.
- Gap between two sides: the absolute difference of their start times, in hours.

## Exclusions

The unit is the record. A side's repetition in which more than 10 % of the cases have no error-free record is dropped;
otherwise `S` is taken over the cases that have one. Q1 and Q2 use only complete pairs (5 repetitions kept on both
sides), so their formulas stay balanced; the count of incomplete pairs is reported. Q3 and Q4 use a pair if each side
keeps at least 3 repetitions, fed to the rules in order. A job that produced no usable records (checkout, setup or test set failed, timeout) is dropped. The gate's exit
code is not used. The number of dropped pairs and jobs and their times are reported. In every analysis each setting must
show one `config_hash`, one `set_hash` and one `requested_model` per side type; anything else is reported and dropped.

## Analysis

Per setting. Intervals are 95 %. Bootstraps resample whole days with replacement, 2 000 resamples, seed 20261124,
percentile intervals; within a resample, a job drawn twice is never paired with its own copy. Telecom (12 jobs) is reported
descriptively throughout: its power is too low for any decision below.

**Q1 — independence of rounds (primary).** For each pair type (unchanged pair, change pair), `ρ_D`: the intraclass
correlation of `D_t` within jobs by the one-way random-effects ANOVA estimator `(F − 1) / (F + 4)` with `F = MSB / MSW`,
truncated at 0, and its exact interval from the F distribution with `J − 1` and `4J` degrees of freedom (Searle).

Decision per setting:
- **independent**: the upper bound of `ρ_D` is below 0.10 for every pair type of the setting. The run stays the unit and
  the gate stays as it is.
- **large**: for some pair type the F test of no job effect rejects at α = 0.05 and the estimate is 0.10 or more. We
  report what requiring runs from at least two jobs, or the job as the unit, costs in money and time per decision, from
  the recorded cost and duration of the jobs.
- otherwise **undetermined**: the gate stays as it is and the setting is named under threats to validity.

At 0.10, 5 rounds of one job are worth about 3.6 independent rounds. "Large" asks less evidence than "independent" on
purpose: its only consequence is a report of what a stricter unit would cost. Power by simulation (normal data, 4 000 series): with
84 jobs, P(independent | ρ_D = 0) = 0.69 and P(large | ρ_D = 0.2) = 0.98; with 42 jobs, 0.38 and 0.92. The coverage of
the upper bound at ρ_D = 0.10 is 97–98 %. For the support agent and the receipt reader the decision needs both pair types,
so "independent" is reached with probability about 0.26 even if rounds are independent; "undetermined" is the expected
outcome under low power and is reported as such.

**Q1 — variance split (descriptive, Table 10).** The run scores `S` of the unchanged pair, by the nested random-effects
model `S = μ + time of day + day + job within day + side within job + run`, fitted by REML (time of day fixed, the rest
random; in telecom, with one job a day, without the day level). Reported: the share of each random part with bootstrap
intervals, `ρ_S` = the correlation of two runs of the same side of one job (the sum of the day, job and side parts over
the total) and its effective sample size `5 / (1 + 4 ρ_S)`. The same
split for the pass rate of each check that varies at all; checks without variance are counted, and the checks whose
between-job share is above one half are named.

**Q1 — dependence within a run (descriptive).** The design effect of the cases of one run: the variance of `D_t` over the
unchanged pairs against `Σ_i Var(d_i) / N²`, where `d_i` is case `i`'s difference between the sides and `N` the number of
cases. Handed to the synthetic simulation (experiment 8) with `ρ_D` of both pair types, `τ²` of the change and the
between-day variance of `S`.

**Q2 — shifts that hit two versions differently.** For the change pairs, a one-way ANOVA on `D_t` by job: the F test of
no job effect (α = 0.05) and `τ² = max(0, (MSB − MSW) / 5)`. The control is the unchanged pair of the same jobs. The
change **moves with the session** if its F test rejects and the bootstrap lower bound of `τ²_change − τ²_control` is above
0; it **does not move** if the upper bound of its `ρ_D` is below 0.10; otherwise undetermined.

**Q3 — jumps (descriptive).** The mean score of each job over the series, one line per setting (Fig. 5b). A job is a jump
if its mean lies more than 3 × 1.4826 × MAD away from the median of the other jobs' means within 3 days either side
(telecom: 10 days), the window cut at the ends of the series; with MAD = 0 the mean absolute deviation is used, and if
that is 0 too, any difference from the median is a jump. Jumps are listed with the `model` values the API returned in that job and
the one before, and the time of day. Night against afternoon: paired by date, a t test on the job means of the two jobs of
each day (support agent, receipt reader).

**Q4 — false blocks on unchanged versions.** For every rule of the main pre-registration, with its parameters fixed there,
rounds fed in order and the rule stopped at 5 rounds (a rule still undecided at 5 has not blocked; undecided shares are
reported apart):
- **same job**: one decision per unchanged pair, its side `b` against its side `c`. False-block rate: share of jobs
  blocked, Wilson interval. For the gate, per setting: false blocks within 5 rounds are **at its level** if the upper
  bound is at most α = 0.05, **above** if the lower bound exceeds 0.05, otherwise undetermined. Only the support agent and
  the receipt reader (84 jobs each) can reach "at its level", and only with no block in at least 73 jobs.
- **apart**: side `b` of one pair against side `c` of another pair of the same setting and version. Gap bins in hours,
  half-open: [0, 0.5) (the unchanged pair against the change pair's old side, the same version run minutes later in the
  same job), [0.5, 18), [18, 30), [30, 54), [54, 168), [168, 336), [336, ∞). Per bin, the rate and its difference from the
  same-job rate, `Δ_g`, with bootstrap intervals.
- **Validity window** (the gate, support agent): a bin is **safe** if the upper bound of `Δ_g` is at most 0.025 and the
  bound holds for every shorter bin; the rate **rises** at the first bin whose lower bound of `Δ_g` is above 0. The
  recommended window is the largest gap observed in the last safe bin before the first rise (with no rise, in the last
  safe bin); with no safe bin, no reuse is recommended. As a more sensitive measure, the variance of the pair mean `D̄` is reported by bin.

**Confirmation and refutation** are the decisions named above, per setting.

## Threats known in advance

- Low power for "independent" and for receipt and telecom false-block rates; the outcomes say so.
- Support and receipt jobs come 12 hours apart: windows between 30 minutes and 12 hours are not resolved.
- One model family, one provider, three applications; one API key shared with other work in December (pools are recorded
  away from the drift times).
- GitHub-hosted runners differ between jobs and their images change over six weeks; `meta.json` records them.
- Fixed clock times: time of day and day of week are partly confounded with the schedule.
- Wilson intervals treat jobs as independent; two jobs a day may share a day effect.
