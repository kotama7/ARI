---
sources:
  - path: ari-skill-web/src/server.py
    role: implementation
  - path: ari-skill-web/REQUIREMENTS.md
    role: doc
  - path: ari-skill-web/mcp.json
    role: config
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-08-02
---

# C04: `ari-skill-web` 実装計画

> 状態: Proposed。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、末尾の削除要件を満たしたら削除する。

## 1. 責務

Web、論文index、citation graphから取得した情報を、source provenance付きの`RetrievalRecordV1`として提供する。検索結果の科学的採用判断やidea生成は行わず、取得、正規化、snapshot、citation identityを所有する。

## 2. 現状と課題

- DuckDuckGo、arXiv、Semantic Scholar、AlphaXiv、URL fetch、iterative citation collectionが一serverにある。
- READMEは「LLMを呼ばない」とする一方、実装にはLLM helperとiterative選択経路があり、契約の再監査が必要である。
- provider fallbackが同一queryの意味と再現性を変え得る。
- live page取得にはSSRF、redirect、content size、content-type、prompt injection対策が必要である。
- manifestがruntimeに存在する全toolを列挙していない。

## 3. 目標契約

各結果はcanonical identifier、title/authors、source URL、provider、query、取得時刻、provider record ID/version、payload digest、citation edge、license/use restrictionを持つ。record modeではproviderを固定し、raw responseまたは再取得可能なversion identityをartifact化する。

## 4. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C04-01 | tool / manifest / docsの事実監査 | canonical tool inventory |
| C04-02 | provider adapter境界 | DuckDuckGo / arXiv / S2 / AlphaXiv adapter |
| C04-03 | `RetrievalRecordV1` とdedup | DOI/arXiv/S2 ID、origin、raw digest |
| C04-04 | live / record / replay | cassette、ETag/Last-Modified、offline fixture |
| C04-05 | URL fetch security | scheme/host/IP policy、redirect再検証、size/type limit |
| C04-06 | citation walkのbounded execution | depth/node/budget、cycle detection、partial result |
| C04-07 | ranking/LLM使用の明示分離 | deterministic retrievalとoptional rerankerの別tool_ref |
| C04-08 | idea / paper consumer migration | snapshot refで受け渡し、inline巨大payload廃止 |

## 5. 受け入れ基準

- [ ] private/loopback/link-local destination、DNS rebinding、oversize responseを拒否する。
- [ ] redirect先にも同じnetwork policyを適用する。
- [ ] record modeでprovider outage時に別providerへ黙って切り替わらない。
- [ ] 同じpaperの複数provider recordをaliasとして保持し、source lineageを失わない。
- [ ] citation graphのcycleとbudget超過がbounded partial resultになる。
- [ ] replayはnetworkなしで同じnormalized recordsを返す。
- [ ] LLMを使うpathはmanifestで`determinism: stochastic`とmodel provenanceを持つ。
- [ ] `pytest ari-skill-web/tests -q` とSSRF/cassette contract testがgreenである。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C04-D1 | record modeのimplicit backend fallback | pinned provider adapter | P3 | outage testがexplicit error、cassette keyにprovider含有 |
| C04-D2 | providerごとに異なるad-hoc result dict | `RetrievalRecordV1` | P3 |全provider golden fixture parity |
| C04-D3 | unrestricted `fetch_url` network path | URL fetch security policy | P2 |SSRF suite green、旧caller migration |
| C04-D4 | `search_arxiv`等のdeprecated narrow alias | `search_papers(provider=...)`またはbroker discovery | P6 | deprecation release、workflow/docs caller 0 |
| C04-D5 | manifestにないhidden public tools / stale declaration | canonical manifest | P1 | runtime `tools/list`完全一致 |
| C04-D6 | LLM helperをdeterministic retrieval内で暗黙使用するpath |明示reranker component | P3 |traceでLLM call 0、reranker contract test |

### 6.2 削除の検証と復旧

各 deletion PR は `pytest ari-skill-web/tests -q`、SSRF corpus、provider outage、offline cassette replay、対象referenceへの `rg` を実行する。公開alias削除前commitとprovider fixturesをrollback基点にし、旧record format readerはsupport window中保持する。

### 6.3 計画書自身の削除

C04-01〜08、受け入れ基準、C04-D1〜D6を閉じ、retrieval/security/replay仕様を恒久文書へ移した後に削除する。
