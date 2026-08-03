You are a scientific analyst. Read the following structured node reports
(search trajectory; each node lists its delta_vs_parent, files added/modified,
headline metric, concerns flagged by the evaluator, and the literal build/run
commands) and the verbatim source files from the contributing chain, then
extract what a peer reviewer needs to evaluate this work.

Include only scientifically meaningful content: successful measurements, key
improvements, ablation insights, and validated results. Omit failed runs and
internal system details.

Return ONLY valid JSON with these keys:
  'evaluation_protocol': {domain, primary_metrics[], required_reporting[], standard_baselines[], ablation_axes[]}
  'experiment_context': {hardware, methodology, findings, implementation_details, ...}
    The 'hardware' field MUST be filled from the 'ran_on:' lines in the node
    reports — combine the executor type, hostname, SLURM partition, CPU model,
    thread count, and memory across contributing nodes. If different nodes ran
    on different hosts, list them. Do NOT write 'not recorded' when ran_on data
    is present in the reports.
  'implementation_overview' (OPTIONAL): {architecture: '1-3 sentence prose summary', key_algorithms: [{name, pseudocode}], optimizations: ['…']}.
    Omit this whole key if the reports do not contain enough material. Do NOT
    include source code verbatim under this key — code lives in ear/code/.

Extract ONLY what is actually present below. Do not invent details. If
information was not captured, write 'not recorded'.

NODE REPORTS:
__ARI_NODE_REPORTS__

VERBATIM SOURCE (from contributing chain):
__ARI_SELECTED_SOURCE__
