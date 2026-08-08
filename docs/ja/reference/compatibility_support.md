---
sources:
  - path: ari-core/ari/execution.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/server.py
    role: implementation
  - path: ari-skill-paper-re/src/rubric_contract.py
    role: implementation
  - path: ari-skill-paper-re/paperbench_patches.json
    role: config
last_verified: 2026-08-08
---

# Compatibility support policy

互換経路は、read-onlyまたは限定scope、fail closed、owner、客観的な削除gateを持つ
場合だけ保持します。新規producerは廃止形式を出力しません。

| 対象 | 保持理由と境界 | owner | 再評価・削除gate |
|---|---|---|---|
| 旧measurement文書 | parserだけが旧flat v1/unversionedを読み、unitやexecution provenanceを捏造しない。writerはcanonicalのみ。 | ARI core maintainers | v1.1でpublished checkpoint利用0とmigration fixture保存を確認。 |
| 旧research/retrieval/result/figure/review/paper/EAR artifact | replay・検証・明示migrationだけに隔離し、runtime producer fallbackにしない。 | 各skill maintainer | publication/replay support window終了後、format単位で削除。 |
| Letta pip deployment | containerなしのlocal利用向け。自動backend fallbackではない。 | ARI maintainers | v1.1でusageとissueを再評価。 |
| `slurm_submit` bridge | core agentのbatch-script workflow限定。新規integratorは`job_submit`/`container_submit`を使う。 | core + HPC maintainers | agentが`JobRequestV1`を直接生成しcaller 0となるv1.1以降。 |
| Rubric V1 reader/offline migration | digest検証しV2へlossless移行。V1 runtime generatorは存在しない。 | replicate + paper-re maintainers | v1.1でworkflow/artifact利用0。 |
| PaperBench adaptation | exact pinと`paperbench_patches.json`に限定しconformance testする。 | paper-re maintainers | pin更新ごと。宣言された`deletion_gate`条件が満たされ target suite が green なら削除。 |
| Orchestrator registry repair | terminalに見える旧runの明示importだけ。自動discovery/state推測は禁止。 | orchestrator maintainers | v1.1でsupport対象checkpoint移行後。 |
| archived lock/cassette | published dispatchのreplayに必要。digest検証し新runへ暗黙admissionしない。 | registry/provider maintainers | publication/replay window終了後にformat単位で削除。 |

互換writerやsilent fallbackの追加には別のarchitecture decisionが必要です。削除時は
pre-removal commit、changelog、caller 0、owner contract/replay suiteを記録します。
