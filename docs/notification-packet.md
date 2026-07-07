# MACP 通知パケット フィールド辞書

トップレベルの一覧は [`protocol.md`](./protocol.md) §3。本書はネストしたオブジェクトの詳細と、
通知文の分離ルール、`mood` の導出規則を定義する。

## 1. `from` / `to`

```json
"from": { "agent_id": "vega", "agent_role": "spec_writer" },
"to":   { "type": "user", "target": "android" }
```

| フィールド | 必須 | 説明 |
| --- | --- | --- |
| `from.agent_id` | ✔ | 送信元エージェントの識別子。人格名（`vega`）でも機能名（`pr-auditor`）でもよい |
| `from.agent_role` | – | そのタスクにおける役割（`spec_writer` / `reviewer` など） |
| `to.type` | – | `user`（人間宛）/ `agent`（エージェント宛）/ `broadcast`（全購読者宛）。省略時 `broadcast` |
| `to.target` | – | 宛先の絞り込み。`user` なら端末ヒント（`android` / `windows` / `web`）、`agent` ならエージェント ID。通知クライアントは自分宛でない通知の表示を抑制してよい（配信自体は全購読者に行われる） |

## 2. 通知文の 3 分離

スマホ通知で「完了」だけでなく**要件の要約＋人格ごとの通知文**を同時に見たい、という要求に対応するため、通知文を 3 フィールドに分離する。

```json
{
  "summary": "PR監査が完了しました。",
  "requirement_summary": "既存コードに不要な変更が入っていないかを中心に確認。",
  "agent_message": "大きな破壊的変更は見当たりませんが、1点だけ確認推奨です。"
}
```

| フィールド | 性質 | UI での扱い |
| --- | --- | --- |
| `summary` | 機械的な要約。**必須** | 通知の1行目・一覧のタイトル |
| `requirement_summary` | 要求内容と充足範囲の要約。任意 | 通知の2行目・詳細画面 |
| `agent_message` | 人格ごとの通知文。任意 | 通知の本文・詳細画面。**欠落時は `summary` にフォールバック** |

人格文の生成規則・文体はプロトコルの管轄外（各エージェント側の責務）。
無人格エージェントは `agent_message` を省略すればよい。

## 3. `result` — 成果物参照

**PC ローカルで開ける `path` と、スマホ・Web UI から参照できる `url` を明確に分離する。**

```json
"result": {
  "format": "markdown",
  "path": "./outputs/codex_instruction.md",
  "url": null
}
```

| フィールド | 必須 | 説明 |
| --- | --- | --- |
| `format` | – | `markdown` / `text` / `json` / `image` / `binary` など |
| `path` | – | **サーバーホスト PC 上のローカルパス**。PC クライアントの `open_file` アクションでのみ使用。スマホからは開けない |
| `url` | – | **リモート端末から参照可能な URL**。設定されていれば全端末でこちらを優先 |

参照解決の優先順位（UI・クライアント共通）:

1. `result.url` があればそれを開く
2. `url` がなく `path` があり、サーバーの成果物配信（Phase 2 の任意機能 `GET /api/artifacts/{task_id}`）が有効なら、Web UI は `/api/artifacts/{task_id}` へのリンクを表示する
3. どちらも使えなければ `path` を文字列として表示するにとどめる（PC 上で手動で開く）

成果物配信はディレクトリ許可リスト（`MACP_ARTIFACT_ROOTS`）で制限する。詳細は [`transport.md`](./transport.md) §7。

## 4. `evaluation` — 実務的評価

```json
"evaluation": {
  "confidence": 0.86,
  "requirement_satisfaction": 0.9,
  "mood": "good",
  "requires_user_action": true
}
```

| フィールド | 必須 | 範囲 | 説明 |
| --- | --- | --- | --- |
| `confidence` | – | 0.0–1.0 | 出力に対する自己信頼度 |
| `requirement_satisfaction` | – | 0.0–1.0 | 要求をどこまで満たしたか |
| `mood` | – | §6 の enum | **エージェント申告（任意）**。感情ではなく実務的評価 |
| `requires_user_action` | – | bool | 人間の確認・操作が必要か。省略時 `false` |

## 5. `actions` — 次に必要なアクション

```json
"actions": [
  { "label": "内容を確認する", "action_type": "open_file", "target": "./outputs/codex_instruction.md" },
  { "label": "Codexに渡す",   "action_type": "copy_prompt", "target": "./outputs/codex_instruction.md" }
]
```

| action_type | 動作 | 有効な端末 |
| --- | --- | --- |
| `open_file` | `target`（ローカルパス）を開く | **PC のみ** |
| `open_url` | `target`（URL）を開く | 全端末 |
| `copy_prompt` | `target` の内容（ファイルまたは文字列）をクリップボードへ | PC。スマホは Web UI 経由で表示 → 手動コピー |
| `ack` | `POST /api/tasks/{task_id}/ack` を呼ぶ | 全端末 |
| `retry` | `POST /api/tasks/{task_id}/retry` を呼ぶ | 全端末 |

クライアントは未知の `action_type` を無視してよい（表示しない）。

## 6. `mood` と導出規則

### 6.1 enum

| mood | 意味 |
| --- | --- |
| `good` | 要求を概ね満たし、信頼度も十分 |
| `caution` | 成果物はあるが確認が必要 |
| `bad` | 失敗、未完了、信頼度不足 |
| `blocked` | 外部要因で停止 |
| `unknown` | 判定不能 |

### 6.2 導出規則（サーバー実装仕様）

- エージェント申告の `evaluation.mood` は**任意**
- サーバーは受信時に必ず `mood_computed` を以下の規則で導出し、パケットに付与する
- 申告値がない場合、UI は `mood_computed` を表示する
- 申告値があり `mood_computed` と**矛盾する場合は両方を併記**する（例: バッジは申告値、ツールチップ/詳細に `computed: caution`）

導出規則（上から順に評価し、最初に一致した行を採用）:

| # | 条件 | mood_computed |
| --- | --- | --- |
| 1 | `status == "failed"` | `bad` |
| 2 | `status == "blocked"` | `blocked` |
| 3 | `status ∈ {"queued", "running"}` | `unknown`（進行中は判定しない） |
| 4 | `evaluation` が欠落、または `confidence` が未設定 | `unknown` |
| 5 | `confidence < 0.5` または `requirement_satisfaction < 0.5` | `bad` |
| 6 | `status == "need_review"` または `requires_user_action == true` | `caution` |
| 7 | `confidence >= 0.75` かつ `requirement_satisfaction >= 0.8` | `good` |
| 8 | 上記いずれにも該当しない | `caution` |

しきい値（0.5 / 0.75 / 0.8）はサーバー設定で変更可能とし、既定値を上表とする。
ハンドオフの `confidence_gate`（[`handoff.md`](./handoff.md) §4）とは独立のしきい値である。

## 7. 完全なパケット例

```json
{
  "protocol": "macp",
  "version": "0.1.0",
  "task_id": "task-20260707-001",
  "task_type": "coding",
  "intent": "notify_user",
  "from": { "agent_id": "vega", "agent_role": "spec_writer" },
  "to": { "type": "user", "target": "android" },
  "command": "/spec",
  "command_alias": "/vega-spec",
  "status": "done",
  "priority": "normal",
  "summary": "Codex向けの実装指示書を作成しました。",
  "requirement_summary": "既存仕様を壊さず、通知パケットの最小実装とSSE配信を追加する方針で整理。",
  "agent_message": "指示書は最小構成でまとめてあります。Phase 1の範囲だけ先に確認してもらえれば十分です。",
  "detail": "既存仕様を壊さず、通知パケットの最小実装とSSE配信を追加する方針で整理しています。",
  "result": {
    "format": "markdown",
    "path": "./outputs/codex_instruction.md",
    "url": null
  },
  "evaluation": {
    "confidence": 0.86,
    "requirement_satisfaction": 0.9,
    "mood": "good",
    "requires_user_action": true
  },
  "actions": [
    { "label": "内容を確認する", "action_type": "open_file", "target": "./outputs/codex_instruction.md" },
    { "label": "Codexに渡す", "action_type": "copy_prompt", "target": "./outputs/codex_instruction.md" }
  ],
  "created_at": "2026-07-07T06:00:00+09:00"
}
```

その他のサンプルは [`examples/`](../examples/) を参照。
