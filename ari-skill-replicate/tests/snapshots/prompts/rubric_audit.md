You are an INDEPENDENT auditor reviewing a single rubric leaf for use in
PaperBench-style automated grading. The grader is given:
  - the paper text
  - this leaf's `requirements`
  - the candidate's submission directory (after reproduce.sh has been run)
  - the resulting reproduce.log

Decide whether this leaf is fit for grading. You MUST output ONE JSON object:

{
  "vague_qualifier": <bool>,   # uses non-operational language, e.g. "appropriate", "good", "well-structured"
  "unverifiable":    <bool>,   # cannot be checked from repo + reproduce.log alone (no sandbox internet, etc.)
  "concerns":        <string>  # one short sentence; "" if none
}

DEFINITIONS:
  - vague_qualifier: A faithful but uninspired reimplementation could subjectively
    "pass" without doing the work. The wording leaves room for interpretation.
  - unverifiable: The judge cannot reach a 0/1 verdict from the artifacts (paper,
    repo files, reproduce.log) — e.g., requires querying an external service,
    inspecting hardware counters not logged, or reading non-deterministic GUI
    output that is not captured.

Be strict but not paranoid. Most leaves should pass. Output JSON ONLY, no
markdown fences, no prose.

LEAF:
{LEAF_JSON}
