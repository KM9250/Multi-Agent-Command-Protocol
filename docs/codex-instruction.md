# Codex 向け実装指示書（Phase 1–2.5 全体像）

MACP notify server と最小クライアントの実装指示。本書だけで着手できるよう書くが、
仕様の正は `docs/` 各書とし、矛盾があれば **docs 側を優先**して本書を修正すること。

> **Phase 1 の実行用指示書は [`codex-phase1-instruction.md`](./codex-phase1-instruction.md) を使うこと。**
> 本書は Phase 1–2.5 の全体像と Phase 2 以降の参照用。

## 0. 前提・制約

- 対象リポジトリ: `Multi-Agent-Command-Protocol`（現状 docs / examples / commands のみ。**既存ファイルを壊さない**。空リポジトリ状態からでも同じ手順で開始できる）
- 言語/環境: Python 3.11+、Windows 上で `uvicorn` 直接起動
- 依存は最小限: `fastapi` / `uvicorn` / `pydantic`（+ クライアント用に `httpx` / `winotify`）
- **プロトコル仕様と実装を分離する**: パケットの定義変更は必ず `docs/protocol.md` 側を先に更新する
- サーバーは AI タスクを実行しない（retry は「要求の記録・配信」のみ）
- Android には手を出さない（Phase 4）。Web UI はビルド工程なしの静的 1 ファイル

## 1. 作るもの（スコープ）

| Phase | 成果物 |
| --- | --- |
| 1 | `server/`（app.py / schemas.py / store.py / event_bus.py）、`tests/`、`requirements.txt` |
| 2 | `GET /api/stream`（SSE 再送付き）、`clients/web/index.html`、`GET /api/artifacts/{task_id}` |
| 2.5 | `clients/windows/notify_receiver.py` |

ディレクトリ構成は `README.md` の構成案に従う。

## 2. 実装仕様の参照先

| 実装対象 | 仕様 |
| --- | --- |
| パケット検証・正規化（エイリアス→正準名、mood_computed 導出、サーバー付与フィールド） | `protocol.md` §3–§8、`notification-packet.md` §6 |
| API（パス・入出力・エラー形式・認証・CORS） | `transport.md` §2, §8, §9 |
| SSE（イベント種別・id・ハートビート・**再接続再送アルゴリズム**） | `transport.md` §3–§5 ※手順順序（購読開始→backlog 送信→重複排除）を厳守 |
| SQLite スキーマ・トランザクション・JSONL | `transport.md` §6 |
| 成果物配信（許可リスト・パストラバーサル防止） | `transport.md` §7 |
| Web UI の表示項目・フォールバック規則 | `clients.md` §2、`notification-packet.md` §2–§3 |
| Windows クライアント（カーソル永続化・バックオフ・表示フィルタ） | `clients.md` §3 |

## 3. 実装順序と受け入れ基準

### Step 1: schemas.py + テスト

- pydantic v2 で `MacpPacket` を定義（`extra="allow"`、enum は `protocol.md` §4–§7。未知 enum の許容は `task_type` / `evaluation.mood` / `actions[].action_type` のみ、`intent` / `status` / `priority` / `to.type` は拒否）
- **`from` は Python の予約語**のため、`from_: AgentRef = Field(alias="from")` とし、
  `model_config = ConfigDict(populate_by_name=True, extra="allow")`、シリアライズは `by_alias=True` で
  **JSON キーは `from` のまま維持**する
- エイリアス正規化（`/curren-check`→`/review` 等 4 対）と `mood_computed` 導出を純関数で実装
- `tests/test_schema.py`: **`examples/*.json` 全 5 件をパースして通ること**、必須欠落・範囲外 confidence・
  `handoff_agent` で `handoff` 欠落、の 3 系統が `ValidationError` になること

### Step 2: store.py + event_bus.py

- `transport.md` §6 の DDL。`append_event` は events 追記 + tasks upsert（+ handoffs upsert）を単一トランザクションで
- `get_events_after(last_event_id)` / `list_tasks(filters)` / `get_task(task_id)` / `ack` / `mark_retry`
- event_bus: `subscribe()/unsubscribe()/publish()`、購読者ごとの `asyncio.Queue`（maxsize 有限、満杯なら切断）

### Step 3: app.py（Phase 1 エンドポイント）

- `POST /api/notify` / `POST /api/handoff` / `GET /api/tasks` / `GET /api/tasks/{id}` / `GET /api/health`
- トークン認証（`MACP_TOKEN` 未設定なら無効。設定時は POST 全部に加え GET /api/tasks 系・artifacts も保護。`transport.md` §9）、CORS（`MACP_CORS_ORIGINS`）
- `tests/test_notify_api.py`: FastAPI `TestClient` で正常登録 → 一覧取得 → 詳細取得、401/422 系

**Phase 1 受け入れ**: `uvicorn server.app:app` 起動後、
`curl -X POST http://127.0.0.1:8765/api/notify -H "Content-Type: application/json" -d @examples/notify_done.json`
が 201 を返し、`/api/tasks` に反映される。`pytest` 緑。

### Step 4: SSE（Phase 2）

- `GET /api/stream`: `transport.md` §5 の手順どおり。`Last-Event-ID` ヘッダ / `?last_event_id=` / `?token=`
- 15 秒ハートビート（`: ping`）
- テスト: 接続 → notify → 受信、`last_event_id` 指定で過去分再送、の 2 ケース（httpx の streaming で可）

### Step 5: Web UI + artifacts（Phase 2）

- `clients/web/index.html` 1 ファイル（fetch + EventSource、フレームワークなし）
- `GET /` で配信。`clients.md` §2.2 の項目、`agent_message`→`summary` フォールバック、
  `result.url` → `/api/artifacts/` → path 表示の優先順位
- 受信した `event_id` を `localStorage` に永続化し、接続時に `?last_event_id=`（+ トークン設定時は `?token=`）を付ける
  （EventSource の自動 `Last-Event-ID` はページ再読み込みをまたがないため必須）
- `GET /api/artifacts/{task_id}`: `MACP_ARTIFACT_ROOTS` 許可リスト検証（`Path.resolve` + `is_relative_to`）

**Phase 2 受け入れ**: ブラウザ 2 枚同時受信。片方をネット切断→復帰で取りこぼしゼロ。

### Step 6: Windows クライアント（Phase 2.5）

- `clients/windows/notify_receiver.py`: `clients.md` §3.2 のとおり
  （httpx streaming で SSE をパース、winotify で toast、`%LOCALAPPDATA%/macp/last_event_id` 永続化、
  2s→4s→8s→最大 60s バックオフ、`log_only`・agent 宛の表示抑制）

**Phase 2.5 受け入れ**: クライアント停止中に notify → 起動で未受信分が toast 表示される。

## 4. やらないこと

- ack / retry エンドポイント（Phase 3。ただし store.py にはメソッドの置き場だけ用意してよい）
- handoff の実行制御（hop 検査・gate・タイムアウト。Phase 5）
- Android・FCM・HTTPS 化・ユーザー管理
- SQLite 以外のストレージ実装（抽象だけ維持）

## 5. 品質基準

- `pytest` で全テスト緑、`ruff`（または最低限 `python -m compileall`）が通る
- 例外時に 500 で内部情報を漏らさない（`transport.md` §8 のエラー形式）
- ログは `transport.md` §10 の粒度。detail 全文をログに書かない
- README（`server/README.md`）に起動手順・環境変数・curl 例を書く
