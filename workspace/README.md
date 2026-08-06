# workspace — the tasks, the studies, and their output

ARI ships no task and no experiment. Everything that is specific to *this*
machine and *this* study lives here, so the ARI repo stays task-agnostic. This
file exists because it was missing: `regen_manifest.py` below was written,
forgotten, and then reimplemented by hand, because nothing listed it. A
directory whose contents are not written down is a directory whose contents get
rebuilt.

## Programs at this level

- `run_handoff_ablation.py` — the study driver. Builds the design, freezes a
  source fingerprint over the files a run must not have edited under it, runs the
  BFTS arms, and writes the manifest. It also owns the study's environment
  record, which it now takes from the harness rather than keeping a second list
  of variable names — the two records used to disagree, and neither contained
  the other.
- `analyze_handoff_ablation.py` — the collector and primary analysis. Refuses
  results whose source fingerprint or array job id does not match what was
  launched, so a shard that ran against edited code cannot enter the numbers.
- `regen_manifest.py` — **re-pin a harness after editing it.** Refreshes every
  `[files]` sha256 in a `harness.toml` and recomputes the `[integrity]`
  self-digest. Run it as `python workspace/regen_manifest.py <task>...`. You need
  this whenever you touch scored scaffolding: the registry verifies each pin
  before binding a harness and raises `HarnessIntegrityError` ("refusing to
  score") rather than scoring something that no longer matches. It also refuses
  to regenerate while a scored file is missing from `[files]` entirely, since an
  unpinned denominator would make every score unverifiable.
- `patch_credited.py` — one-off repair of credited-time fields in already-written
  results.

## Job submission

- `submit_handoff_ablation_array.sh` — the campaign entry point. Modes:
  `--smoke`, `--preflight` (one seed, reduced repetitions), `--full`, and
  `--resume ROOT`, which reads the design back from the frozen
  `launch_contract.json` and refuses (exit 3) if the source fingerprint drifted
  since launch. Requires `ARI_PARTITION`; concurrency is capped by an API
  ceiling, not by how many nodes happen to be idle.
- `submit_handoff_ablation_sbatch.sh` — the per-shard body. Warms the page cache
  before scoring (a cold cache turned 214 ms into 2086 ms) and derives the scored
  shapes from the harness rather than repeating them as a literal.

## Subdirectories

- `harnesses/` — the registered tasks, one directory each, plus their tests. See
  `harnesses/README.md`.
- `tools/` — 24 standalone programs for measuring, auditing and checking. See
  `tools/README.md`.
- `checkpoints/` — study output, one `<timestamp>_<slug>/` per launch. This is
  where results go; not `$HOME`, not `/tmp`.
- `experiments/`, `staging/` — scratch space for runs that are not campaign
  output.

## Two things that bite

**Editing a pinned file mid-campaign discards the campaign.** The study freezes a
fingerprint over its source at launch; a worker that finds a mismatch exits 86
and the collector refuses the run. `report_temp/` and `workspace/tools/` are
outside the pin, so the manuscript and the tools can be edited while a campaign
is in flight. Nothing else can. `tools/check_campaign_safe.py` answers both
questions mechanically.

**What the freeze does and does not catch.** It catches MODIFICATION and
DELETION of a recorded file, by digest. It catches ADDITION separately, by
re-enumerating the source set on the node and comparing it with the contract —
a new file under a pinned prefix changes what the study is made of and changes
no recorded digest, so the digest alone was blind to it. When that
re-enumeration cannot run, the worker says so and continues rather than
reporting zero additions, because an unanswerable question must not read as a
clean answer. It does NOT catch an edit that is reverted byte-exactly before
the worker finishes: the checks are taken at two instants, hours apart, and
nothing watches the interval. Untracked files under a pinned prefix are outside
the set, because the set is built from `git ls-files`.

**The compute nodes are a different architecture from the login node.** An
interpreter that works in one place fails with `Exec format error` in the other.
Pick the interpreter for the node you are actually on.
