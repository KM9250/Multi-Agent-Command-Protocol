# MACP AI→AI ハンドオフ仕様

AI エージェント間のタスク引き継ぎ（handoff）の仕様。
**仕様は Phase 0 で固定し、実行制御の実装は Phase 5**。ただし `POST /api/handoff` は Phase 1 から「受理して記録するだけ」の形で先置きし、スキーマを早期に実運用へ晒す。

## 1. 想定する処理形態

小規模な直列処理（2〜3 個体）を想定する。

```text
ユーザー依頼
  ↓
Vega: 問題分類 /triage        （intent: handoff_agent → curren へ）
  ↓
Curren: 出力確認 /review      （intent: report_agent → vega へ返却）
  ↓
Vega: 仕様書化 /spec
  ↓
ユーザーへ通知                 （intent: notify_user）
```

- AI 同士の処理も、人間通知と**同じ MACP パケット形式**で扱う
- ハンドオフの途中経過もすべて `events` に記録され、Web UI のハンドオフ履歴で追跡できる

## 2. パケット形式

`intent: "handoff_agent"` のパケットは `handoff` オブジェクトを**必須**で持つ。

```json
{
  "protocol": "macp",
  "version": "0.1.0",
  "task_id": "task-20260707-002",
  "task_type": "coding",
  "intent": "handoff_agent",
  "from": { "agent_id": "vega", "agent_role": "triage" },
  "to": { "type": "agent", "target": "curren" },
  "status": "queued",
  "summary": "仕様書化前のレビューを依頼します。",
  "handoff": {
    "handoff_id": "handoff-001",
    "requested_command": "/review",
    "reason": "仕様書化前にレビューが必要なため",
    "priority": "normal",
    "return_to": "vega",
    "return_intent": "report_agent",
    "return_format": "json",
    "hop": 1,
    "max_hops": 3,
    "confidence_gate": 0.75,
    "must_return_to": true
  },
  "created_at": "2026-07-07T06:10:00+09:00"
}
```

## 3. `handoff` フィールド定義

| フィールド | 型 | 必須 | 説明 |
| --- | --- | --- | --- |
| `handoff_id` | string | ✔ | ハンドオフ識別子。チェーン内で一意（推奨形式 `handoff-NNN` または UUID） |
| `requested_command` | string | ✔ | 依頼するコマンドの**正準名**（`/review` 等。エイリアスは正規化される） |
| `reason` | string | ✔ | 引き継ぎ理由。受け手が判断に使う |
| `priority` | string | – | `low` / `normal` / `high`。省略時 `normal` |
| `return_to` | string | △ | 結果の返却先エージェント ID。`must_return_to: true` のとき必須 |
| `return_intent` | string | – | 返却時に使う intent。既定 `report_agent` |
| `return_format` | string | – | 返却形式のヒント。既定 `json` |
| `hop` | integer | ✔ | 現在のホップ数。チェーンの最初のハンドオフで `1` |
| `max_hops` | integer | ✔ | 許容最大ホップ数。既定推奨 `3` |
| `confidence_gate` | number | – | 0.0–1.0。結果の `confidence` がこの値未満なら人間確認へ差し戻す。既定 `0.75` |
| `must_return_to` | boolean | – | `true` なら受け手は必ず `return_to` へ結果を返す。既定 `true` |

## 4. 実行ルール（Phase 5 で実装）

### 4.1 ループ防止

1. ハンドオフを受けたエージェントがさらにハンドオフする場合、`hop` を +1 して引き継ぐ
2. `hop > max_hops` となるハンドオフをサーバーは**拒否**し、`need_review` イベントとして人間に通知する
3. 同一 `task_id` チェーン内で同じ `agent_id` に 2 回以上戻る循環を検出した場合も同様に人間へ差し戻す

### 4.2 confidence ゲート

- 受け手エージェントの処理結果（`report_agent` パケット）の `evaluation.confidence` が `confidence_gate` 未満の場合、`return_to` へ返す代わりに **`intent: need_review` として人間に差し戻す**
- 差し戻しパケットの `summary` には「confidence ゲート未達」であることを明記する

### 4.3 返却制御

- `must_return_to: true`: 受け手は処理完了時に必ず `return_to` 宛の `report_agent` パケットを送る
- `must_return_to: false`: 受け手は結果を直接ユーザー通知（`notify_user`）で終わらせてよい

### 4.4 途中経過のログ

- ハンドオフの登録・受理・返却・差し戻しはすべて `events` テーブルに記録される
- `handoffs` テーブルがチェーンの現在状態を保持する（[`transport.md`](./transport.md) §6）

## 5. ハンドオフのライフサイクル

```text
pending    … POST /api/handoff で登録された直後
accepted   … 受け手エージェントが処理を開始（running パケットの受信で遷移）
returned   … return_to への report_agent パケットを受信して完了
escalated  … max_hops 超過 / confidence_gate 未達で人間に差し戻し
expired    … 一定時間応答がない（タイムアウトは Phase 5 で設定可能に。既定 24h）
```

## 6. Phase 1 での挙動（記録のみ）

Phase 1 の `POST /api/handoff` は以下だけを行う。

1. パケットを検証する（`handoff` 必須フィールドを含む）
2. `events` / `handoffs` / JSONL に記録する（状態は `pending` のまま）
3. SSE で配信する（購読中のエージェント・UI が見られるようにする）

hop 検査・confidence ゲート・タイムアウトなどの実行制御は行わない。
受け手エージェントへの実際の伝達は、当面は人間がオーケストレーションする
（エージェントを起動してパケットを渡す）運用とし、Phase 5 で自動化を検討する。

## 7. サンプル

- ハンドオフ登録: [`examples/handoff_agent.json`](../examples/handoff_agent.json)
- 結果返却: [`examples/report_agent.json`](../examples/report_agent.json)
