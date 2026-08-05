# Harness pool: choosing how to measure, instead of inheriting one way

## The problem with one harness per task

A task name and a way of measuring it used to be the same thing. `stencil` named
both the scientific question ("optimize a 3-D 7-point Jacobi stencil on this
machine") and one specific answer to "how shall we score it". There was no
selection because there was nothing to select between.

That is not a neutral default. Every property that makes a measurement
trustworthy is a **choice**, and each choice was made once, invisibly, and turned
out to be wrong at least once:

| choice | what was there | what it had to become | what the wrong choice cost |
|---|---|---|---|
| denominator | naive implementation | competent frozen reference | the score measured distance from doing nothing |
| problem size | working set inside LLC | working set outside it | the optimization gradient the study needed did not exist |
| timed window | wall clock, team creation inside | internal timer, team creation outside | 37–54% of the reference's time was not the kernel |
| toolchain | pinned to the default | part of the search space | the same compiler moved 6.8× on one flag |
| environment | ambient | recorded and checked | one variable moved the same source 5.9× |

Each was found by discovering the harness was wrong, not by comparing it against
an alternative. A pool makes the alternatives exist, so the comparison is
available before the mistake instead of after it.

## What a pool changes

**A task gets several harnesses, and they may disagree.** Disagreement is a
result, not a defect to hide. If two defensible harnesses rank two candidates
differently, then the claim "candidate A is better" was a claim about the harness
as much as the code, and the reader is entitled to know that. Under one harness
per task this is structurally invisible.

**Selection becomes an explicit, recorded act.** The same argument as the
environment record: a study that does not say which harness it chose, from what
alternatives, and on what grounds, is not reproducible on the axis that matters
most. "We used the best harness" is unfalsifiable unless the pool and the
criterion are written down.

**Robustness becomes measurable.** The interesting question is not "what score
did the candidate get" but "does the finding survive changing the harness". That
question cannot even be posed today.

## Declaring what a harness is for

`harness.toml` declares how to *run* a harness (entry, kwargs, file digests,
axis, scale). It said nothing about what the harness is *for*, which is exactly
what selection needs. The `[declares]` block is machine-readable and, importantly,
**states limits as well as capabilities**. It is covered by the manifest's
integrity digest, because it is what the pool selects on: editing a declared band
changes which harness measures a study without changing a single scored byte.

```toml
[declares]
question    = "time to solution against a competent reference, same machine"
denominator = "competent_frozen"      # naive | competent_frozen | anchor_matched | best_known
resolves    = 0.00149                  # measured band: the smallest difference it can separate
cost_s      = 97.7                     # seconds per scoring at the declared repetitions
requires    = ["c_compiler", "openmp"] # capabilities, probed by executing, not by name
sees        = ["memory_bandwidth", "numa_placement", "large_page_policy"]
blind_to    = ["problem_generation"]   # the problem arrives from outside the timed window
```

Two fields carry most of the weight.

`resolves` is the **band** — measured, not asserted. A harness that cannot
separate two candidates closer than 0.25% must not be selected for a study whose
expected effect is 0.1%; the selector now refuses it, and refuses a band carrying
no measurement date, because a number somebody typed and a number somebody took
are otherwise indistinguishable.

`blind_to` records what the harness structurally cannot see. This is not
speculation: it was measured that the large-page policy moves the stencil harness
5.9× and leaves GEMM and SpMM inside the noise, because only the stencil
candidate allocates its own memory and first-touches it *inside* the timed
window. That is a permanent property of those harnesses and it belongs in the
manifest, not in someone's notes.

## Selection: by hand first, automatically second

Manual selection comes first, and not only for caution. An automatic selector
cannot be validated without a manual baseline to disagree with — there is nothing
to check it against.

    ari harness select --resolve 0.002 --budget-s 120 --must-see large_page_policy

prints every harness ranked, each with the declared properties that qualified or
disqualified it, and the operator chooses. It exits 2 when nothing qualifies,
because that is a result: the requirement is wrong, or the pool is missing a
harness that does not exist yet. Running the closest one anyway produces a
number, not an answer. The automatic mode would be the same ranking with a policy
applied and the outcome recorded identically; it does not exist yet.

**The selector must never rank on results.** A selector that picks the harness
giving the best score is a machine for score hacking, and it would be an easy
accident: "choose the harness under which the candidate does best" is a natural
sentence and a fatal criterion. Selection is on properties declared *before* the
run — question fit, resolution, cost, capability, blind spots — never on
outcome. This is enforced structurally rather than by convention: the selector
module imports nothing that can load a harness, read a result file or run
anything, and a test asserts that from its AST. Both guards were verified to fail
when violated.

## What this does not change

The integrity pins, the `refusing to score` behaviour on a modified file, and the
rule that a node's edits cannot reach the scorer all stay exactly as they are.
Registration remains by presence of a manifest. A pool with several harnesses per
task needs those properties more, not less.

## Making a variant

A variant is a **separate directory** — that keeps every harness independently
content-addressed — but it does **not** copy the code. It links to it:

    harnesses/gemm_incache/
        gemm_harness.py -> ../gemm/gemm_harness.py     # symlink
        gemm_kernels    -> ../gemm/gemm_kernels        # symlink
        experiment.md   -> ../gemm/experiment.md       # symlink
        harness.toml                                   # the only real file

Digests read *through* a symlink, which is what makes this correct rather than
merely convenient: both manifests pin the same bytes, so editing the shared
source breaks **both** variants' pins at once. Copying would give two pins over
two files that drift apart silently, and the second copy would go on scoring with
scaffolding the first had already fixed.

Everything that differs lives in the manifest:

    [harness]
    task = "gemm"                  # the question it answers; the pool it joins

    [measure_kwargs]
    shapes = [[512, 512, 512]]     # the preliminary problem: 6.0 MiB, fits in L2

Putting the problem definition in `[measure_kwargs]` rather than in an
environment variable is the point. `ARI_STENCIL_SHAPES` can replace the scored
problem outright without moving a pinned byte, the manifest hash, or
`measure_kwargs` — the harness goes on advertising a band it measured on a
different problem. A declared kwarg is inside the digest. Where a knob must stay
in the environment, name it in `[declares.band_conditions]` with the value the
band was measured under, and the selector refuses the band when the run does not
match. That detects the problem; a declared kwarg removes it.

Registering a second harness for a task is deliberately **breaking**:
`load("gemm")` then refuses, and every caller must name a harness (or set
`ARI_HARNESS`). That is the design working — the alternative is a score that is a
property of a directory name, reported as a property of the task — but it means
adding a variant to a live study is a decision, not a convenience.

## Still open

- **Who measures `resolves`.** The band must be measured
  (`tools/measure_resolution_band.py`), which costs node time per variant, and a
  variant must not inherit the band of the configuration it was derived from —
  that number belongs to the other configuration. The manifest carries the
  measurement's date and repetition count, and the selector refuses a band with
  no date, so an unmeasured variant is simply not selectable on resolution. Two
  registered harnesses (`erfc`, `meshpart`) are in exactly that state today.
- **Cross-harness agreement.** Reporting it needs a definition of "the same
  candidate under two harnesses", which is straightforward for a frozen reference
  and less so for agent-produced code that may not compile under both. Until this
  exists the pool lets you *choose* a harness but not yet ask whether a finding
  survives the choice — which is the question the pool was built for.
- **Automatic selection.** The ranking is available; nothing applies a policy to
  it and runs the winner. Whatever does must record the choice and the
  alternatives exactly as the manual path already does.
