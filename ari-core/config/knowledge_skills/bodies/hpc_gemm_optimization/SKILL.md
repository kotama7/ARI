# GEMM Optimization

## When to use

Use this procedure when optimizing dense matrix multiplication while numerical
equivalence and reproducible measurement remain mandatory.

## Preconditions

The Research Contract identifies the target interface, data types, supported
hardware, baseline implementation, and admissible performance metric.

## Procedure

State the GEMM equation before touching code, including transpose flags,
leading-dimension semantics, and the alpha/beta accumulation. Most "wrong
answer" findings in this kernel come from disagreeing about that statement
rather than from the arithmetic.

Establish a baseline you own. A baseline you did not write is a second
unknown: when the measured ratio surprises you, you cannot tell which side
moved. Keep it in the same binary as the candidate so both see identical
inputs and identical compiler settings.

Then work the transformation ladder in this order, changing one hypothesis at
a time:

1. **Loop order.** The textbook `i, j, k` form walks one operand down a column
   in the innermost loop, so every element load is strided by the leading
   dimension. Reordering so the innermost loop walks contiguous memory in both
   the read and the accumulation is usually the single largest change
   available, and it costs nothing in numerical terms if the accumulation
   order is preserved.
2. **Blocking.** Tile the iteration space so that one block triple's working
   set fits the cache level you are targeting, and hoist the scalar operand out
   of the innermost loop so it lives in a register instead of being reloaded.
   Blocking without hoisting usually disappoints.
3. **Vectorization and threading.** Only after the first two, and only when a
   measurement says the remaining bottleneck is issue width or a single core's
   bandwidth. Both change the accumulation order, so both require the
   equivalence evidence below rather than a spot check.

Measure by alternating baseline and candidate inside one process, warming both
paths before any timing, and taking the minimum over several trials as the
statistic. Alternation cancels slow drift in machine state; the minimum
rejects interference rather than averaging it in. Repeat the whole alternating
block several times and report the per-replay values, not one number.

## Decision points

Choose blocking, vectorization, threading, or accelerator specialization only
after the measured bottleneck and target architecture justify it. Prefer the
least side-effecting bound Provider that satisfies the required capability.

Prefer a change whose benefit survives a shape sweep. A transformation tuned
to one square shape frequently reverses on a tall-skinny or short-fat one, and
a result reported on a single shape cannot distinguish the two cases.

## Failure conditions

Stop scientific promotion on ABI mismatch, sanitizer finding, numerical error
outside the dtype/accumulation-length model, nondeterministic disagreement, or
missing performance provenance.

Stop also when the timed region contains anything other than the kernel. Setup,
allocation, first touch, environment queries, and file reads inside the timed
call are attributed to the kernel by the measurement, and a correct candidate
can be made to look several times slower than its own baseline this way. Move
every such step outside the timing and re-measure before believing a
regression.

## Expected artifacts

Produce source, compiler invocation, binary identity, test-case manifest,
correctness evidence, raw timings, summarized measurements, and environment
identity.

## Scientific cautions

A single differential check against the baseline is weaker than it looks: it
compares one input against one output. Metamorphic identities test the
transformation itself. For GEMM, two are cheap and effective — scaling an
operand must scale the result, and the product distributes over a sum of the
other operand. A correct blocked implementation holds both to rounding; a
reassociation bug that survives a spot check usually does not.

Do not tune to one square shape, conflate correctness with performance, relax a
tolerance after observing failures, or treat Provider success as correctness.

Report the compiler, the flags, and the statistic alongside any ratio. A
speedup without them is not a measurement, and `-ffast-math` in particular
changes what "equivalent" means before any of your own changes do.

## Evaluation obligations

Require numerical equivalence through differential and metamorphic testing,
performance-regression checks, memory-safety checks, and reproducibility across
the declared shape/thread matrix.
