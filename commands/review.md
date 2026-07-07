# /review — 成果物・出力内容の確認、レビュー

| 項目 | 内容 |
| --- | --- |
| 正準名 | `/review` |
| エイリアス | `/curren-check`（過去互換。受理時に正準名へ正規化し、表記は `command_alias` に保持） |
| 想定 task_type | `coding` / `portfolio` / `avatar_3d` ほか全般 |

## 役割

対象の成果物・出力・変更内容を確認し、要求を満たしているか、破壊的変更や欠陥がないかを評価する。
**対象を変更しない**（修正・整形は `/polish`、方針整理は `/triage` の責務）。

## 入力

- レビュー対象（ファイルパス、URL、PR、または先行タスクの `result`）
- 確認の観点（任意。例:「既存コードに不要な変更が入っていないか」）

## 出力パケットの要件

- `command`: `/review`
- `status`: `done`（問題の有無に関わらずレビュー完了なら done）/ `failed`（レビュー自体が実施不能）
- `summary`: レビュー結果の一言（例:「PR監査が完了しました。」）
- `requirement_summary`: 何をどの観点で確認したか
- `evaluation.confidence`: レビュー判断への自己信頼度
- `evaluation.requires_user_action`: 指摘があり人間判断が必要なら `true`
- 指摘一覧は `detail` または `result`（レポートファイル）に置く

## ハンドオフでの利用

直列チェーンの検証役として使う（例: `/triage → /review → /spec`）。
`must_return_to: true` で呼び出し元へ `report_agent` を返すのが基本形。
