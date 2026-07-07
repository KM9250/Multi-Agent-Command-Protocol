# Codex 向け Phase 1 開発指示書 — MACP notify server 最小実装

本書は Phase 1（サーバー最小実装）の**実行用指示書**である。本書単体で着手できるよう、
実装に必要な仕様は本文に展開してある。ただし**仕様の正は `docs/` 各書**であり、
矛盾を見つけた場合は docs を優先し、本書の該当箇所を修正すること
（全体像は [`codex-instruction.md`](./codex-instruction.md)、プロトコル詳細は
[`protocol.md`](./protocol.md) / [`notification-packet.md`](./notification-packet.md)、
サーバー仕様は [`transport.md`](./transport.md)）。

## 1. スコープ

### やること（Phase 1）

1. `server/` 一式（`app.py` / `schemas.py` / `store.py` / `event_bus.py`）
2. `POST /api/notify` — 検証・正規化・`mood_computed` 導出・保存
3. `POST /api/handoff` — 検証・記録のみ（実行制御なし）
4. `GET /api/tasks` / `GET /api/tasks/{task_id}` / `GET /api/health`
5. SQLite（events / tasks / handoffs）+ JSONL 監査ログ
6. トークン認証（設定時は GET 系も保護）・CORS
7. JSON Schema / TypeScript 型定義の生成・配布（`schema/`）
8. テスト（`tests/test_schema.py` / `tests/test_notify_api.py`）
9. `requirements.txt` / `server/README.md` / `.gitignore`

### やらないこと（後続 Phase。実装しない）

- `GET /api/stream`（SSE）、Web UI、`GET /api/artifacts/{task_id}` — Phase 2
- Windows 通知クライアント — Phase 2.5
- `POST /api/tasks/{id}/ack` / `POST /api/tasks/{id}/retry` — Phase 3
  （`store.py` に `ack()` / `mark_retry()` の**未実装スタブ**（`NotImplementedError`）だけ置いてよい）
- ハンドオフの hop 検査・confidence ゲート・タイムアウト — Phase 5
- Android・FCM・HTTPS 化・ユーザー管理・SQLite 以外のストレージ

### 制約

- Python 3.11+、Windows 上で `uvicorn` 直接起動できること
- 依存は `fastapi` / `uvicorn` / `pydantic`（v2）+ テスト用 `pytest` / `httpx` のみ
- **既存ファイル（docs / examples / commands / README / LICENSE）を変更・削除しない**
- サーバーは AI タスクを実行しない
- パケット仕様を変えたくなったら実装で吸収せず、先に `docs/protocol.md` の変更を提案する

## 2. 成果物のファイル構成

```text
multi-agent-command-protocol/
├─ requirements.txt
├─ .gitignore                 … data/, __pycache__/, .venv/, *.sqlite3 など
├─ server/
│  ├─ __init__.py
│  ├─ app.py                  … FastAPI 本体・ルーティング・認証/CORS・エラーハンドラ
│  ├─ schemas.py              … pydantic モデル・正規化・mood 導出
│  ├─ store.py                … SQLite + JSONL
│  ├─ event_bus.py            … in-process 購読（Phase 2 の SSE が使う骨格）
│  ├─ config.py               … 環境変数の読み込み（1ファイルにまとめる）
│  └─ README.md               … 起動手順・環境変数・curl 例
├─ schema/
│  ├─ macp-packet.schema.json … 生成物（コミットする）
│  └─ macp.d.ts               … 手書きの TypeScript 型定義
├─ scripts/
│  └─ generate_schema.py      … pydantic モデル → JSON Schema 生成
└─ tests/
   ├─ test_schema.py
   └─ test_notify_api.py
```

## 3. 設定（`server/config.py`）

環境変数で設定する（Phase 1 で使うもののみ）。

| 環境変数 | 既定値 | 説明 |
| --- | --- | --- |
| `MACP_HOST` / `MACP_PORT` | `127.0.0.1` / `8765` | バインド先 |
| `MACP_DB_PATH` | `./data/macp.sqlite3` | SQLite ファイル（ディレクトリは自動作成） |
| `MACP_JSONL_PATH` | `./data/audit.jsonl` | 監査ログ。空文字で無効 |
| `MACP_TOKEN` | 未設定 | 未設定なら認証無効。`0.0.0.0` バインド + 未設定時は起動時に WARNING |
| `MACP_CORS_ORIGINS` | `http://localhost:3000` | カンマ区切り |

## 4. `schemas.py` の仕様

### 4.1 モデル定義

pydantic v2 で `MacpPacket` と下位モデル（`AgentRef` / `Destination` / `ResultRef` / `Evaluation` / `ActionItem` / `Handoff`）を定義する。

- `model_config = ConfigDict(populate_by_name=True, extra="allow")` — **未知フィールドは保持**
- **`from` は Python 予約語**のため `from_: AgentRef = Field(alias="from")`。
  シリアライズは常に `by_alias=True` で **JSON キーは `from` のまま維持**する
- 必須: `protocol` / `version` / `task_id` / `task_type` / `intent` / `from` / `status` / `summary` / `created_at`
- enum の扱い（`protocol.md` §8）:
  - **未知値を 422 で拒否**: `intent`（`notify_user` / `handoff_agent` / `report_agent` / `log_only` / `need_review`）、
    `status`（`queued` / `running` / `done` / `failed` / `blocked` / `need_review`）、
    `priority`（`low` / `normal` / `high`）、`to.type`（`user` / `agent` / `broadcast`）
  - **未知値を受理（警告ログのみ）**: `task_type` / `evaluation.mood` / `actions[].action_type`（str 型として受ける）
- 範囲: `evaluation.confidence` / `evaluation.requirement_satisfaction` は 0.0–1.0
- `protocol == "macp"`、`version` はメジャー 0 のみ受理（`0.x.y` 以外は 422）
- `created_at` はタイムゾーン付き ISO 8601（naive datetime は 422）
- `intent == "handoff_agent"` のとき `handoff` 必須。`handoff` の必須フィールド:
  `handoff_id` / `requested_command` / `reason` / `hop` / `max_hops`（`must_return_to` が true（既定）なら `return_to` も必須）
- クライアントが `event_id` / `received_at` / `mood_computed` を送ってきたら**破棄して上書き**

### 4.2 正規化（`normalize_packet(packet) -> dict`）

1. コマンドのエイリアス解決（下表）。エイリアスで来たら `command` を正準名にし、受理した表記を `command_alias` へ

   | エイリアス | 正準名 |
   | --- | --- |
   | `/curren-check` | `/review` |
   | `/curren-polish` | `/polish` |
   | `/vega-triage` | `/triage` |
   | `/vega-spec` | `/spec` |

2. 既定値の充足: `to` 省略時 `{"type": "broadcast"}`、`priority` 省略時 `"normal"`
3. `received_at`（サーバー現在時刻、ISO 8601）を付与
4. `mood_computed` を導出して付与（下記）

### 4.3 `mood_computed` 導出（純関数 `compute_mood(packet) -> str`）

上から順に評価し、最初に一致した行を採用（しきい値は config で変更可能、既定は下表）:

| # | 条件 | 結果 |
| --- | --- | --- |
| 1 | `status == "failed"` | `bad` |
| 2 | `status == "blocked"` | `blocked` |
| 3 | `status ∈ {"queued", "running"}` | `unknown` |
| 4 | `evaluation` 欠落 or `confidence` 未設定 | `unknown` |
| 5 | `confidence < 0.5` or `requirement_satisfaction < 0.5` | `bad` |
| 6 | `status == "need_review"` or `requires_user_action == true` | `caution` |
| 7 | `confidence >= 0.75` and `requirement_satisfaction >= 0.8` | `good` |
| 8 | それ以外 | `caution` |

※ 規則 5・7 で `requirement_satisfaction` が未設定の場合はその比較をスキップする（confidence のみで判定）。

## 5. `store.py` の仕様

### 5.1 DDL（`transport.md` §6 と同一）

```sql
CREATE TABLE IF NOT EXISTS events (
  event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id    TEXT NOT NULL,
  event_type TEXT NOT NULL,            -- 'packet' | 'ack' | 'retry_requested'
  payload    TEXT NOT NULL,            -- packet: 正規化済みパケット JSON / ack・retry_requested: server event envelope JSON
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);

CREATE TABLE IF NOT EXISTS tasks (
  task_id            TEXT PRIMARY KEY,
  task_type          TEXT,
  intent             TEXT,
  command            TEXT,
  status             TEXT NOT NULL,
  priority           TEXT,
  summary            TEXT,
  agent_id           TEXT,
  mood               TEXT,
  mood_computed      TEXT,
  requires_user_action INTEGER DEFAULT 0,
  latest_packet      TEXT NOT NULL,
  acknowledged       INTEGER NOT NULL DEFAULT 0,
  acknowledged_at    TEXT,
  retry_requested_at TEXT,
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS handoffs (
  handoff_id        TEXT PRIMARY KEY,
  task_id           TEXT NOT NULL,
  requested_command TEXT,
  from_agent        TEXT,
  to_agent          TEXT,
  return_to         TEXT,
  hop               INTEGER,
  max_hops          INTEGER,
  state             TEXT NOT NULL,     -- Phase 1 では常に 'pending'
  payload           TEXT NOT NULL,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);
```

### 5.2 インターフェース

SQLite 以外へ差し替え可能なよう、SQL はこのモジュールに閉じ込める。

```python
class Store:
    def __init__(self, db_path: str, jsonl_path: str | None): ...
    def append_packet(self, normalized: dict, raw: dict) -> int:
        """events 追記 + tasks upsert +（handoff_agent なら）handoffs upsert を
        単一トランザクションで行い、event_id を返す。
        raw（正規化前パケット）は JSONL に追記（失敗は WARNING のみ、処理継続）。"""
    def get_events_after(self, last_event_id: int, limit: int = 500) -> list[dict]: ...
    def list_tasks(self, *, status=None, task_type=None, intent=None,
                   acknowledged: bool | None = None,
                   limit: int = 50, offset: int = 0) -> list[dict]:
        """tasks を updated_at 降順で返す（latest_packet を展開し、
        acknowledged / acknowledged_at を含める）。"""
    def get_task(self, task_id: str) -> dict | None:
        """最新状態 + そのタスクの全イベント（時系列）+ 関連ハンドオフ。"""
    def ack(self, task_id: str): raise NotImplementedError      # Phase 3
    def mark_retry(self, task_id: str): raise NotImplementedError  # Phase 3
```

- tasks upsert 時、`acknowledged` / `acknowledged_at` / `retry_requested_at` は**上書きしない**（既読状態はパケット再送で消えない）
- 接続は `sqlite3`（標準ライブラリ）。uvicorn は単一プロセスなので `check_same_thread=False` + 直列化ロック（`threading.Lock`）で十分

## 6. `event_bus.py` の仕様（骨格のみ）

Phase 2 の SSE が使う。Phase 1 では `POST /api/notify` / `POST /api/handoff` の保存成功後に `publish()` を呼ぶところまで実装する（購読者ゼロなら何もしない）。

```python
class EventBus:
    def subscribe(self) -> asyncio.Queue: ...      # maxsize 有限（例 256）
    def unsubscribe(self, q: asyncio.Queue): ...
    async def publish(self, event: dict): ...      # 満杯の購読者はドロップ対象として unsubscribe
```

## 7. `app.py` の仕様

### 7.1 エンドポイント

| メソッド/パス | 認証※ | 応答 |
| --- | --- | --- |
| `POST /api/notify` | ✔ | `201 {"ok": true, "event_id": N, "task_id": "...", "mood_computed": "..."}` |
| `POST /api/handoff` | ✔ | `201 {"ok": true, "event_id": N, "handoff_id": "...", "state": "pending"}`。`intent != "handoff_agent"` は 422 |
| `GET /api/tasks` | ✔ | クエリ: `status` / `task_type` / `intent` / `acknowledged` / `limit` / `offset` → `{"ok": true, "tasks": [...]}` |
| `GET /api/tasks/{task_id}` | ✔ | `{"ok": true, "task": {...}, "events": [...], "handoffs": [...]}`。なければ 404 |
| `GET /api/health` | – | `200 {"status": "ok"}` **のみ**（バージョン等の詳細は返さない） |

※ `MACP_TOKEN` 設定時のみ要求: `Authorization: Bearer <token>` または `X-MACP-Token: <token>`。未設定なら全て認証なし。

### 7.2 エラー形式（`transport.md` §8）

```json
{ "ok": false, "error": { "code": "validation_error", "message": "...", "fields": ["evaluation.confidence"] } }
```

- 401 `unauthorized` / 404 `not_found` / 422 `validation_error` / 500 `internal_error`
- pydantic の `ValidationError` は 422 に変換し、違反フィールドを `fields` に列挙
- 500 で内部情報（スタックトレース・パス）を応答に含めない（ログのみ）

### 7.3 CORS・ログ

- `CORSMiddleware` で `MACP_CORS_ORIGINS` を許可（メソッド: GET/POST、ヘッダ: Authorization / X-MACP-Token / Content-Type）
- `logging`: コンソール + `./data/server.log`（`RotatingFileHandler`）
  - INFO: 受信（task_id / intent / status / mood_computed）
  - WARNING: 未知 task_type・未知 mood・JSONL 失敗・トークン未設定での `0.0.0.0` バインド
  - ERROR: 想定外例外（スタックトレース付き）
  - `detail` 等の本文全文はログに書かない（task_id と summary まで）

## 8. スキーマ配布（`schema/`）

1. `scripts/generate_schema.py`: `MacpPacket.model_json_schema(by_alias=True)` を
   `schema/macp-packet.schema.json` に書き出す（整形 JSON、キーは `from` になっていること）
2. `schema/macp.d.ts`: `protocol.md` §3 に対応する TypeScript 型定義を**手書き**する
   （`MacpPacket` / `Intent` / `Status` / `Priority` / `Mood` / `Handoff` など。
   未知 enum を許容するフィールドは `KnownX | (string & {})` パターンで表現）
3. 生成物はコミットする。`tests/test_schema.py` に「再生成して既存ファイルと一致すること」の
   ドリフト検査を入れる

## 9. テスト仕様

### `tests/test_schema.py`

1. `examples/*.json` **全 5 件**がパース・正規化に成功する
2. 必須欠落（`summary` なし）→ ValidationError
3. `evaluation.confidence: 1.5` → ValidationError
4. `intent: "unknown_intent"` → ValidationError／`task_type: "space_travel"` → 受理／`evaluation.mood: "great"` → 受理
5. `intent: "handoff_agent"` で `handoff` なし → ValidationError
6. エイリアス正規化: 入力 `command: "/vega-spec"` → `command == "/spec"`, `command_alias == "/vega-spec"`
7. `compute_mood`: `failed`→`bad`、`blocked`→`blocked`、`running`→`unknown`、
   evaluation なし→`unknown`、`confidence 0.3`→`bad`、`need_review`→`caution`、
   `done + 0.86/0.9 + requires_user_action false`→`good`、`done + 0.6/0.6`→`caution`
8. クライアント送信の `event_id` / `mood_computed` が破棄されること
9. スキーマドリフト検査（§8-3）

### `tests/test_notify_api.py`（FastAPI `TestClient`、DB は tmp_path）

1. `examples/notify_done.json` を POST → 201 → `GET /api/tasks` に 1 件 → `GET /api/tasks/{id}` で詳細一致
2. 同一 `task_id` に `status: running` → `done` の 2 パケット → tasks は `done`、events は 2 件
3. 不正パケット → 422 + エラー形式（`ok: false`, `error.code == "validation_error"`, `fields` あり）
4. `MACP_TOKEN` 設定時: トークンなし POST → 401、`GET /api/tasks` も 401、正しいトークン → 成功、
   `GET /api/health` はトークンなしで 200
5. `POST /api/handoff` に `examples/handoff_agent.json` → 201、`GET /api/tasks/{id}` の `handoffs` に `state: "pending"`
6. JSONL に生パケットが 1 行追記されていること
7. `GET /api/tasks?status=done&acknowledged=false` などフィルタの動作

## 10. 受け入れ基準（完了の定義）

```bash
pip install -r requirements.txt
pytest                                    # 全テスト緑
uvicorn server.app:app --port 8765        # 起動できる

curl -s http://127.0.0.1:8765/api/health
# → {"status":"ok"}

curl -s -X POST http://127.0.0.1:8765/api/notify \
  -H "Content-Type: application/json" -d @examples/notify_done.json
# → 201 {"ok":true,"event_id":1,"task_id":"task-20260707-001","mood_computed":"caution"}
#   ※ notify_done.json は requires_user_action=true のため導出は caution（申告 mood は good のまま併記される）

curl -s http://127.0.0.1:8765/api/tasks | python -m json.tool   # 登録済みタスクが見える
python scripts/generate_schema.py         # schema/ が最新（git diff なし）
```

- Windows（PowerShell）でも同等の手順が通ること（パス区切り・`data/` 自動作成に注意）
- `ruff check`（導入しない場合は `python -m compileall server tests scripts`）が通ること

## 11. 完了報告

実装完了時、以下を含む報告を作成すること。

1. 実装したファイル一覧と各テストの結果
2. 仕様（docs/）との差異・判断に迷った点（あれば必ず列挙）
3. 受け入れ基準の実行ログ（curl の実出力）
4. Phase 2（SSE / Web UI）に向けた引き継ぎメモ（event_bus の使い方、store の拡張点）
