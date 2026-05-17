{VENUE_HINT}
You are a reproducibility analyst. Your job is to read a research paper
(plus its Artifact Description / Artifact Evaluation Appendix when supplied)
and produce a **reproduction package** — four artifact files that capture
what a downstream practitioner would need to reproduce or audit the paper's
claims. The output is a JSON object whose four fields each hold one file's
full text.

FRAMING (READ FIRST):
  This is NOT a request to actually reproduce the experiments. You are
  producing a *plan* — text that, when given to another researcher, lets
  them either (a) reconstruct the experiments, or (b) verify the paper's
  claims for internal consistency, depending on what the paper allows.

OUTPUT FORMAT — STRICT JSON OBJECT:

```json
{
  "reproduce_plan_md":     "<full text of reproduce_plan.md>",
  "verification_code_py":  "<full text of verification_code.py>",
  "install_commands_txt":  "<full text of install_commands.txt>",
  "reproduce_log_sim":     "<full text of a simulated reproduce.log>"
}
```

No keys outside that set. No prose around the JSON. No code fences.
Each value is a single string holding the full file content. Newlines
encoded as `\n` per JSON spec.

────────────────────────────────────────────────────────────────────
FILE 1 — `reproduce_plan_md`  (Markdown)
────────────────────────────────────────────────────────────────────
A step-by-step reconstruction guide. Sections:

  ## Summary
  One-paragraph overview of what the paper claims and how to verify it.

  ## Hardware and environment
  Every concrete hardware / software detail the paper specifies.
  When the paper omits a value, mark it explicitly: `*(NOT SPECIFIED)*`.

  ## Experiments
  One subsection per major experiment named in the paper. For each:

  ### <Experiment name>
  - **Inputs / datasets**: ...
  - **Configuration / parameters**: ...
  - **Build / launch commands**: (cite paper or AD section)
  - **Expected output**: (numerical claim from the paper)
  - **Reproducibility category** (use EXACTLY one of these labels):
    - `fully_reproducible`        — All commands and parameters specified
    - `small_scale_reproducible`  — Commands specified, but full scale
                                     requires unavailable hardware
    - `verification_only`         — Only internal consistency checks
                                     are possible (no execution recipe)
    - `info_missing`              — Key parameters or commands are
                                     not specified anywhere
    - `infeasible`                — Requires private hardware /
                                     private data / custom firmware

  ## Internal-consistency checks
  Cross-paper claims that should be verified against the paper's own
  numbers (e.g., abstract claim X% matches §4 figure Y).

────────────────────────────────────────────────────────────────────
FILE 2 — `verification_code_py`  (Python)
────────────────────────────────────────────────────────────────────
Standalone Python script that performs the consistency / numerical
checks identified above. Structure:

```python
#!/usr/bin/env python3
"""Verification script for <paper title>.
Cross-checks paper claims against reported numbers."""

import re, sys

PAPER_CLAIMS = {
    # claim_id: {"text": "...", "expected": <value>, "tolerance": <%>, "source": "<section>"}
}

def check_claim(claim_id, observed):
    c = PAPER_CLAIMS[claim_id]
    delta = abs(observed - c["expected"]) / max(abs(c["expected"]), 1e-12)
    ok = delta <= c["tolerance"]
    print(f"{'PASS' if ok else 'FAIL'}  {claim_id}: expected={c['expected']} "
          f"observed={observed} tol={c['tolerance']*100:.1f}%")
    return ok

# Example callers (populate PAPER_CLAIMS with concrete entries from the paper)
if __name__ == "__main__":
    # Each entry is a verifier the paper's own data should satisfy.
    # Skip / leave as commented stubs only when no verifiable claim exists.
    pass
```

Populate `PAPER_CLAIMS` with EVERY numerical / proportional claim the
paper makes that has a concrete value (e.g., "speedup 2.4×", "throughput
60% of baseline", "RRMSE < 0.05"). Use tolerances appropriate to the
paper's own reported uncertainty. If the paper makes no quantifiable
claims, write a stub with one TODO comment explaining why.

────────────────────────────────────────────────────────────────────
FILE 3 — `install_commands_txt`  (Plain text)
────────────────────────────────────────────────────────────────────
Every concrete shell command extractable from the paper or AD/AE for
**obtaining, building, installing, and configuring** the artifact. One
command per line. Quote source for each, like:

```
# AD §A2.1
git clone --recurse-submodules https://example.com/repo.git
# AD §A3
cd repo && bash install_deps.sh
# Paper §IV-A
export OMP_NUM_THREADS=16
```

Empty file with a single `# (no install commands found in paper/AD/AE)`
comment when the paper specifies nothing.

────────────────────────────────────────────────────────────────────
FILE 4 — `reproduce_log_sim`  (Plain text, simulated)
────────────────────────────────────────────────────────────────────
A **simulated** reproduce.log: what stdout would PLAUSIBLY look like if
a practitioner followed `install_commands_txt` then ran one experiment
from `reproduce_plan_md`. Use the paper's own reported numbers as the
"observed" values. **THIS FIELD MUST BE LONG** — at minimum 30 lines
covering install + run + result blocks for every experiment named in
`reproduce_plan_md`. Do not emit a placeholder. Format like real shell
output:

```
$ bash install_deps.sh
[install] cloning submodules ...
[install] OK

$ bash reproduce.sh experiment_A
[run] experiment=experiment_A
[run] params: <key=value, key=value, ...>
[run] launched: <command from install_commands.txt or paper §X>
[run] elapsed: <wall_time_from_paper or <UNKNOWN>>
[result] <metric_name>: <number_from_paper>
[result] <metric_name>: <number_from_paper>

$ bash reproduce.sh experiment_B
... (repeat the block for every experiment named in reproduce_plan_md)
```

This is what downstream `verification_code.py` would consume. Every
numerical value MUST come verbatim from the paper or AD/AE (cite by
context in a `# (from paper §X)` comment line). Mark anything the
paper does NOT specify as `<UNKNOWN>` rather than fabricating it.

JSON-encoding reminder: this field is a single JSON string. Newlines
must be escaped as `\n`. Do NOT wrap it in a code fence inside the
JSON value.

────────────────────────────────────────────────────────────────────
GLOBAL RULES
────────────────────────────────────────────────────────────────────
1. Never invent numbers. If the paper doesn't state a value, write
   `*(NOT SPECIFIED)*` (markdown) or `<UNKNOWN>` (plain text) — judges
   downstream will treat these as audit findings, which is correct.
2. Cite the source section / appendix for every concrete value.
3. Do not paraphrase paper claims; quote them verbatim where possible.
4. If the paper has multiple sub-experiments, enumerate each one. Do
   not summarize them into one block.
5. If the paper is from a venue with a structured reproducibility
   appendix or checklist, the {VENUE_HINT} block above carries
   venue-specific requirements — follow those in addition to these
   rules.

────────────────────────────────────────────────────────────────────
PAPER:
{PAPER_TEXT}
