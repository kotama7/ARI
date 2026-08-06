# SpMM Optimization

## When to use

Use this procedure when optimizing sparse-dense matrix multiplication where
structural validity, numerical equivalence, and reproducible measurement are
mandatory.

## Preconditions

The Research Contract identifies the sparse format, index base, data types,
supported hardware, baseline implementation, and admissible performance metric.

## Procedure

Validate the sparse structure before measuring anything. For CSR that means:
the row pointer is non-decreasing, starts at zero, and ends at the stated
nonzero count; every column index is in range; and indices within a row are
strictly increasing if the code assumes sorted rows. This costs one pass and
routinely catches a generator or converter defect that would otherwise be
reported as a speedup, because a malformed matrix makes the candidate skip work
the baseline performs.

Establish a reference implementation you own, in the same binary as the
candidate, so both see the identical matrix and identical compiler settings.

Then work the transformation ladder, one hypothesis at a time:

1. **Hoist and accumulate.** The straightforward form recomputes the dense-row
   index for every (nonzero, dense-column) pair and stores to the output for
   every element. Hoisting the nonzero value out of the dense-column loop,
   accumulating a small register block across the dense columns, and writing
   the output row back once removes both the repeated index arithmetic and the
   repeated stores. This is usually the largest change and it does not alter
   the accumulation order.
2. **Partitioning.** Only when a measurement shows load imbalance. Row-length
   distribution, not nonzero count, determines imbalance: a matrix with a few
   very long rows behaves nothing like a uniform one at the same density.
3. **Format specialization.** Last, and only with the structural evidence to
   back its assumptions. A format that assumes sorted, duplicate-free rows
   silently rewrites input semantics when it meets a matrix that is neither.

Measure over a family of sparsity patterns, not one matrix. Alternate baseline
and candidate inside one process, warm both paths before timing, and take the
minimum over several trials per replay. Report the per-replay values.

## Decision points

Select an optimization only when it improves the declared workload distribution
and preserves empty-row, duplicate, sorted/unsorted, and zero-nnz behavior.

Prefer a change whose benefit holds across the row-length distributions in the
declared family. A partitioning scheme tuned to a uniform matrix commonly
reverses on a power-law one, and a result from a single matrix cannot tell the
two apart.

## Failure conditions

Stop scientific promotion on structural violation, sanitizer finding, numerical
error outside the dtype/accumulation-length model, nondeterministic
disagreement, or missing performance provenance.

Stop also when the timed region contains anything other than the kernel.
Matrix construction, index conversion, allocation, and first touch inside the
timed call are attributed to the kernel, and for sparse work the construction
cost can exceed the kernel cost outright.

## Expected artifacts

Produce source, compiler invocation, binary identity, matrix family manifest
with per-matrix structural summary, correctness evidence, raw timings,
summarized measurements, and environment identity.

## Scientific cautions

An empty row is the most common silent divergence: the reference writes zeros,
a candidate that iterates nonzeros may leave the previous contents. Include
empty rows, a duplicate column, an unsorted row, and a zero-nonzero matrix in
the family deliberately rather than hoping the generator produced them.

Nonzero count is not the workload. Two matrices with equal density and
different row-length distributions exercise different bottlenecks, so a single
aggregate ratio over a mixed family hides more than it reports.

Do not relax a tolerance after observing failures, conflate structural validity
with numerical correctness, or treat Provider success as correctness.

## Evaluation obligations

Require structural validation, numerical equivalence through differential
testing, memory-safety checks, performance-regression checks, and
reproducibility across the declared matrix family and thread matrix.
