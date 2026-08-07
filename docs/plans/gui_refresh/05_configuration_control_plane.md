# 05 — Configuration Control Plane

> Status: planned  
> Dependencies: 00, 04  
> Gate: G3 — Configuration truth

## Purpose

Pydantic defaults、YAML、profile、environment、project settings、Wizard、checkpoint に分散する設定を、一つの schema と resolver で説明・検証・保存できる control plane に統合する。GUI を「設定の唯一の正本」と誤表示せず、各値の effective value、source、scope、適用時点を追跡可能にする。

## Scope

- canonical config metadata/schema registry。
- legacy-compatible resolver と versioned target precedence。
- scope、mutability、sensitivity、dependency/interlock、merge semantics。
- project/template/draft/run snapshot の persistence と provenance。
- secret reference/readiness 管理。
- versioned config API、validation、diff、atomic write、concurrency control。
- Settings 24-key、workflow YAML、profile/env、launch mapping の migration。

## Non-goals

- 全 environment variable を即時廃止しない。
- secret の実値を GUI で再表示しない。
- active run の immutable algorithm mode を編集可能にしない。
- unknown plugin/skill config を silent drop しない。

## Current sources

| Source | Current role | Risk |
|---|---|---|
| Pydantic field defaults (`ARIConfig`) | 全 leaf の実効既定値。実際に load される唯一の defaults | YAML/UI と重複 |
| `ari/configs/defaults.yaml` | RQGM/proposal_router defaults の**パリティ参照**。runtime では load されず、対応する pydantic defaults が実効値（parity は named tests が固定） | 「正本」と誤解して UI がこれを読むと drift する |
| `config/workflow.yaml` | pipeline 定義 **兼** `ARIConfig` top-level 入力。`model_fields` 外の top-level key は silent drop | docs 上の正本と実態がずれる。silent drop が誤設定を隠す |
| `config/default.yaml` | legacy schema。viz の skill-phase 補完と finder fallback のみが読む | 第三の「config file」として混同されやすい |
| `config/profiles/*.yaml` | laptop/HPC/cloud override。merge されるのは `bfts.max_total_nodes`、`bfts.max_parallel_nodes`/`parallel`、`hpc.enabled`、`hpc.scheduler` の 4 key のみで他は無視 | 適用されたように見えて適用されない field がある |
| process environment / `.env` | `apply_*_env_overrides` 系（`ARI_MODEL`、`ARI_BACKEND`、`ARI_CHECKPOINT_DIR`、`ARI_MAX_*`、`ARI_FRONTIER_SCORE`、`ARI_COMPOSITE`、`ARI_AXIS_MODE`、`ARI_MODE`、`ARI_RQGM_ENABLED`、`ARI_PAPER_MODE` ほか約 15 系統）+ YAML `${VAR}` 補間 + env-only の `auto_config()` 経路 | provenance/secret 境界が弱い。env は profile より後に適用され最優先 |
| project `settings.json` | checkpoint-scoped GUI settings。`load_config` は読まず、launch 時に `ARI_*` env へ翻訳されて初めて run に届く | shallow merge、schema 検証不足、GET/POST shape 非対称 |
| Wizard local state | launch-only override | draft/resume/型保証がない |
| `launch_config.json` | launch 時の実効 config snapshot。driver の template 変数 `launch_config.*` として stage から参照される | resolver 全体の provenance ではない |
| checkpoint state | resume の mode/設定。`rqgm_state.json` の persisted mode が config/env より優先（`reconcile_resume_mode`、downgrade-only） | new-run settings より優先すべき値がある |

現行の precedence は宣言的な merge ではなく、CLI の命令的な呼び出し順（おおよそ env > profile > `workflow.yaml` > pydantic defaults。ただし profile 適用後に env override を掛け直す設計）で決まる。GUI Settings は env 翻訳経由でのみ run に関与するため、runtime・GUI Settings・launch では precedence が完全には一致しない。最初の resolver は現在の文脈別挙動を正確に再現し、golden parity 後に versioned policy として整理する。

## Canonical field metadata

```python
class ConfigFieldMeta:
    path: str
    value_type: str
    default: object
    enum: list[object] | None
    minimum: float | None
    maximum: float | None
    description_key: str
    category: str
    level: str                 # basic / advanced / expert
    scope: str                 # preference / installation / project / template / run
    sensitivity: str           # public / internal / secret_reference
    mutability: str            # draft / new_run_only / resume_mutable / read_only
    merge_strategy: str        # replace / deep_merge / append_unique
    dependencies: list[str]
    conflicts: list[str]
    capability: str | None
    deprecation: object | None
```

- `ARIConfig`/nested Pydantic models を type、default、validation の基礎にする。ただし現状の制約を registry 側で吸収する: pydantic v2 で nested model は `extra="allow"`、assignment は再検証されない（env override は手書き enum guard）、top-level は `model_fields` prefilter で silent drop、config への jsonschema 検証は存在しない。
- UI category、scope、sensitivity、mutability など runtime 型にない metadata を明示 registry で補う。
- schema generation は model catalog、enum、description を frontend constant へ複製しない。
- schema version と resolver version を別に持つ。
- field alias/deprecation は migration function と warning を持つ。

## Configuration scopes

| Scope | Examples | Persistence | Editability |
|---|---|---|---|
| User preference | locale、theme、density、Developer Mode | browser-local | user editable |
| Installation | provider availability、scheduler、container runtime | server config | admin/operator |
| Secret reference | API key、SSH credential | secret provider | write-only/readiness only |
| Project default | common model、retrieval、resource defaults | project config | project editable |
| Run template | workflow、BFTS、RQGM、paper、evaluation | versioned template | editable/cloneable |
| Run draft | one launch override | draft document | editable until launch |
| Run snapshot | effective launch/resume config | checkpoint artifact | immutable/read-only |

GUI の category と storage scope を同じ概念にしない。例えば Models category 内でも secret reference、project default、run override が混在し得る。

なお現行実装の scope は実質二値（machine/env と per-checkpoint。project ≡ run ≡ checkpoint dir で `~/.ari` 等の global 設定は存在しない）であり、Installation / Project default / Run template の各 scope は greenfield。導入時は保存場所と ownership を ADR で決める。

## Resolution model

### New run

```text
schema default
→ repository/workflow default
→ selected execution profile
→ installation policy
→ project default
→ run template
→ run draft override
→ explicitly allowed environment override
→ validated effective config
```

### Resume

```text
checkpoint resolved snapshot
→ only fields marked resume_mutable
→ explicitly allowed operational override
→ validated resume config
```

- checkpoint の execution mode（`ari.mode`）、paper mode（`paper.mode`）、RQGM policy history は immutable。
- resolver は leaf ごとに value、source layer、source location、applied_at、mutability、warning を返す。
- rejected/ignored override も explanation として返す。
- 初期 `resolver_version=legacy-compatible` は現在の context-specific precedence を再現する。
- target resolver への変更は migration preview と explicit version bump を要求する。

## Resolved manifest

run ごとに additive artifact `resolved_config.json` を保存する。

```json
{
  "schema_version": 1,
  "resolver_version": "legacy-compatible-1",
  "run_id": "...",
  "resolved_at": "...",
  "digest": "sha256:...",
  "source_stack": ["default", "workflow", "profile", "project", "draft"],
  "values": {"ari": {"mode": "ari_rqgm"}},
  "provenance": {
    "ari.mode": {"source": "run_template", "mutable": false}
  },
  "secret_references": {
    "llm.api_key": {"provider": "env", "configured": true}
  },
  "warnings": []
}
```

- secret value は含めない。
- digest は redacted canonical representation から計算する。
- old checkpoint で manifest がない場合は best-effort reconstructed view と confidence/source warning を返す。
- raw legacy files は変更せず、manifest は additive とする。

## Configuration API

```text
GET   /api/v1/config/schema
GET   /api/v1/config/catalogs/models
GET   /api/v1/projects/{project_id}/config
PATCH /api/v1/projects/{project_id}/config       # ETag/revision required
GET   /api/v1/run-templates/{template_id}
PATCH /api/v1/run-templates/{template_id}
POST  /api/v1/run-drafts/{draft_id}/resolve-config
POST  /api/v1/run-drafts/{draft_id}/validate
GET   /api/v1/runs/{run_id}/resolved-config
PUT   /api/v1/secrets/{secret_id}                # write-only
GET   /api/v1/secrets/{secret_id}/status
```

- GET は value と metadata を別 object として返し、secret は `configured/source/last_updated` のみ。
- PATCH は unknown path、wrong type/range、dependency violation、stale revision を正規 error にする。
- raw YAML editor は parsed patch と lossless unknown-field preservation を使う。
- write は lock、temporary file、fsync、atomic rename、backup policy を持つ。
- project が無い場合に secret だけ先に mutation するような非 transaction behavior を禁止する。

## Interlocks and policy

- `ari.mode=ari_rqgm` と `rqgm.enabled=true` は一つの intent として編集し、draft validation では不整合を error にする。ただし runtime の `resolve_effective_mode` は不整合を warning + `simple_bfts` fallback で解決する（error にしない）ため、effective 表示は必ず**解決後**の mode を示し、「要求したが fallback した」状態を明示的に警告する。GUI が RQGM active と表示してよいのは解決結果が `ari_rqgm` の場合のみ。
- paper mode（`paper.mode` + `rqgm.paper.enabled`、同じ warn+fallback 意味論）は独立軸だが、組合せの意味を preview する。
- mode の provenance は `rqgm_state.json` の `mode_source`（`config`/`env`/`resume`）と `switch_journal` を表示に用いる。
- RQGM は new run only。active checkpoint では read-only。現行 v1 は「RQGM の CLI flag/GUI toggle なし」を明示決定している（`docs/guides/execution_modes.md`）ため、GUI から mode を選択可能にすることはこの決定の supersede であり、ADR と docs 更新を伴う。
- profile が merge しない field は「未対応」と明示し、適用済みと見せない。
- setting の変更が current run、next run、resume、installation restart のどれに効くか表示する。
- policy-controlled field は disabled にするだけでなく policy reason/source を返す。

## Legacy adapter

- Settings の flat 24-key POST（`SettingsContract.test.tsx` が固定）を exact fixture で維持する。GET は 27 top-level key（26 scalar/list + nested `ors`）で POST と key 集合が一致しない非対称契約であることも fixture 化する（POST のみにある `ssh_*`/`llm_base_url`/`slurm_partitions`、GET のみにある `ollama_host`/`mcp_skills`/`vlm_review_*`/`letta_deployment*`/`ors` など）。
- legacy GET の `{**defaults, **saved}` shallow merge behavior を adapter 内に閉じ込める。
- legacy `_status` in body などの status quirk は旧 endpoint のみ維持する。
- api key の `.env` upsert 経路（provider→env-key mapping、「20 文字未満は無視」heuristic による silent drop）は既知欠陥として fixture 化し、canonical secret API では再現しない。
- 平文 secret を返す `GET /api/env-keys` は新 secret readiness API 導入後に閉鎖・置換する（task 09 と共有）。
- old `settings.json`、workflow YAML、launch config を dual-read する。
- canonical write を導入した後も downgrade 不要の backup/compatibility export を用意する。
- card 数や DOM 常駐を contract とする test は、capability/value retention test 移行後に削除する。

## Validation and tests

- 全 Pydantic/config YAML leaf の schema coverage inventory。
- default/profile/project/template/draft/env/resume の precedence matrix golden test。
- deep merge、list merge、zero/null/empty、unknown/additive key の round-trip test。
- alias/deprecation/version migration test。
- ETag conflict、concurrent write、crash during write、backup restore test。
- secret response 0 件、redaction、allowlist、newline injection、file mode test。
- old checkpoint reconstruction と `simple_bfts` identity test。
- launch manifest digest/reload/reproduce test。

## Completion criteria

- config leaf の 100% が schema registry に登録されるか、非公開理由を持つ。
- CLI、GUI preview、launch が同じ resolver service を使う。
- effective value/source/scope/applies-when を leaf 単位で取得できる。
- secret の平文が API、manifest、browser、log に現れない。
- legacy Settings/workflow/checkpoint contract suite が green である。
- RQGM interlock と resume immutability が backend validation で保証される。

## Deletion criteria

- config schema、precedence、scope、secret、manifest format を reference docs へ移し、frontend hard-coded catalog と ad-hoc resolver が削除済みである。

## Delete-after checklist

- [ ] configuration reference と migration guide を更新した。
- [ ] schema coverage report を CI artifact に移した。
- [ ] legacy hard-coded defaults/catalog の usage がゼロである。
- [ ] main merge と CI green を確認した。
- [ ] `INDEX.md` を更新した。

