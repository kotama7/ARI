{VENUE_HINT}
You are a senior reviewer populating ONE SUBTREE of a hierarchical
paper-replication grading rubric. The skeleton has already defined the
parent node assigned to you below; YOUR job is to recursively decompose
its scope into a deep tree of leaves.

GRADING SUBSTRATE (READ FIRST):
  Phase 1: candidate provides reproduce.sh; grader runs it once in a sandbox;
           reproduce.log and artifact files are produced.
  Phase 2: PaperBench SimpleJudge reads paper + your leaf + submission files
           + reproduce.log, then assigns 0/1 per leaf.

PARENT SCOPE (your subtree must cover EXACTLY this part of the paper):
  {PARENT_REQUIREMENTS}

LEAF BUDGET FOR THIS SUBTREE: aim for ~{TARGET_LEAVES} leaves total.

Each leaf is a TaskNode with these fields:
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

Internal (non-leaf) nodes inside YOUR subtree need only ``id``,
``requirements``, ``weight``, ``sub_tasks``. Omit ``task_category``,
``finegrained_task_category``, and ``rationale_from_paper`` on internal
nodes.

HIERARCHY DESIGN INSIDE YOUR SUBTREE (this is the depth-generation pass):
  Subdivide the parent scope recursively until each leaf is one atomic,
  binary-checkable fact. Aim for 3–5 ADDITIONAL levels below your subtree
  root (so total tree depth, counting the skeleton root and the parent,
  reaches 5–7).

  Generic decomposition pattern (adapt to the paper):
    your-root  ← already given as the parent scope
      ├─ subdivide by experiment / variant / sub-claim
      │    ├─ subdivide by instance (dataset, environment, model, kernel
      │    │  variant, hyperparameter setting, baseline, …)
      │    │    ├─ subdivide by implementation aspect or measurement
      │    │    │    └─ atomic leaf (one verifiable fact)
      │    │    └─ atomic leaf
      │    └─ atomic leaf
      └─ subdivide by …

  Match the paper's actual structure, not the template. Different fields
  decompose differently — pick whichever vocabulary the paper itself uses.

  ANTI-PATTERN (do NOT do this):
    your-root
      ├─ "Code Development"  → flat list
      ├─ "Code Execution"    → flat list
      └─ "Result Analysis"   → flat list
  task_category is leaf metadata, never a structural axis.

LEAF DESIGN PRINCIPLES (adversarial mindset):
  - A fraudulent submission CANNOT pass.
  - A faithful reimplementation MUST pass.
  - Generic boilerplate MUST score below 10%.
  - For every claim the paper makes within YOUR scope, design at least
    one leaf.

CATEGORY GUIDELINES (target distribution across leaves in your subtree):
  - Code Development      ~50%
  - Code Execution        ~45%
  - Result Analysis       ~5%

WORDING RULES (match PaperBench style):
  - Use definite, verifiable phrasing: "The X class outputs Y for input Z",
    "Experiment II for environment E has been run", "In the log, method M's
    score is strictly higher than method N's".
  - Avoid vague qualifiers: "appropriate", "well-organized", "clear",
    "good", "proper".
  - Every leaf MUST cite a paper section and a verbatim quote in
    rationale_from_paper. The quote must appear LITERALLY in the paper
    text.
  - ``rationale_from_paper.quote`` is a plain-text JSON string. STRIP LaTeX
    markup before storing — JSON does not accept ``\(``, ``\$``, ``\texttt``
    as escape sequences and the rubric loader will reject your output.
    Replace ``\\(...\\)`` with parentheses, drop ``\\texttt{X}`` and emit
    just ``X``, replace ``\\$`` with ``$``, use plain ASCII for math
    symbols (write ``m+1`` not ``\\(m+1\\)``).

OUTPUT FORMAT:
You MUST output a single JSON object — no prose, no markdown fences. The
output IS the parent TaskNode with ``sub_tasks`` populated. Keep the
parent's ``requirements`` text identical to the PARENT SCOPE above:

{
  "id": "<uuid v4>",
  "requirements": "{PARENT_REQUIREMENTS}",
  "weight": <positive integer>,
  "sub_tasks": [
    <recursive children — internal nodes and leaves as described above>
  ]
}

PAPER:
{PAPER_TEXT}
