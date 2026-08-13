---
sources:
  - path: ari-core/ari/manuscript/profiles.py
    role: implementation
  - path: ari-core/ari/manuscript/builder.py
    role: implementation
  - path: ari-core/ari/manuscript/snapshot.py
    role: implementation
  - path: ari-core/ari/manuscript/readiness.py
    role: implementation
  - path: ari-core/ari/manuscript/briefs.py
    role: implementation
  - path: ari-core/ari/manuscript/publication.py
    role: implementation
  - path: ari-core/ari/manuscript/runtime.py
    role: implementation
  - path: ari-core/ari/manuscript/contracts.py
    role: schema
  - path: ari-core/ari/config/__init__.py
    role: config
  - path: ari-core/config/workflow.yaml
    role: config
  - path: docs/adr/manuscript_complete/MC-ADR-007-runner-up.md
    role: doc
last_verified: 2026-08-09
---

# `generic_empirical_v1` profile

最初の profile は empirical な論文のためのものです。適用可否は型付きの
context 特性から導出され、書き手が requirement を適用対象から外すことは
できません。

| Requirement | 適用条件 | Authoring | Publication | 主 resolver |
|---|---|---:|---:|---|
| MC-RQ-001 問い/目的 | 常に | block | block | method/人手による明確化 |
| MC-RQ-002 hypothesis/反証 | hypothesis testing | block | block | method/人手による明確化 |
| MC-ME-001 method | 常に | block | block | artifact recovery |
| MC-ME-002 configuration/environment | empirical | block | block | artifact recovery |
| MC-ME-003 protocol/workload/停止規則 | empirical | block | block | artifact recovery/validation |
| MC-RS-001 primary result の identity | result claim | block | block | projection/validation |
| MC-RS-002 uncertainty | stochastic claim | block | block | repetition |
| MC-CP-001 baseline | comparative claim | block | block | baseline 実験 |
| MC-CP-002 同等の protocol | comparator が存在 | block | block | validation |
| MC-AB-001 component の ablation | multi-component claim | block | block | ablation |
| MC-CL-001 claim coverage | result claim | block | block | projection rebuild |
| MC-CL-002 数値の再現性 | numeric result | block | block | projection/validation |
| MC-NG-001 negative accounting | 常に | report | block | projection/disclosure |
| MC-SL-001 selection accounting | candidate が複数 | report | block | projection rebuild |
| MC-RW-001 記録済み related work | 常に | block | block | 記録済み retrieval |
| MC-RW-002 novelty distinction | novelty claim | block | block | 記録済み retrieval/人手 |
| MC-LM-001 limitations | 常に | block | block | disclosure |
| MC-LM-002 validity threats | empirical | report | block | disclosure |
| MC-RP-001 EAR/source/environment | empirical | block | block | artifact recovery |
| MC-RP-002 command/lock | reproducibility claim | block | block | artifact recovery |
| MC-AS-001 現行の certification | assurance enforce | report | block | 固定 certification |
| MC-OM-001 omission accounting | manuscript 有効 | block | block | projection rebuild |

`stochastic_claim`、`comparative_claim`、`multi_component_claim` といった特性は、
記録された測定値、configuration、metric 語彙、contribution 構造、node のラベル
から得られます。reviewer の散文から推論されることはありません。将来 profile を
変更するには新しい profile ID / version が必要であり、したがって新しい attempt
identity が必要になります。

## Evidence lane の割り当て

`build_manuscript_context` は、固定された順序付き検査リスト
（`ari-core/ari/manuscript/builder.py` の `_lane`）を実行して、exploration
snapshot の各 node にちょうど 1 つの evidence lane を与えます。最初に一致した
検査が勝ち、その検査が lane と、`EvidenceRecordV1.reason_codes` に記録される
reason code を供給します。

検査 2〜5 が読む provenance status は、`node_provenance_audit.json`（workflow
stage `audit_node_provenance`）に記録された node ごとの status と、その node が
参照する各 artifact について snapshot projection が再計算した status との
和集合です。

| # | 検査 | Lane | Reason code |
|---:|---|---|---|
| 1 | terminal な execution status: `failed`、`abandoned`、`cancelled`、`error`、`inconclusive`、`null` | contextual_negative | `execution_<status>` |
| 2 | 再 hash が記録済みの digest/size と食い違う参照 artifact がある | excluded | `artifact_digest_mismatch` |
| 3 | checkpoint から消えている参照 artifact がある | excluded | `artifact_missing` |
| 4 | 安全でない参照 artifact がある: path escape、symlink 成分、読めない/parse できない、または別の node を名指す attestation | excluded | `artifact_invalid` |
| 5 | 記録済みの baseline hash に対して audit が検証できなかった参照 artifact、または path を一切名指さない node の artifact entry がある | exploratory | `artifact_unhashed` |
| 6 | `valid_for_frontier` が false —— RQGM の selective erasure（`_valid_for_frontier: false`）または `_stale` metric sentinel | excluded | `stale_or_erased` |
| 7 | real data が無い、または metric が無い | contextual_negative | `no_real_measurement` |
| 8 | `frontier_class == "debug_frontier"` | exploratory | `debug_frontier` |
| 9 | `frontier_class == "uncertified_frontier"` | exploratory | `uncertified_frontier` |
| 10 | `fail` または `tampered` の property verdict がある | excluded | `assurance_property_failed` |
| 11 | `assurance.mode: enforce` でありながら、assurance status `pass`、assurance tier `certify`、admit された certify attestation が 1 つ以上、記録済みの verified target digest という**4 つすべて**が揃っていない | exploratory | `certification_required` |
| 12 | `assurance.mode: audit` で、*記録された* assurance status が `pass` でない | exploratory | `assurance_<status>` |
| 13 | それ以外 | publishable | `typed_measurement` |

この順序は規範です。provenance の完全性（2〜5）は assurance（10〜12）より先に
検査されるため、記録された identity に対して artifact を再 hash できない node
は、どれだけ十分に certify されていても excluded になります。frontier class
（8〜9）は mode 依存の検査より先に検査されるため、debug または uncertified な
frontier の node はどの mode でも publishable にはなりません: RQGM は既に、その
node の harness verdict が `fail` であったこと（`debug_frontier`）、あるいは
`pass` verdict がそもそも確立されなかったこと —— inconclusive、infrastructure
error、または KCA によるブロック（`uncertified_frontier`）—— を記録しています。
どの assurance mode もそれを publication の裏づけへ戻すことはできません。

### mode 依存

検査 1〜10 と 13 は mode に依存しません。`assurance.mode`（`off` | `audit` |
`enforce`、`AssuranceRuntimeConfig`）を読むのは検査 11〜12 だけです。

| node の形 | `off` | `audit` | `enforce` |
|---|---|---|---|
| typed measurement、attestation 無し | publishable | publishable | exploratory |
| screen attestation のみ、certify 無し | publishable | publishable | exploratory |
| 記録済み target に対して certify `pass` が admit されている | publishable | publishable | publishable |
| 記録された assurance status が `pass` でないが、property は `pass` のまま | publishable | exploratory | exploratory |
| `fail` または `tampered` の property がある | excluded | excluded | excluded |
| stale、または論理的に erase 済み | excluded | excluded | excluded |
| 唯一の certify attestation が別の target に束縛されている | publishable | publishable | exploratory |
| debug または uncertified な frontier | exploratory | exploratory | exploratory |

`audit` は、certification が無いというだけの証拠を意図的に格下げしません。
検査 12 が発火するのは*記録された*非 `pass` の assurance status に対してだけで、
空の `assurance_status` は `publishable` へ抜けます。assurance record が無いとは
assurance を実行しなかったということであり、それは legacy の姿勢です。それを
publication の裏づけとして拒むことこそ、`enforce` が追加するものです。

`target_digest` が node の `verified_target_digest` と一致しない attestation は、
artifact status `stale` として projection されます。`stale` は node を excluded
にする status（2〜4）ではないため、そうした node は `off` と `audit` の下では
admissible なままです。単にその attestation が `certify_attestation_item_ids`
へ admit されないだけであり、それが唯一の certify attestation だった場合に検査
11 が `enforce` の下でその node を格下げする理由もそこにあります。

### lane の帰結

section brief の、positive claim に使ってよい証拠へ入るのは `publishable` lane
の record だけです。`exploratory` と `excluded` の record は forbidden として、
`contextual_negative` の record は disclose 専用として列挙されます。これとは
別に、`EvidenceRecordV1.claim_eligible_fact` は `publishable` と `exploratory`
で true、`contextual_negative` と `excluded` で false です。契約は、
`publishable` lane の外で publication eligibility を主張する record も、
negative/excluded lane の内側で claim eligibility を主張する record も拒否します。

## subject の選択

MC-SL-001 と MC-AS-001 はいずれも、compiler が論文の subject をどう選ぶかに
依存します。その決定は `ManuscriptContextV1` の 2 つの block へ projection され
ます: 異なる policy で計算した 2 つの subject を運ぶ `subjects` と、
certification の証拠の傍らで結果を繰り返す `assurance` です。

`scientific_winner` は snapshot 自身の selection policy から来ます。その payload
は `ExplorationSnapshotV1.selection_policy_digest` へ hash されます。

| Payload key | 値 |
|---|---|
| `policy` | `manuscript-scientific-winner-v1` |
| `validity` | `valid_for_frontier` |
| `eligibility` | `real_data_then_all` |
| `order` | `scientific_score_desc`、次に `node_id_desc` |

`real_data_then_all` とは、valid な node のいずれかが real data を持つときは
real data を持つ valid な node、そうでなければ valid な node すべて、という
意味です。node の score は、`metrics["_scientific_score"]` の値が実数のときは
その値、そうでなければ key が `_` で始まらない numeric metric のうち最大のもの、
それも無ければ score 無しです。boolean が数えられることは決してなく、score の
無い node は score を持つあらゆる node の下に並びます。metric は、いずれかの値
が非有限のとき mapping 全体を文字列化する JSON safety pass を通って snapshot
へ届くため、`NaN` が 1 つあるだけでその node は score 無しになります。

`publication_candidate` は、winner 自身の evidence record が `publishable` lane
にある場合に限り scientific winner になります。そうでなければ candidate は null
であり、どの場合に当たるかを `selection_reason` が記録します。

| `selection_reason` | 意味 |
|---|---|
| `scientific_winner_is_publishable` | candidate は winner |
| `certified_alternative_available:<node-id>` | candidate は null。名指された node は、同じ順序付けの下で最も score の高い publishable な node |
| `no_publishable_candidate` | candidate は null。publishable な node が 1 つも無い |

`certified_alternatives` は、scientific winner 以外のすべての publishable な
node を snapshot の順序 —— depth、次に node ID —— で列挙します。score 順では
ないため、reason code が名指す node が必ずしも最初の entry とは限りません。
この field も `assurance.certified_node_ids` も「certified」と言いますが、両者
が適用する述語は `publishable` lane です。その lane が certify tier の
attestation を要求するのは `assurance_mode=enforce` の下でだけです。

`assurance` block は、`publication_candidate`、`scientific_winner`、
`selection_reason` を、`certified_node_ids`（winner を含むすべての publishable
な node）、node が自分の certify attestation として記録した `present` な
harness attestation item、および `present` でないすべての harness attestation
item の傍らで繰り返します。MC-AS-001 が読むのはまさにその block です。candidate
が非 null で `certified_node_ids` に現れるときにだけ満たされ、certify
attestation item が 1 つも present でないときは `missing` ではなく
`unavailable` を報告します。`enforce` の下では、null の candidate はさらに、
scientific winner がまだ publication に admit できる certification を持たない
旨を述べる自動的な limitation を追加します。MC-SL-001 は `node_count` と
`selection_reason` を読み、exploration history が snapshot の node 1 つにつき
1 entry を持ち、かつ reason が記録されているときにだけ満たされます。

alternative を記録することは、それを選択することではありません。
[MC-ADR-007](../../adr/manuscript_complete/MC-ADR-007-runner-up.md) により、
compiler が block された winner の代わりに publishable な runner-up を据える
ことは決してありません: `certified_alternatives` を subject として読み返す code
は存在せず、黙った差し替えは論文が何についてのものかを、そうと言わずに変えて
しまいます。winner は、明示的な selection 決定が新しい attempt を作るまで
publication-blocked のままです。`subjects` block 全体は abstract の section
brief へも `subject-selection` item として届くため、書き手は生き残った subject
だけでなく、その乖離と理由を受け取ります。

### publication candidate が存在しない場合

MC-AS-001 が適用されるのは `assurance.mode: enforce` の下だけであり ——
`assurance_enforce` 特性は `assurance_mode == "enforce"` であって、それ以外の
何物でもありません —— publication をブロックしますが authoring はブロックしま
せん。したがって null の candidate は mode ごとに違うものを代償にします。

| `assurance.mode` と attestation の状態 | MC-AS-001 の status / reason | authoring verdict への影響 | publication verdict への影響 |
|---|---|---|---|
| `off` または `audit` | `not_applicable` / `applicability_rule_false` | 無し | 無し |
| `enforce`、`assurance.attestation_item_ids` が非空 | `missing` / `publication_certification_missing` | 無し | `blocked` |
| `enforce`、`assurance.attestation_item_ids` が空 | `unavailable` / `publication_certification_unavailable` | 良くて `ready_with_disclosures` | `blocked` |

`off` と `audit` では requirement は不活性です: evidence ref も resolver も
verdict への影響もありません。`PublicationDecisionV1` の `assurance`
sub-verdict はこのとき pass ではなく `not_required` になります。runtime が
assurance を required と印すのは mode が `enforce` のときだけだからです。null
の candidate とその `selection_reason` は、それでも両方の block に記録されます。

3 行目が authoring verdict を動かすのは、`unavailable` な requirement があれば
`ready` の report を `ready_with_disclosures` へ格下げする、という一般規則を
通してだけです。MC-AS-001 は、失敗する 2 行のどちらでも authoring をブロック
することは決してなく、他の requirement が既に押し下げた authoring verdict を
改善することも決してありません。

この非対称性が設計です。enforce lane が node を `publishable` として admit する
のは、certify tier の assurance status が pass で、admit された certify
attestation が 1 つ以上あり、verified target digest がある場合だけなので、
`enforce` の下で非 null の candidate は常に certified です —— したがって失敗
する 2 行は、まさに自動的な certification limitation が付く run です。
uncertified な winner を持つ enforce の run でも authoring は行われ、limitation
がその欠落を manuscript へ書き込みます。欠落を述べる draft は正当な artifact
ですが、同じ draft を certified として提示するのは正当ではありません。到達でき
ないままなのは publication lock だけであり、現行の certification が subject を
覆うまで続きます。

### 予約: 明示的な selection 決定

MC-ADR-007 は、fallback しないという既定を覆すことを、version 付きの selection
policy と必須の開示がある場合に限って許します。**そのような policy は実装され
ていません。** `ManuscriptRequirementProfileV1` や `RequirementSpecV1` のどの
field も、どの設定 key も、どの code path も runner-up を subject へ昇格させま
せん。winner が publishable でないとき、candidate は無条件に null です。上の
`selection_policy_digest` もその policy ではありません —— それが pin するのは
scientific winner をどう順序付けるかであって、subject を差し替えてよいかどうか
ではありません。

もしそうした policy がいつか追加されるなら、readiness が `ready` を報告できる
ようになる前に、subject の変更は新しい subject に対して applicability、すべての
requirement result、`limitations` を再計算しなければなりません: 古い subject に
対して評価された requirement set は新しい subject を記述しませんし、subject の
変更をまたいで継承された limitation は、もはや論文の subject ではない node に
ついての開示だからです。その義務は予約された設計であって、利用できる挙動では
ありません。
