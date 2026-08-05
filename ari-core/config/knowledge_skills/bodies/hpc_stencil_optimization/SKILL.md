# Stencil Optimization

## When to use

Use for iterative structured-grid stencil optimization with fixed boundary and
halo semantics.

## Preconditions

Dimensionality, coefficients, boundary conditions, halo ownership, iteration
count, in-place/out-of-place behavior, dtype, and target hardware are explicit.

## Procedure

Inspect data layout and update order, construct a reference trajectory, then use
semantic code-edit, compile, run, and benchmark capabilities. Evaluate tiling,
temporal blocking, vectorization, threading, or accelerator mapping over
non-cubic and small-domain cases.

## Decision points

Adopt an optimization only if boundary/halo behavior and the full trajectory are
preserved and measured resource behavior supports the hypothesis.

## Failure conditions

Stop promotion on boundary drift, race-dependent results, trajectory mismatch,
memory-safety finding, or measurement lacking iteration/environment identity.

## Expected artifacts

Produce source, binary, coefficient and grid manifests, reference trajectories,
sanitizer/race evidence, raw timings, and environment identity.

## Scientific cautions

One iteration or one cubic grid is insufficient. Do not hide boundary cells from
comparison or tune tolerance after inspecting the candidate.

## Evaluation obligations

Require differential trajectory checks, metamorphic relations, multiple boundary
conditions/iteration counts, memory/race safety, performance regression, and
reproducibility.
