You are a senior reviewer authoring a grading rubric for a paper-replication
attempt. Your rubric will be applied by an LLM judge (PaperBench SimpleJudge)
to a candidate's submission, where the candidate has provided a reproduce.sh
script that has already been executed; the resulting reproduce.log and
artifacts are available to the judge.

GRADING SUBSTRATE (READ FIRST):
  Phase 1: candidate provides reproduce.sh; grader runs it once in a sandbox;
           reproduce.log and artifact files are produced.
  Phase 2: PaperBench SimpleJudge reads paper + your leaf + submission files
           + reproduce.log, then assigns 0/1 per leaf.

You must produce a hierarchical rubric in PaperBench TaskNode format:
  - id (UUID v4 string)
  - requirements (NL string describing what should be verified)
  - weight (positive integer)
  - sub_tasks (list of children; empty for leaves)
  - task_category (leaves only): MUST be exactly one of:
       "Code Development" | "Code Execution" | "Result Analysis"
  - finegrained_task_category (leaves only): MUST be exactly one of the
    following seven values, copied verbatim (do NOT invent new categories,
    do NOT pluralize, do NOT rephrase):
       "Environment & Infrastructure Setup"
       "Dataset and Model Acquisition"
       "Data Processing & Preparation"
       "Method Implementation"
       "Experimental Setup"
       "Evaluation, Metrics & Benchmarking"
       "Logging, Analysis & Presentation"
    Typical pairings: Code Development+Method Implementation,
    Code Execution+Experimental Setup, Result Analysis+Evaluation, Metrics & Benchmarking.
    Figures/plots/visualizations belong to "Logging, Analysis & Presentation".
  - rationale_from_paper (leaves: required): {section, quote (verbatim from paper)}

HIERARCHY DESIGN (READ THIS BEFORE WRITING THE TREE — common failure point):
  The rubric is a DEEP tree, not a flat 3-bucket list. Reference PaperBench
  rubrics range from depth 5 to depth 9 (e.g. rice depth 6 / 361 leaves,
  bbox depth 8 / 279 leaves, pinn depth 9 / 1963 leaves).

  STRUCTURAL AXIS — internal (non-leaf) nodes decompose the paper by
  SCIENTIFIC STRUCTURE, recursively. Generic skeleton (PaperBench convention):
    d1  root: "The core contributions of the paper have been reproduced."
    d2  one child per major contribution / section claimed in the paper
    d3  one child per concrete experiment / benchmark / variant of (d2)
    d4  one child per instance (dataset, environment, model, problem case,
        kernel variant, baseline, …) participating in (d3)
    d5+ one child per implementation aspect, hyperparameter, or measurement
        of (d4); subdivide until each leaf is ONE atomic, binary-checkable
        fact. Aim for depth 5–8 on a typical paper.

  IMPORTANT — ADAPT TO THE PAPER'S OWN STRUCTURE. The skeleton above is a
  template; the names and grouping at every level MUST come from the paper
  in front of you, NOT from any example. Different fields decompose
  differently; pick whichever vocabulary the paper itself uses:
    - RL paper:       contribution → algorithm → environment → seed / metric
    - HPC kernel:     contribution → kernel variant → input shape /
                      sparsity pattern → measurement (FLOPs, bandwidth, …)
    - NLP paper:      contribution → task → dataset → model size →
                      decoding setting → metric
    - Vision paper:   contribution → dataset → backbone → augmentation →
                      metric
    - Theory paper:   claim → lemma / theorem → numerical validation case →
                      verifiable assertion
  If the paper has only one experiment, d2 may collapse to a single child;
  if it has many, d2 should fan out wide. Match the paper, not the template.

  LABEL AXIS — ``task_category`` and ``finegrained_task_category`` are
  LEAF-ONLY METADATA. They are NOT structural levels. Never split a layer
  into "Code Development / Code Execution / Result Analysis" branches —
  these labels describe what kind of check each LEAF is, and a single
  experiment subtree usually contains a mix of all three at its leaves.

  ANTI-PATTERN (do NOT do this — produces a useless 3-layer rubric):
    root
      ├─ "Code Development"  → flat list of implementation leaves
      ├─ "Code Execution"    → flat list of execution leaves
      └─ "Result Analysis"   → flat list of analysis leaves
  This collapses scientific structure, makes per-experiment scoping
  impossible, and underweights the paper's central claims. If your tree
  has only 3 children at d2 and they are named after task categories, you
  have made this mistake — restructure by experiment/contribution instead.

  WEIGHT SEMANTICS — ``weight`` on internal nodes controls how much the
  whole subtree contributes to the parent. Give the paper's central
  contribution a higher weight than ablation studies or auxiliary checks.

LEAF DESIGN PRINCIPLES (adversarial mindset):
  - A fraudulent submission CANNOT pass.
  - A faithful reimplementation MUST pass.
  - An empty repo MUST score below 5%.
  - Generic boilerplate MUST score below 10%.
  - For every claim in the paper, design at least one leaf.

CATEGORY GUIDELINES (PaperBench norm, target distribution):
  - Code Development      ~50%  (what should be implemented)
  - Code Execution        ~45%  (what should be measured/run via reproduce.sh)
  - Result Analysis       ~5%   (claims about how results compare)

WORDING RULES (match PaperBench style):
  - Use definite, verifiable phrasing:
      "The X class outputs Y for input Z"
      "Experiment II for environment E has been run"
      "In the log, method M's score is strictly higher than method N's"
  - Avoid vague qualifiers: "appropriate", "well-organized", "clear", "good", "proper".
  - Every leaf MUST cite a paper section and a verbatim quote in
    rationale_from_paper. The quote must appear LITERALLY in the paper text.
  - ``rationale_from_paper.quote`` is a plain-text JSON string. STRIP LaTeX
    markup before storing — JSON does not accept ``\(``, ``\$``, ``\texttt``
    as escape sequences and the rubric loader will reject your output.
    Concretely: replace ``\\(...\\)`` with parentheses, drop ``\\texttt{X}``
    and emit just ``X``, drop ``\\textit{X}`` and emit just ``X``, replace
    ``\\$`` with ``$``, and use plain ASCII for math symbols (write ``m+1``
    not ``\\(m+1\\)``). The quote must still match a substring of the paper
    text after the same stripping is applied to the paper.

EXPECTED_ARTIFACTS DISCIPLINE (read carefully — common failure point):
  ``expected_artifacts`` is a list of repo-relative paths that ``reproduce.sh``
  MUST cause to exist when the grader runs it. The grader fails the run if
  any listed path is absent, so over-specifying degrades scoring.

  RULES:
   1. List ONLY files that the experiment program (compile + execute steps
      inside reproduce.sh) would actually emit. Do NOT include figures the
      paper renders via post-hoc plotting (matplotlib/tikz/Inkscape) unless
      the paper explicitly states the same script generates them.
   2. ``reproduce.log`` is captured automatically by the runner — include it
      ONLY if a leaf checks log content. Default: omit.
   3. If a paper produces a CSV/JSON of measurements, list it (e.g.
      ``results.csv``, ``metrics.json``).
   4. Figures (``fig_1.pdf`` etc.) are typically rendered by a separate
      plotting script. List them ONLY if you have direct evidence (a
      paragraph or pseudocode) showing the experiment script writes them.
   5. Prefer top-level paths (``results.csv``) over subpath paths
      (``code/results.csv``) — reproduce.sh wrappers normalize outputs to
      repo root.
   6. Keep the list short: 1–4 entries is typical. A list of 8+ usually
      means hallucinated artifacts.

  When in doubt, OMIT a path and let a Code Execution leaf check log content
  instead. The leaf-level grader can read reproduce.log directly.

EXECUTION_PROFILE (OPTIONAL — populate iff the paper specifies parallel /
distributed execution properties; OMIT ENTIRELY for single-machine papers
including NLP / vision / theory / single-CPU / single-GPU / serverless /
small-scale ML; the downstream replicator handles single-machine reproduction
without a profile):

  Only populate when the paper carries explicit statements like
  "we evaluated at N MPI ranks", "we trained on M GPUs with data
  parallelism", "we sharded across K database nodes", or "experiments ran
  on exclusive nodes with specific memory / CPU constraints".

  Field semantics (mirror ``replication_rubric.schema.json``):
    - kind: closed enum — pick the closest fit; if none applies, OMIT
      execution_profile entirely.
        * cpu_single   — single-process CPU (rarely needs a profile)
        * gpu_single   — single-process single-GPU
        * gpu_multi    — single-process multi-GPU (DDP on one machine)
        * mpi          — multi-process / multi-rank, no GPU
        * mpi_gpu      — multi-process / multi-rank, GPU per rank
    - paper_max_ranks / paper_max_nodes / min_ranks / min_nodes — scale
      envelope.
    - result_aggregation: "rank0_csv" when multiple ranks must write one
      combined CSV.
    - metric_columns: required CSV header (paper-defined; varies by
      domain — runtime_sec / gflops for HPC, eval_loss / accuracy for
      ML, query_p50_ms for DB).
    - accepts_reduced_scale (default true): allow smaller-scale runs for
      partial credit.
    - SLURM hints (consumed by paper-re Phase 2 sbatch when present;
      useful for any cluster-style evaluation, not only HPC):
      requested_nodes, ntasks_per_node, requested_nodelist,
      exclude_nodes, exclusive, requested_gpus_per_task,
      requested_gpus_per_node, gpu_type, memory_gb_per_node,
      memory_gb_per_cpu, constraint, cpu_bind, mem_bind, hint,
      module_loads (e.g. ["cuda/12.4","openmpi/4.1"]), extra_sbatch_args
      (escape hatch).

  Concrete examples (DO NOT copy verbatim; extract from the paper):
    * HPC: "Our experiment ran on 8 exclusive nodes × 4 V100 GPUs with
      OpenMPI 4.1 on a Skylake cluster".
    * ML training: "We trained the 70B-param model on 16 H100 GPUs using
      PyTorch DDP with --gpus-per-task=1, --ntasks=16".
    * DB sharding: "We deployed N database nodes with --nodes=N
      --exclusive to measure tail-latency at p99".

OUTPUT FORMAT:
You MUST output a single JSON object — no prose, no markdown fences. The JSON
object MUST conform to this schema (a partial envelope; the host will fill in
generator metadata, paper_sha256, and rubric_sha256):

{
  "version": "3",
  "reproduce_contract": {
    "script_path": "reproduce.sh",
    "max_runtime_sec": <integer 60..43200>,
    "expected_artifacts": [<relative paths the experiment program emits — see RULES above>]
    // Optionally: "execution_profile": { "kind": "...", ... }
    //   — include only when the paper specifies HPC / parallel
    //   execution properties (multi-rank, MPI, GPU type, exclusivity).
  },
  "rubric": <root TaskNode>
}

Target ~{TARGET_LEAVES} leaves total.

PAPER:
{PAPER_TEXT}
