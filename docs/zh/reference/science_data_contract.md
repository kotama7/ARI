---
sources:
  - path: ari-core/ari/science_data_contract.py
    role: implementation
  - path: ari-skill-transform/src/science_data.py
    role: implementation
  - path: ari-skill-transform/src/ear.py
    role: implementation
last_verified: 2026-08-02
---

# Science data 与 EAR 完整性

新的 transform run 只生成 `ari.science-data/v1`。该格式包含三个独立的
content-addressed section：

- `raw`：tree、typed `MeasurementSetV1`、执行配置、environment 与精确输入artifact；
- `derived`：使用core唯一formula registry计算的汇总与numeric claim；
- `interpretation`：绑定`raw_digest`且永久为`claim_eligible=false`的可选模型注释。

`deterministic_digest`不包含interpretation，因此更换模型、prompt或注释文字不会改变
measurement和derived claim的identity。`science_data_digest`覆盖完整record。consumer只可
在有限迁移接口中使用`science_data_projection`，不得把interpretation数值合并为
measurement。

只有带已完成execution identity的canonical measurement可以支持claim。untyped node
metric保留在`legacy_metrics`中供检查，但不会生成汇总或claim。node report缺失或node
identity不符时annotation为unavailable；live path不会扫描`trace_log`或任意work
directory来补偿。

pre-v1 artifact必须显式离线转换：

```bash
python scripts/migrate_science_data.py old.json science_data.v1.json --run-id RUN_ID
```

旧measurement仍不可支持claim，未绑定的旧claim不会被接纳，native parser也不会隐式
迁移。

EAR `manifest.lock` v2绑定排序后的file content/role、curation policy、evidence index、
`SKILLS.lock`、`CATALOG.lock`、cassette、ResultEnvelope artifact、科学契约和admission
report。curate在可恢复目录交换前验证全部digest；publish和clone再次独立验证。backend
失败不会破坏本地curated bundle。已发布的manifest v1只通过read-only reader支持。
