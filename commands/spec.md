# /spec — 要件定義、仕様書化、実装指示書化

| 項目 | 内容 |
| --- | --- |
| 正準名 | `/spec` |
| エイリアス | `/vega-spec`（過去互換。受理時に正準名へ正規化し、表記は `command_alias` に保持） |
| 想定 task_type | `coding` / `document` ほか |

## 役割

整理済みの情報（`/triage` の分類結果、`/review` の指摘など）をもとに、
要件定義書・仕様書・実装指示書（Codex 等へ渡せる粒度）を作成する。
チェーンの**終端**になることが多く、完了時は人間への通知（`notify_user`）で締める。

## 入力

- 仕様化の対象と前提資料（先行タスクの `result`、既存 docs）
- 出力形式の指定（任意。例:「Codex にそのまま渡せる実装指示書」）

## 出力パケットの要件

- `command`: `/spec`
- `status`: `done` / `need_review`（設計判断が残る場合）
- `result.path` または `result.url`: 作成した仕様書・指示書
- `requirement_summary`: どの要求をどこまで仕様に落としたか
- `evaluation.requires_user_action`: 人間の承認が必要な設計判断が残るなら `true`
- 実装へ渡す場合は `actions` に `copy_prompt`（PC）や成果物リンクを含める

## ハンドオフでの利用

`confidence_gate` 未達（既定 0.75 未満）の場合は仕様書を確定させず、
`need_review` として人間に差し戻すこと（`handoff.md` §4.2）。
