# 02 — Design System, Accessibility, and Internationalization

> Status: planned  
> Dependencies: 00  
> Gate: G1 — Experience contract

## Purpose

既存の token/CSS 資産を起点に、全 workspace が同じ意味、操作、状態表現を共有する design system を構築する。見た目の統一だけでなく、可視化の誤読防止、アクセシビリティ、三言語運用を release contract にする。

## Scope

- semantic design tokens、layout primitives、typography、density、motion。
- form、table、tabs、dialog、toast、status、empty/error/loading の共通 component。
- D3/React Flow をまたぐ visualization primitives。
- responsive behavior、keyboard、screen reader、contrast、reduced motion。
- 日本語、英語、中国語の resource、formatting、用語 glossary。
- Storybook 相当の component catalog と visual regression fixture。

## Non-goals

- D3 と React Flow を単一 library に統一しない。
- brand redesign を理由に情報構造や domain semantics を変更しない。
- Developer Mode を security boundary にしない。

## Existing touchpoints

- `ari-core/ari/viz/frontend/src/styles/`（`dashboard.css` を entry に `tokens/layout/components/widgets/responsive` の 6 file 構成）
- `ari-core/ari/viz/frontend/src/components/common/`（Badge、Button、Card、EmptyState、ErrorState、LoadingState、StatBox、StatusBadge）
- `ari-core/ari/viz/frontend/src/components/Tree/TreeVisualization.tsx`
- `ari-core/ari/viz/frontend/src/components/Workflow/WorkflowPage.tsx`
- `ari-core/ari/viz/frontend/src/i18n/`

既存 token と common component を棚卸しし、置換可能なものを再利用する。新旧 token を並行追加したまま放置しない。

現状の観測事実（G0 baseline に含める）:

- theme は dark 固定。light/high-contrast、`prefers-color-scheme`、`prefers-reduced-motion` は未対応。
- token 採用は部分的で、status 系 hex（`#3b82f6` 等）が Tree/Idea/DetailPanel に直書き重複し、inline `style={{}}` が広く使われている。
- `index.html` が npm の d3 に加えて CDN `<script>` を二重 load している（offline/CSP の両面で除去対象。task 09 と共有）。
- i18n は自作の flat dict（en/ja/zh、既定 `ja`、`localStorage['ari_lang']`）で、key parity test は既に存在する（`src/i18n/__tests__/parity.test.tsx`）。MonitorPage に旧 dashboard.js 由来の `data-i18n` 属性が残存しており、移行時に除去する。

## Token model

```text
primitive: color.gray.900, space.4, radius.2, font.size.sm
semantic: surface.canvas, text.muted, status.warning, score.penalty
component: button.primary.bg, graph.node.selected, timeline.transition.blocked
```

- component は primitive color を直接参照せず semantic token を使う。
- light/dark/high-contrast は semantic layer の theme として実装する。
- status は色だけで伝えず icon、label、pattern、position を併用する。
- RQGM の accepted/rejected/stale/invalidated/removed は固定 semantic palette を持つ。
- research phase と governance stage は別 palette と凡例を持つ。

## Layout system

- App Shell: header、primary nav、context bar、content、inspector、status tray。
- Workspace: summary rail、main visualization、details inspector の 3-pane を基本とする。
- narrow viewport では inspector を drawer、navigation を modal sheet に変換する。
- data table は column priority を持ち、単純な横スクロールだけに依存しない。
- chart と inspector の selection を URL または shared feature state で同期する。

## Component inventory

### Foundation

- `Stack`、`Inline`、`Grid`、`Panel`、`Divider`、`ScrollableRegion`。
- `Text`、`Heading`、`Code`、`TruncatedText`、`Timestamp`、`NumberValue`。
- `Button`、`IconButton`、`Link`、`Badge`、`StatusBadge`、`Progress`。

### Input and configuration

- accessible `Field`、`Select`、`Combobox`、`Switch`、`Slider`、`SecretField`。
- `FieldProvenance`、`ScopeBadge`、`MutabilityBadge`、`ValidationSummary`。
- `ConfigDiff`、`RawEditor`、`ConflictDialog`、`ConfirmationChallenge`。

### Data and feedback

- virtualized `DataTable`、`KeyValueTable`、`Timeline`、`EventList`。
- `LoadingState`、`EmptyState`、`ErrorState`、`DegradedState`、`StaleDataBanner`。
- `Toast` は補助通知とし、重要な error を toast だけに置かない。

### Visualization

- `VisualizationFrame`、`Legend`、`Tooltip`、`ZoomControls`、`MiniMap`。
- `GraphSelectionModel`、`TimeRangeControl`、`MetricScale`、`ExportImage`。
- feature DTO から共通 `GraphModel` へ変換する adapter contract。

## Accessibility contract

- WCAG 2.2 AA を target とする。
- focus order、visible focus、skip link、landmark、heading hierarchy を shell で保証する。
- tabs は `tablist/tab/tabpanel`、tree は適切な tree/grid semantics を持つ。
- canvas/SVG visualization に同等情報の table/list view を必ず用意する。
- drag-only 操作に keyboard alternative を用意する。
- animation、live update、auto-scroll は pause でき、`prefers-reduced-motion` を尊重する。
- streaming update は screen reader へ過剰 announce せず、summary region を制御する。
- destructive action は focus trap、明示 label、server challenge を備える。

## Internationalization contract

- locale は global provider の単一 state とし、component ごとの local language state を禁止する。
- string concatenation を避け、plural、date、duration、number、currency を locale formatter に委譲する。
- config key、policy hash、artifact path は翻訳せず、説明 label を翻訳する。
- 日本語・英語・中国語の key parity test を維持し、missing key は CI failure とする。
- RQGM terminology glossary を翻訳 resource と docs で共有する。
- long label、CJK wrapping、monospace token、RTL 将来対応を layout fixture で検証する。

## Visualization truth rules

- axis、unit、normalization、policy hash、epoch を常に表示する。
- missing、zero、not applicable、not yet computed を別表現にする。
- comparison 不可な score を同一 connected line に置かない。
- partial/stale data は opacity だけで表現せず label を付ける。
- aggregate から raw event/artifact へ drill-down path を提供する。
- chart export に title、filter、run ID、timestamp、policy hash を含める。

## Migration approach

1. 既存 token と CSS selector の inventory を作る。
2. semantic token を additive に導入する。
3. common state/form/layout component を旧画面でも使える adapter として導入する。
4. shell と新 workspace を新 component で構築する。
5. old inline style/global selector を feature 単位で削除する。
6. unused token と duplicate responsive rule を usage scan 後に削除する。

## Validation

- component interaction unit test。
- axe 相当の automated a11y test と manual screen-reader review。
- keyboard-only journey test。
- light/dark/high-contrast/reduced-motion visual regression。
- 3 locale × narrow/desktop × empty/error/loading/large-data snapshot。
- chart truth-rule contract test と table fallback parity test。

## Completion criteria

- 新 workspace が semantic token と shared primitives だけで構成される。
- P1–P5 state の共通 visual/interaction pattern が catalog 化されている。
- 主要 journey が keyboard と screen reader で完了できる。
- 三言語 parity と representative visual regression が CI gate である。
- RQGM score/status visualization の truth rules が test 化されている。

## Deletion criteria

- component API、token、a11y/i18n rule が frontend reference と catalog に移管済みである。

## Delete-after checklist

- [ ] design-system reference を恒久文書へ移した。
- [ ] visual/a11y/i18n tests が CI で稼働している。
- [ ] duplicate legacy CSS の removal issue が完了している。
- [ ] main merge と CI green を確認した。
- [ ] `INDEX.md` を更新した。

