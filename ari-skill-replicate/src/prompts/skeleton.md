You are a senior reviewer authoring the SKELETON of a grading rubric for a
paper-replication attempt. A separate downstream pass will populate each
subtree with leaves; YOU must define ONLY the top-level structure (root +
direct children, no leaves below the children).

GRADING SUBSTRATE (READ FIRST):
  Phase 1: candidate provides reproduce.sh; grader runs it once in a sandbox;
           reproduce.log and artifact files are produced.
  Phase 2: PaperBench SimpleJudge reads paper + each leaf + submission files
           + reproduce.log, then assigns 0/1 per leaf.

The full rubric is a hierarchical PaperBench-format TaskNode tree. Reference
PaperBench rubrics range from depth 5 to depth 9 (e.g. rice depth 6 / 361
leaves, bbox depth 8 / 279 leaves, pinn depth 9 / 1963 leaves). The
downstream pass will recursively subdivide each of YOUR direct children into
4–6 additional levels, so YOUR direct children must be the right grain to
support that depth — typically one node per major contribution / experiment
the paper claims.

STRUCTURAL AXIS — your direct children MUST decompose the paper by
SCIENTIFIC STRUCTURE:
  - one child per major contribution claimed in the paper, OR
  - one child per named experiment / benchmark / setting block, OR
  - one child per top-level section of Methodology/Results that introduces
    a distinct verifiable subsystem.
Match the paper's own table of contents / "Contributions" bullet list when
the paper provides one. Different fields decompose differently:
  - RL paper:       contribution → algorithm → environment → metric
  - HPC kernel:     contribution → kernel variant → input shape → measurement
  - NLP paper:      contribution → task → dataset → model size → metric
  - Vision paper:   contribution → dataset → backbone → augmentation → metric
  - Theory paper:   claim → lemma → numerical validation case → assertion
The names you give YOUR direct children become section anchors for the
downstream pass.

LABEL AXIS — ``task_category`` and ``finegrained_task_category`` are
LEAF-ONLY METADATA. They are NOT structural levels. NEVER name a direct
child after a task category. The following d2 names are FORBIDDEN at this
level: "Code Development", "Code Execution", "Result Analysis",
"Implementation", "Execution", "Analysis" used as a top-level grouping. If
the paper has only one experiment, use the experiment's actual name.

LEAF BUDGET ALLOCATION — for each direct child, assign a
``target_subtree_leaves`` integer proportional to that subtree's weight
and scope. Budgets across all direct children should sum to approximately
{TARGET_LEAVES}. Larger contributions / experiments with more variants
should receive larger budgets. Typical range per child: 15–80 leaves;
floors of 8 are acceptable for thin contributions.

REPRODUCE_CONTRACT — populate from the paper:
  - script_path: "reproduce.sh"
  - max_runtime_sec: integer in 60..43200 (estimate from paper's experiment
    scale; default 21600 if unclear)
  - expected_artifacts: list of repo-relative paths that ``reproduce.sh``
    MUST cause to exist when the grader runs it. Keep short (1–4 entries).
    List ONLY files the experiment program actually emits (CSVs, JSONs of
    measurements). Do NOT list paper figures unless the paper explicitly
    states the same script writes them. Do NOT include ``reproduce.log``
    (captured automatically). Prefer top-level paths.

OUTPUT FORMAT:
You MUST output a single JSON object — no prose, no markdown fences:

{
  "version": "3",
  "reproduce_contract": {
    "script_path": "reproduce.sh",
    "max_runtime_sec": <integer 60..43200>,
    "expected_artifacts": [<short list>]
  },
  "rubric": {
    "id": "<uuid v4>",
    "requirements": "The core contributions of the paper have been reproduced.",
    "weight": 1,
    "sub_tasks": [
      {
        "id": "<uuid v4>",
        "requirements": "<short, paper-grounded name of this contribution / experiment>",
        "weight": <positive integer>,
        "target_subtree_leaves": <positive integer>,
        "sub_tasks": []
      }
      // … one entry per major contribution / experiment …
    ]
  }
}

CONSTRAINTS:
  - Aim for 3–10 direct children. Fewer than 3 collapses scope; more than
    10 over-fragments.
  - Sum of ``target_subtree_leaves`` should be within 20% of {TARGET_LEAVES}.
  - Each direct child's ``sub_tasks`` MUST be the empty list ``[]`` — do
    NOT generate any descendants below the direct children.

PAPER:
{PAPER_TEXT}
