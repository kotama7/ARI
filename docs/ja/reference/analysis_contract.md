---
sources:
  - path: ari-core/ari/analysis.py
    role: implementation
  - path: ari-skill-benchmark/src/server.py
    role: implementation
  - path: ari-skill-plot/src/server.py
    role: implementation
last_verified: 2026-08-02
---

# 決定論的解析契約

ARI では測定、統計解析、作図、採否判定を分離する。
`ari-skill-benchmark` は要約・統計検定・run 比較、`ari-skill-plot` は作図、
`ari-skill-evaluator` は科学的 acceptance gate を所有する。

`ari.public.analysis` は `AnalysisRequestV1`、
`StatisticalTestRequestV1`、`RunComparisonRequestV1`、`AnalysisResultV1`
を公開する。全 metric は unit を明示し、metric/unit 不一致、空 sample、
全欠損、paired 長不一致を error にする。欠損は `missing_policy` に従い、
drop 数も結果へ残す。

統計結果は sample 数、test statistic、raw/補正済み p-value、effect size、
confidence interval、assumption diagnostics、Python/NumPy/SciPy version、
解決済み input digest を含む。複数比較では Bonferroni、Holm、または
Benjamini-Hochberg の指定が必須である。`analysis_plan_digest` は事前計画を
固定するが、遵守したこと自体の証明にはしない。

CSV/JSON/npy は閉じた `WorkspaceRefV1`、相対 path、上限 byte、期待 SHA-256
で拘束する。同一 backend/environment を独立 replicate と推論せず、共有
substrate として明示する。異なる環境の ranking は既定で拒否する。

benchmark の旧 `plot`、matplotlib/pandas、schema 無し parsing、p-value のみの
公開 result は v0.2 で削除した。作図は `plot-skill:render_figure` が source・
data・spec・environment・PNG/PDF digest を持つ manifest として生成する。
