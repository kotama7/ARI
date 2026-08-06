# workspace/tools — everything the paper needs to be checkable

One place for the programs the paper depends on, so a claim in the manuscript
can be traced to a program that recomputes it. Nothing here modifies experiment
data; the two `measure_*`/`check_reference_*` programs run scoring jobs and
write results, the rest are read-only.

Each program writes to `--out DIR`, else `$ARI_TOOL_OUT`, else a checkpoint
directory named for the tool. They do NOT write back to the checkpoint they were
originally developed in, so re-running one never overwrites an older run's
record.

## Contents

- `README.md` — this file.
- `_harness_access.py` — **the one way a tool reaches a harness.**
  `verified_harness(task)` calls `ari.harness_registry.load()` first, so every
  sha256 pin and the manifest self-digest are checked before anything is
  measured, and then returns both the registry's `Harness` (prefer it:
  `measure()` applies the manifest's own `[measure_kwargs]`, so a tool never
  restates the scored problem size) and a read-only view of the module for the
  internals some tools legitimately need — `_compile_kernel`, `gen_problem`,
  `_REFERENCE_CFLAGS`, the cached oracles. Eight programs here used to
  `__import__` the harness file directly, which skips the registry entirely;
  `measure_resolution_band.py` is one of them, and it produces the band that is
  copied into `[declares].resolves`, so the number certifying the instrument was
  made by an unverified copy of the instrument.
- `profile_candidate.py` — **why a candidate is slow, at a size and a run count
  you choose.** `measure_absolute_performance.py` says how fast it is; this says
  why: IPC, how often an access leaves L1, what fraction of those reach memory,
  and bytes/cycle where the machine reports its line size — over exactly the
  region the score is built from, with the candidate's own compiler and screened
  flags. Never scored (`scored: false` in every record): a profile that could
  move a score would be a second scoring channel with none of the first one's
  anti-gaming surface.

  The SIZE defaults to the manifest's `[measure_kwargs]`, the size the score is
  taken at, because the harnesses' own defaults are not that — spmm's is ~39x
  smaller, where parallel overhead dominates and every kernel looks alike.
  `--reps` is how many independent PROCESSES per case (default 3: one point has
  no spread, and this study has already mistaken run-to-run variance for an
  effect), using the scored input-seed formula so point r lines up with scored
  repetition r. There is no warmup and no in-process repetition — the score is
  one cold call per process, and a warm profile would describe a regime the score
  never measures. `--plan-only` prints the shape of the run and its process count
  before spending anything.

  The recorded spread is **per case, never pooled**: two shapes have genuinely
  different IPC, and pooling them reports that difference as measurement noise.
  Measured on a compute node, three reps of the seeded stencil starter: IPC
  1.302 at 96³ and 1.353 at 128³, each reproducing to 0.22% — tighter than the
  0.32% wall-clock band for the same task.

  Needs a compute node. The event numbers are ARMv8 PMUv3 encodings; on the
  submit node's architecture they read zero, and `region_counters` exits rather
  than printing a clean empty result.
- `check_campaign_safe.py` — is it safe to edit right now, and is the running
  campaign still intact? A campaign freezes 524 files at submit; changing any of
  them mid-run makes every worker fail its post-run digest check and the
  collector refuse to aggregate, discarding science that already completed. That
  happened twice on 2026-08-03 — once from editing the manuscript, once from
  patching a submit script with nine shards in flight. Answers both questions
  mechanically: whether anything pinned has drifted since launch (exit 1 if so,
  meaning the campaign is already lost and there is no point waiting), and
  whether a given path is pinned. `report_temp/` and `workspace/tools/` are not.
- `check_matched_denominator.py` — **does the second denominator still return 1
  for identical code?** The harness scores against two builds of the same frozen
  source: the anchor (default toolchain) and the matched one (the candidate's
  toolchain). Scoring the reference AS the candidate must give a matched ratio of
  1, because the two programs are the same program; the anchor ratio need not,
  and does not. Measured across three tasks and two compilers: matched
  0.9914--1.0055, anchor **0.1735--1.0906**. On identical code that entire anchor
  spread is toolchain and flags. Needs a compute node — the unit tests can pin
  the structure but not the number. Exits nonzero when the separation breaks.
- `verify_environment_record.py` — **does the environment record survive a real
  scoring, and does drift actually get caught?** The unit tests call
  `measurement_environment()` directly and pin its shape; they cannot show that a
  real `measure_node()` carries the record into the result it writes, nor that
  two scorings taken under different settings produce different digests. Both are
  properties of a run, not of a function. Scores the frozen reference twice on
  one node — `XOS_MMM_L_PAGING_POLICY` unset, then set — and requires three
  things: each result carries a digest, the two digests differ, and
  `check_environment_drift.py` fires on the pair. Verified on hardware
  2026-08-03: digests `02d17e0d…` and `9e8235f6…`, checker exit 1. Needs a
  compute node.
- `compare_harnesses.py` — **do two harnesses agree about which candidate is
  better?** Choosing a harness is half the pool; the other half is asking whether
  a finding survives the choice. Compares ORDERINGS only — two harnesses with
  different denominators and different problems put their numbers on different
  scales by construction. A pair whose difference falls inside a harness's
  measured band ABSTAINS rather than counting either way, because that harness
  has no view about it; and a comparison in which every pair abstained reports
  `n/a`, never 100%, since an agreement rate over zero decided pairs is an
  absence of evidence rather than a perfect result. Candidates missing from one
  harness are reported, never dropped: comparing only what ran everywhere favours
  candidates that are easy to build. Exit 1 on any ordering disagreement. This
  tool reads scores, which the SELECTOR must never do — wiring its output back
  into selection would build a score-hacking loop out of two honest halves.
- `check_environment_drift.py` — **did the measurement environment hold still
  while the study ran?** The harness records the environment with every score and
  digests it, which answers "what was it" but not "was it the same one all the
  way through" — and nothing was reading the record back, which is the same
  captured-but-unattached shape the capture exists to prevent. It matters because
  `XOS_MMM_L_PAGING_POLICY` moves the same frozen source by 5.9x: a site default
  changed between Monday's shards and Friday's fails nothing, scores everything,
  and quietly puts a factor into the contrast that has nothing to do with the
  agents. Per-repetition pairing cancels what varies *within* a scoring, never
  what changed *between* them. Prints every distinct digest, which variables
  differ, and how the runs divide; it does not decide whether a difference can
  reach the measurement, it shows you the difference. Exit 1 on more than one
  digest, exit 2 on no records at all — an old study and a broken capture look
  identical from outside, so neither is ever reported as clean.
- `check_cache_capacity.py` — will the campaign's oracle cache fit? The harness
  caches a generated problem and a reference solution per repetition, keyed by an
  input seed derived from the RUN seed
  (`remeasure_seed = run_seed + 1_000_000`), so the cache grows **linearly in the
  seed count** — 26.7 GB for one seed, ~800 GB for thirty against ~694 GB of
  quota. A one-seed pre-flight cannot show this. The launcher calls it before
  submitting and refuses with exit 4; `ARI_SKIP_CAPACITY_CHECK=1` overrides once
  the storage question is decided. Note the two cache-key encodings —
  `_s{seed*100003+rep}` for gemm/stencil, `_s{seed}_r{rep}` for spmm — the first
  version of this tool matched only the first and therefore under-reported by
  57%, concluding a campaign would fit when it will not.
- `find_incomplete_cells.py` — which cells of a submitted campaign did NOT
  finish, as array indices. A cell is complete only when its manifest records
  `rc == 0`, its `run_dir` exists, its `final_measurement.json` is present and
  valid, **and** `source_integrity.json` says `verified`. That last check is the
  one that matters: a cell whose science completed but whose source digest moved
  mid-run exits `RC=86` and is unusable, yet its manifest still says `rc=0` and
  carries the fingerprint captured at START — so the manifest alone cannot see
  it. Feeds `submit_handoff_ablation_array.sh --resume ROOT`, which re-runs only
  those cells, takes its design from the original `launch_contract.json`, and
  refuses (exit 3) if the source tree has changed since.
- `analyse_reflection_trajectory.py` — did a parent's proposal reach the child's
  code, and did it help? Classifies `next_steps_hints` and the parent→child
  source diff into optimisation categories and reports adoption rate **against
  the base rate in the arms that received no proposals at all**. Without that
  base rate an adoption rate means nothing, because most of these categories are
  things an optimising agent does unprompted. Produces the paper's trajectory
  table.
- `emit_paper_tables.py` — generates the result tables' ROWS from the derived
  analysis instead of having them retyped. Verified by regenerating the
  preliminary descriptive table and matching the manuscript digit for digit.
  Transcription is where this paper has lost numbers: a manual audit found
  fourteen wrong or unsourced values in one sitting, and a later machine check
  found two the eye had passed. Emits rows only — the table environment, caption
  and label stay in the manuscript, because those carry the claims.
- `check_paper_consistency.py` — recomputes the paper's descriptive, contrast,
  resource and absolute-performance numbers from the derived CSV/JSON and exits
  nonzero when the manuscripts disagree. Read-only; a clean run prints `PASS`.
  This is the automated form of the manual audit that found seven wrong or
  unsourced numbers in one sitting. It also checks `v2_measurement_facts.json`
  — the band, the stencil page-cache mechanism — **including values DERIVED from
  those numbers**: the band/target ratios had been recomputed by hand from the
  rounded figures printed in the table, so the manuscript said spmm was 1.01x
  over target when it is 1.005x, and stencil 1.39x when it is 1.40x. Checking the
  values a table prints is not the same as checking what the prose concludes from
  them. A manuscript carrying none of the v2 numbers is reported as ABSENT rather
  than wrong, so a stale translation cannot mask a real mismatch.
- `check_reference_competence.py` — scores the highest-scoring candidate the
  agents actually produced, per task, against today's frozen reference. A
  denominator the agents' own code beats cannot support the claim that the score
  measures optimisation quality. This found the gemm reference losing 1.313x to
  a plain `ikj` at one of three scored shapes.
- `measure_shape_stability.py` — for a candidate problem shape, measures BOTH a
  blocked and an unblocked kernel's own credited time across independent
  scorings. A shape is only usable if the implementations candidates actually
  write can be measured stably on it; that criterion is why the third gemm shape
  is 1500x600x1500 and not 500x500x2000.
- `measure_fma_ceiling.c` — measured FMA ceiling, so "fraction of peak" in the
  paper is observed rather than a spec-sheet product. Measures 2534 GF/s here
  against the GEMM reference's 382. **Build it with clang or `fcc -Nclang`**, not
  gcc 8.5, which has no `arm_sve.h`. Six earlier versions all reported a ceiling
  BELOW the reference they were meant to bound — accumulators spilled to memory,
  auto-vectorisation emitting no SVE FMA at all, `svfloat64_t` arrays (the type is
  sizeless and cannot be an array element). The source records each dead end.
  Two checks decide whether a run is trustworthy: `objdump` must show SVE FMAs
  (clang emits `fmad`, not `fmla` — grepping only for `fmla` reports zero), and
  doubling `ITER` must leave the GF/s unchanged (it moves 0.14% here), or the loop
  was optimised away.
- `parse_fapp.py` — turns a Fujitsu `fapp` report into named fields and one
  rule-based bottleneck verdict. Handing an LLM the raw fixed-width table is
  handing it something to misread; what an optimizer acts on is GFLOPS and its
  peak ratio, memory throughput and its peak ratio, SIMD/SVE rates, IPC, and a
  verdict. The verdict is RULES, not a model, on purpose: an LLM classifier would
  vary between arms and a handoff experiment would then measure the classifier as
  much as the channel. Thresholds live in one place and travel in the output, so
  every arm gets the same ones and they can be argued with. Only event group
  `pa1` yields the named statistics. The first version matched header words per
  line and reported "no statistics" on a report that had them -- fapp wraps a
  header across two lines.
- `region_counters.c` — **hardware counters for the region that is actually
  scored**, on a machine with no `perf`. Reads cycles, instructions, L1D
  access/refill and L2D refill through `perf_event_open(2)` and reports IPC, the
  L1D refill rate, the fraction of L1 misses reaching memory, and bytes/cycle.
  `perf`, PAPI and likwid are all absent here, but the PMU is exposed and
  `perf_event_open` works, so what was missing was the tool, not the counters.
  Root is NOT needed and neither is `perf_event_paranoid=0`: `pid>=0` with
  `cpu=-1` and `exclude_kernel=1` is permitted at 2.

  **v1 counted the whole child process while claiming to count "a region the
  caller marks" — there was no marking mechanism at all.** That is not a naming
  quibble on this harness: the scored kernel call is ONE statement, and around it
  in the same process sit a 134 MB read, a 134 MB serial NaN-poison write and a
  134 MB write-out. Measured on a compute node with the same 0.0097 s region: the
  whole process reads **7.16x** the region's cycles, and because the poison pass
  is pure write-allocate traffic the L2D ratio is dragged toward "memory bound"
  for every candidate. Two candidates with identical kernels but different setup
  would have received different profiler feedback.

  So `--gate` makes the region real, and the TARGET marks it: the parent hands
  the child two pipe fds (`ARI_COUNTER_GATE_FD`, `ARI_COUNTER_ACK_FD`), the
  target writes a byte and BLOCKS until the counters are armed, runs the region,
  and writes a second byte. Blocking is the point — without it the counters start
  microseconds into the region. Measured: wake-up 4.2 us mean / 26.6 us worst, so
  only the closing edge carries lag, under 0.02% of a 161 ms region. Verified on
  hardware: with the gate, adding 7.2x more untimed work around the region moved
  the count by 0.07% (152,542,426 vs 152,428,858 cycles); without it, by 7.16x.
  A target that does not mark exits 4 rather than silently falling back to
  whole-process counting.

  Three more v1 defects, each of which made a wrong number look right: a counter
  was "ok" if its fd opened, so an event the chip does not implement read 0 and
  printed as "no misses" (now `time_running` is carried and a zero over a region
  that ran is reported SUSPECT); `read_format` was 0, so multiplexed events were
  silently under-reported (the scaling factor is now computed and printed);
  and bytes/cycle hardcoded a 256-byte line in a file claiming architecture
  neutrality (now from sysfs or `sysconf`, and **suppressed rather than guessed**
  when neither answers — which is the case on the aarch64 compute nodes here, so
  pass a measured `--line-bytes N` to get that ratio). Running it on the wrong
  architecture no longer returns a clean empty result: raw ARMv8 encodings that
  read 0 cycles exit 5 with "a zero here is a wrong tool, not a fast kernel".
  Build with `cc -O2` (the file defines `_GNU_SOURCE` itself).
- `measure_clock.c` — core clock via `perf_event_open(2)`. `perf` is not installed
  here and no module provides it, and there is no `cpufreq` directory, but the PMU
  is exposed as `armv8_pmuv3_0` with `perf_event_paranoid` 0, so cycles can be
  counted directly: 1.9984 GHz, identical across a 1 s and a 3 s interval. The
  missing piece was the tool, not the counter — "no perf" is not "no clock".
- `measure_design_power.py` — **can this design detect the effect it is looking
  for?** Three review objections -- no profiler, no A64FX-specific optimization
  essentials, no problem-aligned skill or harness -- all reduce to one measurable
  claim: the agent has no repeatable procedure, so each run lands somewhere
  different and a channel effect is buried under that. Pairing removes seed-level
  difficulty but not run-level variance, so this reports sd(paired difference),
  the standard error at the planned n, and the minimum detectable effect against
  the observed one. Measured mid-campaign, all six contrasts came out at
  effect/MDE below 1, i.e.\ a null at n=30 would describe the measurement rather
  than the intervention. sd(diff) is the quantity the missing equipment exists to
  reduce.
- `measure_resolution_band.py` — **KATAGIRI: 結果がぶれない問題設定.** Scores
  identical builds repeatedly; the spread is pure measurement noise, so the p95
  of |score − median| is the band a rep count buys. Re-run it whenever the
  denominator, the problem sizes or the timed region change — all three moved
  during this study and no earlier band survived any of them.
- `aggregate_flops.py` — **KATAGIRI: 性能が出ているか, for the AGENTS.**
  `measure_absolute_performance.py` answers "is this code fast" for one source
  you hand it, which in practice is the frozen reference. This answers it for
  every run a campaign produced, per arm. The absolute times are recoverable but
  nobody was recovering them: the aggregate a run persists is the ratio, and a
  ratio of 0.86 is equally compatible with 300 GF/s and with 3 GF/s. SpMM
  reports time only — its flop count is `2*nnz*k` and nnz is not in the family
  name, so a GF/s there would be a guess.
- `measure_timed_window.py` — **KATAGIRI: 結果がぶれない問題設定.** Says WHICH
  PART of the timed window the noise is in, which the band alone cannot. Builds
  the SCORED binary through the harness's own `_compile_kernel` and reads the
  same internal timer, then varies the sweep count to split
  `t = a + b*nt` into a fixed allocation/first-touch term and a per-sweep term.
  Here `b` reproduces to 0.03% from nt=1 to nt=240 while `a` spreads 34% over
  100 processes — so the stencil's band is the fixed term, and no rep count
  averages it away. Run the real binary, never a re-implementation: a standalone
  replica failed to reproduce the effect across 50 processes and that failure was
  misread as a refutation, because the replica's process held none of the 268 MB
  the scored driver already has resident when the kernel allocates 268 MB more.
- `measure_absolute_performance.py` — **KATAGIRI: 性能が出ているか.** Reports
  achieved GF/s per scored case against BOTH the measured FMA ceiling and the
  architectural peak (with a measured clock), because a speedup ratio cannot
  answer "is 33 GFLOPS too low". Also states why a low fraction is not only the
  search's fault: the contract forbids intrinsics, so the reachable ceiling is
  set by the auto-vectoriser.
- `check_first_touch.py` — **MUKUNOKI / KATAGIRI: NUMA・first touch.** Checks
  three things: is there a parallel touch, does its decomposition MATCH the
  compute loop, and (optionally) what does removing it cost. The middle check is
  the one that matters — the corpus's best stencil candidate touched with
  `collapse(3)` and swept with `collapse(2)`, placing pages away from the thread
  that uses them, which reads as correct on inspection.
- `audit_candidate_code.py` — **MUKUNOKI: コードの分析は必須.** Classifies a
  source into the optimisations it actually contains, and with `--comments`
  flags what the source CLAIMS but does not do. That gap is real: the best
  stencil candidate's comment claims temporal blocking it never implements.
- `reviewer_analysis.py` — regenerates run-level summaries, handoff and leakage
  audits, machine-readable statistics and the figures. It reads
  `<root>/<task>/manifest.jsonl` and follows each row's `run_dir` into
  `workspace/experiments/`, so point it at a **collected campaign root**:

  ```bash
  ARI_REPLACEMENT_ANALYSIS_DIR=<campaign_root_basename> python3 workspace/tools/reviewer_analysis.py
  ```

  The env var exists because the directory name carries machine detail this
  repository must not hold; the built-in default is that name with the detail
  removed and therefore matches nothing on disk. `load_manifests()` asserts
  exactly 270 rows, so it runs against a completed `--full` campaign only —
  not against a `--preflight`. The layout was checked against a collected
  9-shard root before committing to a 5-hour campaign: all rows resolved and
  every key the tool reads was present.
- `warm_oracle_cache.py` — precomputes the numpy oracles before a campaign, so
  the first node does not pay 29 minutes of shared setup inside its own timeout
  and get recorded as an infrastructure failure.

## Derived outputs

Figures and CSV/JSON produced by these programs stay in `report_temp/tools/`,
next to the manuscript that cites them. Programs live here; their outputs live
with the paper.

## Running

From the repository root, with the aarch64 interpreter on compute nodes:

```bash
workspace/.venv_aarch64/bin/python workspace/tools/check_reference_competence.py --out /path/to/out
```

`check_paper_consistency.py` and `reviewer_analysis.py` run on the login node.
The `measure_*` and `check_reference_*` programs compile and time kernels, so
they must run on a compute node through the batch system.
