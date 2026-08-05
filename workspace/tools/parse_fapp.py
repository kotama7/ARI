"""Turn a Fujitsu `fapp` report into structured fields, and classify the bottleneck.

WHY. Handing an LLM the raw report is handing it a fixed-width text table to
misread. What an optimizer acts on is a small set of named numbers and one
verdict: is this compute bound, memory bound, or neither. This produces both, and
the verdict is RULE-BASED on purpose -- if the classification were itself an LLM
call it would vary between arms, and a handoff experiment would then be measuring
the classifier as much as the channel.

WHAT fapp GIVES. Only event group `pa1` yields the named statistics; pa2 and
beyond return raw counters intended for vendor post-processing. From pa1:

    GFLOPS and its ratio to peak
    memory throughput (GB/s) and its ratio to peak
    SIMD instruction rate, SVE operation rate
    IPC, GIPS, effective instructions

The SVE rate is the one that would have saved this project six failed attempts:
"auto-vectorization emits no SVE here" is one field, not an objdump session.

THE THRESHOLDS ARE A STARTING POINT, NOT A RESULT. They are stated here so they
can be argued with and changed in one place, and so that whatever they are, every
arm of an experiment gets the same ones.

USAGE
    python parse_fapp.py report.txt
    python parse_fapp.py report.txt --json
"""
import argparse
import json
import pathlib
import re
import sys

# Rule-based verdict thresholds. Deliberately conservative and deliberately
# visible: a candidate that is neither clearly bound gets "unclear", not a guess.
MEM_BOUND_PEAK_PCT = 40.0    # memory throughput at >= this % of peak
FP_BOUND_PEAK_PCT = 30.0     # flop rate at >= this % of peak
LOW_SVE_PCT = 1.0            # SVE operation rate below this is "not vectorised"


def _row_after(text: str, header_words: list[str]) -> list[float] | None:
    """The AVG row of the table whose header contains all of header_words.

    fapp wraps a table header across TWO lines -- "Mem throughput" sits above
    "GFLOPS" -- so matching all the words against a single line finds nothing.
    Search a sliding two-line window instead; the first version of this function
    matched per line and silently reported "no pa1 statistics" on a report that
    had them.
    """
    lines = text.splitlines()
    for i in range(len(lines)):
        window = lines[i] + " " + (lines[i + 1] if i + 1 < len(lines) else "")
        if all(w in window for w in header_words):
            for j in range(i, min(i + 8, len(lines))):
                if lines[j].strip().startswith("AVG"):
                    nums = re.findall(r"[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?",
                                      lines[j].split("AVG", 1)[1])
                    return [float(x) for x in nums]
    return None


def parse(text: str) -> dict:
    out: dict = {}
    m = re.search(r"Fujitsu Advanced Performance Profiler Version (\S+)", text)
    if m:
        out["profiler_version"] = m.group(1)
    m = re.search(r"CPU frequency\s*:\s*Process\s+\d+\s+(\d+)\s*\(MHz\)", text)
    if m:
        out["cpu_mhz"] = int(m.group(1))
    m = re.search(r"Type of program\s*:\s*(.+)", text)
    if m:
        out["program_type"] = m.group(1).strip()

    r = _row_after(text, ["GFLOPS", "Mem throughput"])
    if r and len(r) >= 5:
        out.update({"elapsed_s": r[0], "gflops": r[1], "gflops_peak_pct": r[2],
                    "mem_gb_s": r[3], "mem_peak_pct": r[4]})
    r = _row_after(text, ["SIMD inst.", "SVE operation"])
    if r and len(r) >= 4:
        out.update({"effective_instructions": r[0], "fp_operations": r[1],
                    "simd_rate_pct": r[2], "sve_rate_pct": r[3]})
    r = _row_after(text, ["IPC", "GIPS"])
    if r and len(r) >= 2:
        out.update({"ipc": r[0], "gips": r[1]})
    return out


def classify(f: dict) -> dict:
    """One verdict and the reasons for it. Rules, not a model."""
    mem = f.get("mem_peak_pct")
    fp = f.get("gflops_peak_pct")
    sve = f.get("sve_rate_pct")
    reasons, verdict = [], "unclear"

    if mem is not None and mem >= MEM_BOUND_PEAK_PCT:
        verdict = "memory_bound"
        reasons.append(f"memory throughput is {mem:.1f}% of peak "
                       f"(>= {MEM_BOUND_PEAK_PCT:.0f}%)")
    elif fp is not None and fp >= FP_BOUND_PEAK_PCT:
        verdict = "compute_bound"
        reasons.append(f"flop rate is {fp:.1f}% of peak (>= {FP_BOUND_PEAK_PCT:.0f}%)")
    else:
        if mem is not None and fp is not None:
            reasons.append(f"neither is near peak: {fp:.2f}% of flop peak, "
                           f"{mem:.2f}% of memory peak -- the kernel is limited by "
                           f"something other than raw throughput (dependencies, "
                           f"instruction mix, or parallel inefficiency)")

    if sve is not None and sve < LOW_SVE_PCT:
        reasons.append(f"SVE operation rate is {sve:.4f}% -- the vector units are "
                       f"essentially unused, whatever the bound")
    return {"verdict": verdict, "reasons": reasons,
            "thresholds": {"mem_bound_peak_pct": MEM_BOUND_PEAK_PCT,
                           "fp_bound_peak_pct": FP_BOUND_PEAK_PCT,
                           "low_sve_pct": LOW_SVE_PCT}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", help="output of `fapp -A -d <dir> -Icpupa`")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    text = pathlib.Path(args.report).read_text(errors="replace")
    fields = parse(text)
    if not fields.get("gflops"):
        print("no pa1 statistics in this report -- only event group pa1 yields "
              "named metrics; pa2+ return raw counters", file=sys.stderr)
        return 1
    verdict = classify(fields)

    if args.json:
        print(json.dumps({"metrics": fields, "classification": verdict}, indent=1))
        return 0

    print(f"profiler        : fapp {fields.get('profiler_version','?')}  "
          f"({fields.get('program_type','?')}, {fields.get('cpu_mhz','?')} MHz)")
    print(f"elapsed         : {fields.get('elapsed_s', float('nan')):.4f} s")
    print(f"flop rate       : {fields.get('gflops', float('nan')):.4f} GF/s "
          f"({fields.get('gflops_peak_pct', float('nan')):.4f}% of peak)")
    print(f"memory          : {fields.get('mem_gb_s', float('nan')):.4f} GB/s "
          f"({fields.get('mem_peak_pct', float('nan')):.4f}% of peak)")
    print(f"vectorisation   : SIMD {fields.get('simd_rate_pct', float('nan')):.4f}%  "
          f"SVE {fields.get('sve_rate_pct', float('nan')):.4f}%")
    print(f"IPC             : {fields.get('ipc', float('nan')):.4f}")
    print()
    print(f"verdict         : {verdict['verdict']}")
    for r in verdict["reasons"]:
        print(f"  - {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
