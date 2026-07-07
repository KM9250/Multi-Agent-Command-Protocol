# MACP サーバー設計書（FastAPI / SSE / 保存・再送）

MACP notify server の設計。実行環境は Python 3.11+ / Windows / uvicorn 直接起動、
依存は FastAPI / uvicorn / pydantic の最小限とする。

## 1. プロセス構成

```text
uvicorn server.app:app --host 0.0.0.0 --port 8765
```

| モジュール | 責務 |
| --- | --- |
| `server/app.py` | ルーティング、SSE 配信、静的配信（Web UI・成果物）、認証・CORS ミドルウェア |
| `server/schemas.py` | pydantic モデル（パケット検証、エイリアス正規化、`mood_computed` 導出） |
| `server/store.py` | SQLite への保存・照会、JSONL 追記。ストレージ差し替え可能な薄い抽象 |
| `server/event_bus.py` | 接続中 SSE クライアントへの in-process ブロードキャスト |

設定は環境変数で行う（`.env` 読み込みは任意）。

| 環境変数 | 既定値 | 説明 |
| --- | --- | --- |
| `MACP_HOST` / `MACP_PORT` | `127.0.0.1` / `8765` | バインド先。LAN 運用時は `0.0.0.0` |
| `MACP_DB_PATH` | `./data/macp.sqlite3` | SQLite ファイル |
| `MACP_JSONL_PATH` | `./data/audit.jsonl` | 監査ログ（空にすると無効） |
| `MACP_TOKEN` | （未設定） | 書き込み系 API の簡易トークン。**未設定なら認証無効（ローカル開発用）。LAN 運用では必須** |
| `MACP_CORS_ORIGINS` | `http://localhost:3000` | CORS 許可オリジン（カンマ区切り） |
| `MACP_ARTIFACT_ROOTS` | （未設定） | 成果物配信を許可するディレクトリ（カンマ区切り）。未設定なら配信無効 |

## 2. API エンドポイント一覧

| メソッド/パス | 認証 | Phase | 役割 |
| --- | --- | --- | --- |
| `POST /api/notify` | ✔ | 1 | 通知パケットを登録 |
| `POST /api/handoff` | ✔ | 1 | ハンドオフパケットを登録（Phase 1 は記録のみ） |
| `GET /api/tasks` | – | 1 | 通知履歴一覧（フィルタ・ページング付き） |
| `GET /api/tasks/{task_id}` | – | 1 | 特定タスクの詳細（イベント履歴含む） |
| `GET /api/stream` | –※ | 2 | SSE でイベントをリアルタイム配信 |
| `GET /api/artifacts/{task_id}` | – | 2 | 成果物のサーバー経由配信（任意機能） |
| `POST /api/tasks/{task_id}/ack` | ✔ | 3 | ユーザー確認済みにする |
| `POST /api/tasks/{task_id}/retry` | ✔ | 3 | 再実行要求を登録・配信 |
| `GET /api/health` | – | 1 | 疎通確認（`{"status": "ok", "version": "0.1.0"}`） |
| `GET /` | – | 2 | Web UI（静的 HTML） |

※ `MACP_TOKEN` 設定時は GET 系にもトークンを要求する（§9）。

### 2.1 `POST /api/notify`

- 入力: MACP パケット（`protocol.md` §3）
- 処理: 検証 → 正規化（エイリアス解決、`mood_computed` 導出、`received_at` 付与）→ 保存（§6）→ SSE 配信
- 応答 `201`:

```json
{ "ok": true, "event_id": 42, "task_id": "task-20260707-001", "mood_computed": "good" }
```

### 2.2 `GET /api/tasks`

クエリ: `status` / `task_type` / `intent` / `acknowledged`(bool) / `limit`(既定 50) / `offset`
応答: `tasks` テーブルの最新状態の配列（新しい順）。

### 2.3 `GET /api/tasks/{task_id}`

応答: タスクの最新状態 + そのタスクの全イベント（`events` から時系列順）+ 関連ハンドオフ。

### 2.4 `POST /api/tasks/{task_id}/ack`

- 終端状態（`done` / `failed` / `blocked` / `need_review`）のタスクを `acknowledged` に遷移させ、`acknowledged_at` を記録
- `ack` イベントを `events` に追記し、SSE 配信（他端末の UI も既読表示に変わる）
- 冪等: すでに `acknowledged` なら `200` で現状を返す

### 2.5 `POST /api/tasks/{task_id}/retry`

**サーバーは AI タスクを実行しない。** retry は「再実行要求」の記録・配信である。

1. 対象タスクの元パケットから `from.agent_id` を取り出し、宛先とする
2. `retry_requested` イベントを `events` に追記。ペイロードは MACP パケット形式:
   - `intent: "handoff_agent"` ではなく専用の event_type で区別し、`to: {"type": "agent", "target": "<元の from.agent_id>"}`、`summary: "再実行が要求されました"`、任意の `reason`（リクエストボディから）
3. SSE 配信。エージェント（またはエージェントを操作する人間）がこれを拾って再実行する
4. `tasks.retry_requested_at` を更新

## 3. SSE 配信設計

### 3.1 ワイヤ形式

```text
GET /api/stream
Accept: text/event-stream
Last-Event-ID: 41        ← 再接続時にブラウザ/クライアントが自動送信
```

```text
id: 42
event: packet
data: {"protocol":"macp", ... , "event_id":42, "mood_computed":"good"}

id: 43
event: ack
data: {"task_id":"task-20260707-001","acknowledged_at":"..."}

: ping                    ← 15 秒ごとのハートビート（コメント行）
```

| event | 内容 |
| --- | --- |
| `packet` | 通知/ハンドオフ/返却パケット本体 |
| `ack` | ack 状態の変化 |
| `retry` | 再実行要求 |

- `id:` には必ず `event_id`（§4）を入れる。これが再送カーソルになる
- ハートビートは接続維持（プロキシ・スリープ検出）のため 15 秒間隔で送る
- クエリ `?last_event_id=` もサポートする（`Last-Event-ID` ヘッダを送れないクライアント向け。ヘッダとクエリの両方があればヘッダ優先）

### 3.2 event_bus（in-process）

- 各 SSE 接続に `asyncio.Queue` を 1 本割り当て、`subscribers` 集合で管理
- パケット保存後、`event_bus.publish(event)` が全キューに put する
- キューが溢れた購読者（詰まったクライアント）は切断する（再接続時に §5 の再送で回復するため、取りこぼしは起きない）

## 4. event_id 管理（SQLite）

- `events.event_id` は `INTEGER PRIMARY KEY AUTOINCREMENT`。**サーバー全体で単調増加**し、全イベント種別（packet / ack / retry / handoff）で単一の系列を共有する
- SSE の `id:` と API 応答の `event_id` はこの値
- クライアントは「最後に処理した event_id」を永続化する（ブラウザは EventSource が自動管理、Python クライアントはローカルファイルに保存）

## 5. 再接続・再送ロジック（堅牢化の中核）

サーバー側 `GET /api/stream` の処理手順:

```text
1. last_id = Last-Event-ID ヘッダ or ?last_event_id= or なし
2. queue = event_bus.subscribe()          ← 先にライブ購読を開始する（すき間を作らない）
3. if last_id が指定されている:
     backlog = SELECT * FROM events WHERE event_id > last_id ORDER BY event_id
     backlog を順に送信し、送った最大 event_id を cursor に記録
   else:
     cursor = 現在の MAX(event_id)        ← 初回接続は過去分を流さない（履歴は /api/tasks で取る）
4. ループ: queue から取り出し、event_id <= cursor なら破棄（再送との重複排除）、
   それ以外を送信して cursor を更新
5. 切断・例外時: event_bus.unsubscribe(queue)
```

ポイント:

- **購読開始（手順2）を backlog 読み出し（手順3）より先に行う**ことで、backlog 送信中に発生した新イベントの取りこぼしを防ぐ。重複は `cursor` 比較で排除する
- クライアント側は受信した `id` を保存し続けるだけでよい。切断→再接続で自動的に差分再送される
- サーバー再起動をまたいでも、`event_id` は SQLite の AUTOINCREMENT なので巻き戻らない
- イベントは削除しない（個人利用規模では問題にならない。将来必要なら「N 日より古い events の間引き」を追加する。その場合、間引き済み範囲の `Last-Event-ID` を持つクライアントには全量スナップショット取り直しを指示する `event: reset` を返す設計とする）

クライアント側（Python / Android ネイティブ）の再接続:

```text
1. 起動時にローカル保存の last_event_id を読み込む
2. GET /api/stream に Last-Event-ID を付けて接続
3. 受信ごとに last_event_id を更新・永続化（ファイル書き込みは 1 イベントごとで十分）
4. 切断検出（読み取りタイムアウト > ハートビート間隔 ×2 = 30 秒）で指数バックオフ再接続
   （2s → 4s → 8s → 最大 60s）
```

## 6. SQLite スキーマ

```sql
CREATE TABLE IF NOT EXISTS events (
  event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id    TEXT NOT NULL,
  event_type TEXT NOT NULL,            -- 'packet' | 'ack' | 'retry_requested'
  payload    TEXT NOT NULL,            -- 正規化済みパケット全体の JSON
  created_at TEXT NOT NULL             -- サーバー受信時刻 (ISO 8601)
);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);

CREATE TABLE IF NOT EXISTS tasks (
  task_id            TEXT PRIMARY KEY,
  task_type          TEXT,
  intent             TEXT,
  command            TEXT,
  status             TEXT NOT NULL,    -- protocol.md §7（acknowledged 含む）
  priority           TEXT,
  summary            TEXT,
  agent_id           TEXT,             -- 最新パケットの from.agent_id
  mood               TEXT,             -- 申告値（null 可）
  mood_computed      TEXT,
  requires_user_action INTEGER DEFAULT 0,
  latest_packet      TEXT NOT NULL,    -- 最新パケット JSON（一覧 API はここから返す）
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
  state             TEXT NOT NULL,     -- handoff.md §5: pending/accepted/returned/escalated/expired
  payload           TEXT NOT NULL,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);
```

- 書き込みは「`events` 追記 → `tasks` upsert →（該当時）`handoffs` upsert」を**単一トランザクション**で行う
- `store.py` は上記を隠蔽するインターフェース（`append_event` / `get_events_after` / `list_tasks` / `get_task` / `ack` / `mark_retry` …）を提供し、SQLite 以外への差し替えを可能にしておく

### JSONL 監査ログ

- `MACP_JSONL_PATH` に、受信した**生パケット**（正規化前）を 1 行 1 JSON で追記する
- 目的: デバッグ・障害時の突き合わせ・将来の再インポート。主記録は SQLite
- 追記失敗は警告ログにとどめ、API 処理は継続する

## 7. 成果物配信（`GET /api/artifacts/{task_id}`、任意機能）

1. `MACP_ARTIFACT_ROOTS` 未設定なら `404`（機能無効）
2. タスクの `result.path` を絶対パスに解決（`Path.resolve()`）
3. **解決後のパスが許可ディレクトリのいずれかの配下にあることを検証**（パストラバーサル防止。`Path.is_relative_to` を使用）
4. 検証に通ればファイルを `FileResponse` で返す（`format` から Content-Type を推定）
5. 通らなければ `403`。ファイル不存在は `404`

Web UI は `result.url` が無く `result.path` があるタスクに対し、この エンドポイントへのリンクを表示する（`notification-packet.md` §3 の優先順位）。

## 8. エラー処理

エラー応答は共通形式:

```json
{ "ok": false, "error": { "code": "validation_error", "message": "...", "fields": [ ... ] } }
```

| HTTP | code | 場面 |
| --- | --- | --- |
| 401 | `unauthorized` | トークン不一致・欠落 |
| 403 | `forbidden` | 成果物パスが許可ディレクトリ外 |
| 404 | `not_found` | task_id 不存在、成果物なし、機能無効 |
| 409 | `invalid_state` | 終端状態でないタスクへの ack など |
| 422 | `validation_error` | パケット検証失敗（違反フィールドを `fields` に列挙） |
| 500 | `internal_error` | 想定外（詳細はログのみ。応答に内部情報を含めない） |

## 9. 認証・CORS

- 書き込み系（`POST` 全部）: `Authorization: Bearer <MACP_TOKEN>` または `X-MACP-Token: <token>` を要求
- `GET /api/stream`: ブラウザの `EventSource` は任意ヘッダを送れないため、**`?token=` クエリを許可**する（LAN 内前提の簡易措置。URL にトークンが残る点は docs に明記し、外部公開しないこと）
- `MACP_TOKEN` 未設定時は認証を無効化（ローカル開発用）。バインドが `0.0.0.0` かつトークン未設定の場合は起動時に警告ログを出す
- CORS: `MACP_CORS_ORIGINS` のオリジンに対して `POST /api/notify` 等を許可（Multi-agent-Platform = `http://localhost:3000` からのブラウザ送信に必須）

## 10. ログ設計

- 標準の `logging` を使用。コンソール + ローテーションファイル（`./data/server.log`）
- INFO: 受信パケット（task_id / intent / status / mood_computed）、SSE 接続・切断（Last-Event-ID と再送件数）、ack / retry
- WARNING: 未知 task_type、JSONL 追記失敗、詰まった購読者の切断、トークン未設定での LAN バインド
- ERROR: 検証以外の例外（スタックトレース付き）
- 通知本文（detail 等）はログに全文を書かない（機密が混ざる可能性があるため task_id と summary までにとどめる）
