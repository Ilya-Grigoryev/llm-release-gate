# Drift job: pre-registration

Registered 24.11.2026, before the first run. Changes after this commit go to `deviations.md` with their date; an analysis
not described here is reported as exploratory. Rules and parameters of the compared decision rules, the simulator and
the other data sets are in the main pre-registration (`preregistration.md`, due 30.11.2026), which is committed before any
of this data is analysed.

## Questions

1. Are the rounds of one CI job independent draws, and how much of the variance lies between days, between jobs on the
   same day and between runs within one job? (Experiment 1)
2. Do shifts between sessions hit two versions differently: does the difference between the old and the new version of
   a declared change move from job to job? (Experiment 1)
3. Do jumps in the mean score line up with what the provider reports or with the time of day? (Experiment 1)
4. How often does a rule block an unchanged version with both sides from one job, and how does the rate change when the
   two sides come from jobs hours apart? (Experiment 2, the drift-job part)

## Design

**Settings.** All on `claude-haiku-5-5`, the model each application's config asks for, frozen at the tag `drift/base` in
each application's repository for the whole series:

| Setting | Repository, pipeline | Cases | Schedule (UTC; Vienna is UTC+1) |
|---|---|---|---|
| Support agent, alone | `workbench-support`, `support` (`golden/solo`) | 53 | daily 02:23 (night) and 14:23 (afternoon) |
| Receipt reader, one call | `receipt-intake`, `sroie-image` (`golden/sroie`) | 30 | daily 14:53 |
| Telecom (tau2-bench) | `telecom-support`, `telecom` (`golden/telecom-pr`) | 10 | Monday and Thursday 14:37 |

Not in the series from the start: the support agent against the simulated user (cost, see below) and the receipt reader
with two calls (its pipeline is not finished). Either may join through an amendment registered before its first run; it
is then analysed by the same rules as its own, shorter series.

**A job.** A scheduled GitHub Actions workflow (`.github/workflows/drift.yml`) checks out `drift/base` and runs
`llm-release-gate pr --base HEAD --rounds 5` (orchestration from gate `v0.1.0-dev.21`; the runner comes from the
application's locked environment, gate `v0.1.0-dev.20`, record version 7). Both sides are the same version, each in its
own tree and process, run in parallel in one job; each side runs every case 5 times (5 rounds), exactly as the gate runs
its first batch of rounds. A job gives 10 runs of the unchanged version: 5 per side.

**The declared change.** In every afternoon job of the support agent, after the unchanged pair, the same job runs
`pr --base drift/base --rounds 5` from the tag `drift/change-1`: `drift/base` plus the commit "Drop the member check and
the overlap rule" (10 lines of `policy.md`; demo pull request workbench #2, measured at −6.4 points, interval
[−13.1, −1.9], after 5 rounds on 15.11.). It gives 5 runs of each version, in one job, after the unchanged pair.

**Duration.** From the first scheduled run (25.11.2026) to 05.01.2027 inclusive; then the schedules are removed.
Expected: 84 support jobs, 42 receipt jobs, 12 telecom jobs, 42 declared-change pairs. A GitHub schedule may start late
or skip a run; actual start times are taken from the records.

**What every run records** (record version 7): `model` as the API reports it, `requested_model`, `request_id`,
`timestamp`, `retries`, `usage` with cost, `ci_job` (repository, run id, attempt, job), `config_hash`, `set_hash`,
per-check results and the case score. The provider returns no other version information that the runner keeps.

**Data.** The workflow uploads each job's output as an artifact (kept 90 days); `fetch-drift.sh` copies them to
`data/runs/drift/` at least once a week. Nothing is deleted or rewritten.

**Blinding.** Until the analysis (after the last job), monitoring reads only operational fields: errors, retries, cost,
`ci_job`, counts of runs. Scores, verdicts and comments of drift jobs are not opened.

**Exclusions.** A job with an infrastructure error is dropped. A job in which more than 10 % of the runs ended with an
error is dropped; otherwise its errored runs are dropped and the rest kept. A re-run of a job (attempt 2 or later) is a
job of its own.

**Stop.** If the series has cost more than $150, the schedules are removed and the series is analysed as far as it got.

**Cost (estimate).** A round of both sides: support $0.16, receipt $0.02, telecom $0.56. Support 84 × $0.80 = $67,
declared change 42 × $0.80 = $34, receipt 42 × $0.10 = $4, telecom 12 × $2.80 = $34: about $139, about $23 a week.
The simulated-user setting would add about $1.15 a job ($48 for one job a day).

## Measures

- `S`: the score of a run, the mean case score over the set's cases (as the gate computes it).
- `D_t = S_c,t − S_b,t`: the difference between the two sides in round `t` of one job.
- For each check: its pass rate in a run, over the cases it applies to.

## Analysis

All per setting. Intervals are 95 %; bootstrap intervals resample whole days (2 000 resamples, percentile), so they hold
when jobs of one day are correlated. In the settings with one job a day, day and job cannot be separated: they are
reported as one level.

**Q1 — independence of rounds (primary).** The intraclass correlation of `D_t` within jobs, `ρ_D`, by the one-way
random-effects ANOVA estimator over the jobs' unchanged pairs (5 rounds each), truncated at 0, with a bootstrap interval.
The gate decides on `D_t`, so `ρ_D` is what its guarantee assumes to be 0. Effective number of rounds in a job:
`5 / (1 + 4 ρ_D)`.

**Decision on the unit of observation.**
- The upper bound of `ρ_D` is below 0.10 in every setting: rounds in a job count as independent; the run stays the unit
  and the gate stays as it is.
- `ρ_D` (the estimate) is 0.10 or more in some setting: for that setting the between-job part is large; we report what
  requiring runs from at least two jobs, or the job as the unit, costs in money and time per decision, from the recorded
  cost and duration of the jobs.
- Otherwise (estimate below 0.10, upper bound at or above): undetermined; the gate stays as it is and the setting is named
  under threats to validity.

At 0.10, 5 rounds of one job are worth about 3.6 independent rounds.

**Q1 — variance split (descriptive, Table 10).** The run scores `S` of the unchanged version (both sides pooled, side as a
fixed effect) are split into days, jobs within a day and runs within a job by a nested random-effects model fitted by
REML. Reported: the share of each part with bootstrap intervals, the within-job intraclass correlation of `S` and the
effective sample size `10 / (1 + 9 ρ_S)` of one job's runs. The same split is made for the pass rate of each check;
reported as the distribution over checks, naming the checks whose between-job share is above one half.

**Q2 — shifts that hit two versions differently.** For each declared-change job, `Δ_j`, the mean over its 5 rounds of
`S_new − S_old`, with its within-job variance. Heterogeneity across jobs: Cochran's `Q` and the DerSimonian–Laird `τ²`,
tested at α = 0.05. The same is computed for the unchanged pair of the same jobs as a control. The change is said to move
with the session if its `Q` test rejects and its `τ²` exceeds the upper bound of the control's.

**Q3 — jumps.** The mean score of each job over the six weeks, one line per setting (Fig. 5b). A job is a jump if its
mean lies more than 3 standard errors (from its own runs) away from the median of the 7 days around it. Jumps are listed
next to the `model` values the API returned in that job and in the job before, and the time of day. For the support agent,
night and afternoon job means are compared by Welch's t-test (α = 0.05). Descriptive; no claim depends on it.

**Q4 — false blocks on unchanged versions.** For every rule of the main pre-registration (the gate, its three
comparators and the five reference rules, with the parameters fixed there), on the drift jobs:
- **same job**: one decision per job, its side `b` against its side `c`, rounds fed in order; the false-block rate is the
  share of jobs blocked, with a Wilson interval (jobs are the units). A rule that needs more than 5 rounds ends undecided,
  which is not a block; undecided shares are reported apart. The gate's own verdict, recorded by the job, is reported too.
- **hours apart**: side `b` of job `i` against side `c` of job `j`, every ordered pair `i ≠ j` of one setting, gap =
  the difference of their start times. Rates by gap: 12 h, 24 h, 36–48 h, 3–6 days, 7–13 days, 14 days or more, with
  bootstrap intervals.
- **Validity window.** The first gap whose bootstrap lower bound lies above the same-job rate marks where the rate starts
  to rise; the recommended validity window is the largest gap before it. If no gap rises, the window is at least the
  largest gap observed. The support agent's schedule gives no gap between 0 and 12 hours, so the window is resolved to
  12 hours at best.

**Confirmation and refutation.** Q1: independent rounds are confirmed if the first branch of the decision holds and
refuted if the second does. Q2: confirmed if the change moves with the session as defined above. Q4: the gate keeps
false blocks at its level if the upper Wilson bound of its same-job rate is at most α = 0.05 (its false-block level for
the whole gate).

## Threats known in advance

- 12 hours between support jobs: windows shorter than that are not resolved.
- One model family and one provider; three applications.
- GitHub-hosted runners differ between jobs; the runner name is not recorded, `ci_job` is.
- Jobs follow a fixed clock: time of day and day of week are partly confounded with the schedule.
