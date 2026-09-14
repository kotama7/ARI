# Stencil Optimization

## When to use

Use this procedure when optimizing an iterative stencil sweep where trajectory
equivalence, boundary behavior, and reproducible measurement are mandatory.

## Preconditions

The Research Contract identifies the stencil shape, boundary treatment, data
layout, iteration count, supported hardware, baseline implementation, and
admissible performance metric.

## Procedure

Construct a reference trajectory, not a reference answer. Compare the field
after every step, because a candidate that drifts and re-converges passes a
final-state check while being wrong throughout. Per-step comparison is the
cheapest defect detector this kernel has.

Establish the baseline in the same binary as the candidate so both see
identical initial conditions and compiler settings.

Then work the transformation ladder, one hypothesis at a time:

1. **Layout and update order.** Contiguity in the innermost dimension and a
   clean flip between the two buffers come first; they are numerically neutral
   and usually the largest single change.
2. **Tiling and temporal blocking.** Only when a measurement says the sweep is
   bandwidth-bound rather than issue-bound. Temporal blocking changes which
   values are live at a step boundary, so it requires the per-step comparison
   above rather than a final-state check.
3. **Threading.** Last, and with the placement discipline below, because on a
   multi-domain machine the placement decides the result more often than the
   decomposition does.

For a threaded decomposition, synchronise once per timestep so that every read
of a neighbour's halo happens after the write that produced it, and prove it
with a race detector rather than by inspection.

Then place the threads deliberately:

- Read the affinity mask the process was actually given. Do not infer it from
  the number of CPUs requested; a batch step can inherit the whole machine in
  its mask even when far fewer CPUs were asked for, and then nothing binds the
  threads at all.
- Derive one CPU per physical core from the topology's sibling lists, and pin
  one worker to each. On a machine with simultaneous multithreading and an
  unrestricted mask, the lowest-numbered allowed CPUs are frequently siblings
  of a single physical core: two threads then share one core's execution
  resources and the parallel candidate loses to its own serial baseline. This
  failure looks exactly like a slow kernel and is not one.
- Record the placement policy with the measurement. A speedup reported without
  it cannot be compared against anything.

Check the paging and first-touch policy before attributing a bandwidth result
to the kernel. Some toolchains default to pre-allocating pages before the
program touches them, which places memory without regard to the thread that
will read it and destroys locality on a bandwidth-bound sweep; a demand-paging
policy restores it. The effect is comfortably larger than most kernel changes,
so a sweep measured under the wrong policy mismeasures the change under test.

## Decision points

Adopt an optimization only if boundary/halo behavior and the full trajectory are
preserved and measured resource behavior supports the hypothesis.

Prefer a change whose benefit survives non-cubic and small domains. A tiling
tuned to one cubic size regularly reverses when a dimension becomes short
enough that the tile no longer divides it.

## Failure conditions

Stop scientific promotion on boundary/halo divergence, trajectory divergence at
any step, race-detector finding, sanitizer finding, nondeterministic
disagreement, or missing performance provenance.

Stop also when the timed region contains anything other than the sweep.
Allocation, first touch, environment queries, and topology reads inside the
timed call are attributed to the kernel; a per-thread topology query inside the
timed region has been observed to make a correct candidate measure several
times slower than its own baseline. Read the environment once, before timing.

## Expected artifacts

Produce source, compiler invocation, binary identity, initial-condition and
boundary manifest, per-step equivalence evidence, race-detector and sanitizer
results, thread-placement and paging policy, raw timings, summarized
measurements, and environment identity.

## Scientific cautions

For a linear stencil, linearity is a metamorphic identity worth testing:
sweeping the sum of two fields must equal the sum of the two swept fields, to
rounding. It catches boundary and halo mistakes that a single differential
comparison against one initial condition misses.

A parallel result is a statement about the kernel *and* the placement. Report
both, and when a threaded candidate underperforms, rule out placement before
concluding anything about the decomposition.

Do not conflate a converged final state with an equivalent trajectory, relax a
tolerance after observing failures, or treat Provider success as correctness.

## Evaluation obligations

Require trajectory equivalence through differential and metamorphic testing,
memory-safety and race detection, performance-regression checks, and
reproducibility across the declared domain shapes, thread counts, and placement
policy.
