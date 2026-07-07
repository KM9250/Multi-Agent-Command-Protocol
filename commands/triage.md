# /triage — 問題の分類、優先度付け、対応方針整理

| 項目 | 内容 |
| --- | --- |
| 正準名 | `/triage` |
| エイリアス | `/vega-triage`（過去互換。受理時に正準名へ正規化し、表記は `command_alias` に保持） |
| 想定 task_type | `coding` / `maintenance` / `research` ほか |

## 役割

複数の問題・要望・指摘を分類し、優先度と対応方針を整理する。チェーンの**起点**になることが多い。
実際の修正・仕様化は行わない（後続の `/polish` / `/spec` へハンドオフする）。

## 入力

- 分類対象（issue 一覧、エラー報告、レビュー指摘、雑多なメモなど）
- 判断基準（任意。例:「ユーザー影響順」「実装コスト順」）

## 出力パケットの要件

- `command`: `/triage`
- `status`: `done`
- `summary`: 分類結果の一言（件数と最重要項目）
- `detail` / `result`: 分類表（項目 / 原因グループ / priority / 推奨対応 / 推奨コマンド）
- `priority`: チェーン全体の優先度をここに反映する（high の問題を含むなら high）
- 後続処理が必要なら `intent: handoff_agent` + `handoff.requested_command` で引き継ぐ

## ハンドオフでの利用

典型チェーンの1段目: `/triage`（分類）→ `/review`（検証）→ `/spec`（仕様化）→ ユーザー通知。
`hop: 1` から開始し、`max_hops` は既定 3。
