# MACP プロトコル仕様書

MACP（Multi-Agent Command Protocol）パケットの共通仕様。
フィールドごとの詳細な定義は [`notification-packet.md`](./notification-packet.md)、
ハンドオフは [`handoff.md`](./handoff.md) を参照。

> **注意**: MACP は Model Context Protocol（MCP）とは無関係の別プロトコルである。

## 1. 基本原則

1. **すべてのやり取りは 1 つの JSON パケット形式で表す**。人間への通知も AI→AI のハンドオフも同一スキーマ
2. **パケットは自己完結**。受信側が他の文脈なしに「誰が・何を・どうしたか・次に何が必要か」を判断できる
3. **前方互換を壊さない**。未知のフィールド・未知の enum 値は受理して保持する（検証エラーにしない）
4. **サーバー付与情報とエージェント申告情報を区別する**。`event_id` / `received_at` / `mood_computed` はサーバーのみが付与する

## 2. バージョニング

- `protocol`: 固定文字列 `"macp"`
- `version`: semver（現行 `"0.1.0"`）
- メジャーバージョンが一致しないパケットは `422` で拒否する。マイナー/パッチ差は受理する
- フィールド追加はマイナーバージョンアップ、必須フィールドの変更・削除はメジャーバージョンアップ

## 3. トップレベルフィールド一覧

| フィールド | 型 | 必須 | 説明 |
| --- | --- | --- | --- |
| `protocol` | string | ✔ | 固定値 `"macp"` |
| `version` | string | ✔ | semver。現行 `"0.1.0"` |
| `task_id` | string | ✔ | タスク識別子。推奨形式 `task-YYYYMMDD-NNN`。同一 `task_id` への複数パケット送信で状態遷移を表す |
| `task_type` | string | ✔ | [§6](#6-task_type) 参照。未知値も受理 |
| `intent` | string | ✔ | [§4](#4-intent-一覧) 参照 |
| `from` | object | ✔ | 送信元。`{agent_id: string(必須), agent_role: string?}` |
| `to` | object | – | 宛先。`{type: "user"\|"agent"\|"broadcast", target: string?}`。省略時 `{"type": "broadcast"}` |
| `command` | string | – | 実行したコマンドの**正準名**（[§5](#5-command-一覧) 参照） |
| `command_alias` | string | – | 入力時の表記（エイリアス）。例 `/vega-spec` |
| `status` | string | ✔ | [§7](#7-status-一覧) 参照 |
| `priority` | string | – | `low` / `normal` / `high`。省略時 `normal` |
| `summary` | string | ✔ | 機械的な要約（1〜2文。スマホ通知の1行目に使われる想定） |
| `requirement_summary` | string | – | 「何を要求され、どこまで満たしたか」の要約 |
| `agent_message` | string | – | 人格ごとの通知文。欠落時 UI は `summary` にフォールバック |
| `detail` | string | – | 詳細説明（長文可） |
| `result` | object | – | 成果物参照。[`notification-packet.md`](./notification-packet.md) §3 |
| `evaluation` | object | – | 信頼度・要求充足度・mood 等。同 §4 |
| `actions` | array | – | 受信側に提示するアクション。同 §5 |
| `handoff` | object | △ | `intent: "handoff_agent"` のとき**必須**。[`handoff.md`](./handoff.md) |
| `created_at` | string | ✔ | ISO 8601（タイムゾーン付き）。例 `2026-07-07T06:00:00+09:00` |

### サーバー付与フィールド（クライアントは送信しない）

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `event_id` | integer | SQLite の単調増加 ID。SSE の `id:` に使用 |
| `received_at` | string | サーバー受信時刻（ISO 8601） |
| `mood_computed` | string | サーバー導出の mood（導出規則は `notification-packet.md` §6） |

クライアントがこれらを送信してきた場合、サーバーは無視して自身の値で上書きする。

## 4. `intent` 一覧

| intent | 意味 | 主な宛先 |
| --- | --- | --- |
| `notify_user` | 人間へ通知する | `to.type = "user"` |
| `handoff_agent` | 別 AI エージェントへ処理を引き継ぐ | `to.type = "agent"` |
| `report_agent` | 呼び出し元 AI へ結果を返す | `to.type = "agent"` |
| `log_only` | 通知せずログだけ残す（SSE 配信はするが、通知クライアントは表示を抑制してよい） | 任意 |
| `need_review` | 人間またはレビュー AI による確認が必要 | `to.type = "user"` または `"agent"` |

## 5. `command` 一覧

**汎用名を正準（canonical）**とし、旧人格コマンド名はエイリアスとして解決する。
パケットの `command` には正準名を格納し、入力時の表記は `command_alias` に保持する。

| 正準名 | エイリアス | 役割 | 定義 |
| --- | --- | --- | --- |
| `/review` | `/curren-check` | 成果物・出力内容の確認、レビュー | [`commands/review.md`](../commands/review.md) |
| `/polish` | `/curren-polish` | 文章・仕様・出力内容の整形、改善 | [`commands/polish.md`](../commands/polish.md) |
| `/triage` | `/vega-triage` | 問題の分類、優先度付け、対応方針整理 | [`commands/triage.md`](../commands/triage.md) |
| `/spec` | `/vega-spec` | 要件定義、仕様書化、実装指示書化 | [`commands/spec.md`](../commands/spec.md) |

- サーバーはエイリアスを受理した場合、正準名に正規化して `command` に格納し、受理した表記を `command_alias` に移す
- エイリアス表は将来コマンド追加時にもこの表を正とする
- コマンドは人格エージェント専用ではなく、無人格サブエージェントにも割り当て可能

## 6. `task_type`

初期値: `portfolio` / `coding` / `avatar_3d`
予約済み（将来追加）: `research` / `document` / `slides` / `agent_handoff` / `notification_test` / `maintenance`

未知の `task_type` は**受理する**（警告ログのみ）。UI はそのまま表示する。

## 7. `status` 一覧

| status | 意味 | 送信者 |
| --- | --- | --- |
| `queued` | 登録済み、未処理 | エージェント |
| `running` | 処理中 | エージェント |
| `done` | 完了 | エージェント |
| `failed` | 失敗 | エージェント |
| `blocked` | 外部要因で停止 | エージェント |
| `need_review` | 人間確認待ち | エージェント |
| `acknowledged` | ユーザー確認済み | **サーバーのみ**（`POST /api/tasks/{id}/ack` で遷移） |

状態遷移の目安:

```text
queued → running → done ────────────┐
                 → failed ──────────┤→ acknowledged（ack はいずれの終端状態からも可能）
                 → blocked ─────────┤
                 → need_review ─────┘
```

同一 `task_id` に対して複数パケットを送ることで遷移を表す（`running` → `done` など）。
サーバーは `tasks` テーブルに最新状態を保持し、全パケットを `events` に残す。

## 8. validation ルール

サーバー（`schemas.py` / pydantic）は以下を検証する。

1. **必須フィールド**: §3 の必須列（✔）が揃っていること
2. **型と enum**: `intent` / `status` / `priority` / `to.type` は定義済みの値のみ。`task_type` と `mood` は未知値も受理
3. **バージョン**: `protocol == "macp"` かつメジャーバージョン一致
4. **数値範囲**: `evaluation.confidence` / `evaluation.requirement_satisfaction` は 0.0–1.0
5. **条件付き必須**: `intent == "handoff_agent"` なら `handoff` オブジェクト必須（`handoff.md` §3 の必須フィールドを含む）
6. **日時**: `created_at` はタイムゾーン付き ISO 8601
7. **未知フィールド**: エラーにせず保持する（`model_config = ConfigDict(extra="allow")` 相当）
8. **サーバー付与フィールド**: クライアントから送られてきた場合は破棄して上書き

検証エラーは HTTP `422` で、どのフィールドが違反したかを含むエラー応答を返す（形式は [`transport.md`](./transport.md) §8）。

## 9. サンプル JSON

実ファイルとして [`examples/`](../examples/) に置く。テスト（`tests/test_schema.py`）はこれらを直接読み込んで検証する。

| ファイル | 内容 |
| --- | --- |
| [`notify_done.json`](../examples/notify_done.json) | 完了通知（`intent: notify_user`, `status: done`） |
| [`notify_failed.json`](../examples/notify_failed.json) | 失敗通知（`status: failed`） |
| [`notify_need_review.json`](../examples/notify_need_review.json) | 要確認通知（`intent: need_review`） |
| [`handoff_agent.json`](../examples/handoff_agent.json) | AI→AI ハンドオフ（`intent: handoff_agent`） |
| [`report_agent.json`](../examples/report_agent.json) | 呼び出し元への結果返却（`intent: report_agent`） |
