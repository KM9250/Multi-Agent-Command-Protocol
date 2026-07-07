# MACP クライアント設計書

Windows 通知クライアント・Web UI・Android の設計。Android の詳細な注意点は
[`android-client-notes.md`](./android-client-notes.md) を参照。

## 1. 最小実装順

| 順 | クライアント | 理由 |
| --- | --- | --- |
| 1 | **Web UI**（PC ブラウザ） | サーバーと同居し環境要因が最少。SSE・再送の動作確認基盤になる |
| 2 | **Windows 通知**（Phase 2.5） | 過去に動作実績があり検証容易。**過去試作の復旧・参考実装**として位置づける |
| 3 | **スマホブラウザ**（Phase 4a） | 追加実装ほぼゼロ（Web UI を LAN 経由で開くだけ）。過去の中断点だった Android ネイティブを回避して先に運用開始 |
| 4 | **Android ネイティブ**（Phase 4b） | OS 通知が必要になった段階で着手 |

## 2. Web UI（`clients/web/`）

### 2.1 方針

- **依存なしの静的 HTML + vanilla JS 1 ファイル**から始める（ビルド工程を持ち込まない）
- FastAPI が `GET /` で配信する。スマホブラウザからは `http://<PCのLAN IP>:8765/` で開く
- スマホ表示前提のレスポンシブ（1 カラム、`viewport` 設定、タップ可能なボタンサイズ）

### 2.2 表示項目（要件 §14）

一覧（タスクカード）:

- `summary`（タイトル行）、`agent_message`（本文。欠落時は `summary` のみ）
- `status` バッジ、`mood` バッジ（既知の申告値は表示し、`mood_computed` と矛盾時は両方表示。**未知の申告値のときは `mood_computed` を主表示とし、申告値は詳細ビューに raw value として表示**）
- `task_type` / `command` / `from.agent_id`
- `confidence`、`requires_user_action`（要対応マーク）
- ack 済みかどうか（既読表示）
- `created_at`（相対時刻表示）

詳細ビュー:

- `requirement_summary` / `detail`
- `result`: `url` があればリンク、`path` のみなら `/api/artifacts/{task_id}` リンク（配信有効時）またはパス文字列表示
- `actions`（`open_url` / `ack` / `retry` はボタン化。`open_file` は「PC でのみ有効」の注記付きでパス表示）
- イベント履歴（同一 task_id の全パケット、時系列）
- ハンドオフ履歴（関連 handoff の状態）

操作:

- ack ボタン（`POST /api/tasks/{id}/ack`）
- retry ボタン（`POST /api/tasks/{id}/retry`、確認ダイアログ付き）
- フィルタ: status / task_type / 未 ack のみ

### 2.3 受信方式

- `EventSource` で `/api/stream` を購読。ただしブラウザ自動送信の `Last-Event-ID` は**同一接続の一時切断にしか効かず**、ページ再読み込み・ブラウザ終了・スマホのタブ破棄をまたぐと失われる。そのため **受信した `event_id` を `localStorage` に保存し、接続時に必ず `?last_event_id=` を付ける**（ヘッダとクエリ併存時はヘッダ優先のため二重送信しても安全）
- 初期表示は `GET /api/tasks` で取得し、以降 SSE 差分で更新
- `MACP_TOKEN` 設定時は初回にトークン入力を求めて `localStorage` に保存し、API 呼び出しにはヘッダで、`/api/stream` には `?token=` で付与する
- **ブラウザの Notification API は HTTPS（secure context）必須**のため、LAN 内 HTTP 運用では**ページ内の一覧更新・バッジ表示まで**とする。ページタイトルへの未読数表示（`(3) MACP`）で代替する

## 3. Windows 通知クライアント（`clients/windows/notify_receiver.py`）

### 3.1 位置づけ

過去に手動テストで動作していた Windows toast 通知の**復旧・参考実装**（Phase 2.5）。
他クライアント（Android ネイティブ等）の SSE 購読・再接続の参照実装を兼ねる。

### 3.2 設計

- 単一 Python スクリプト。依存: `httpx`（SSE ストリーム読み取り）+ `winotify`（toast 表示。追加のネイティブ依存がなく Python 3.11+ で安定）
- 処理:
  1. ローカルファイル（`%LOCALAPPDATA%/macp/last_event_id`）から前回カーソルを読む
  2. `GET /api/stream` に `Last-Event-ID` を付けて接続（`MACP_TOKEN` はヘッダで送れる）
  3. `event: packet` を受信するたびに toast を表示:
     - タイトル: `summary`（先頭に mood 絵文字: 🟢 good / 🟡 caution / 🔴 bad / ⛔ blocked / ⚪ unknown）
     - 本文: `agent_message`（なければ `requirement_summary`、なければ省略）
     - ボタン: 「Web UIで開く」（`http://<server>/#task/<task_id>` を開く）。`result.url` があれば「成果物を開く」も追加
  4. 受信ごとに `last_event_id` をファイルへ永続化
  5. 切断時は指数バックオフ（2s→4s→8s→最大 60s）で再接続
- 表示フィルタ:
  - `intent: log_only` は表示しない
  - `to.type == "agent"`（ハンドオフ・返却）は既定で表示しない（`--show-agent-events` で有効化）
  - `event: ack` / `event: retry_requested` は表示しない（Web UI 側の関心事）
- 自動起動: Windows の「スタートアップ」フォルダまたはタスクスケジューラ登録（手順は `clients/windows/README.md` に記載）

## 4. Android（`clients/android/`）

### Phase 4a: スマホブラウザ（コード実装なし）

- スマホのブラウザで `http://<PCのLAN IP>:8765/` を開き、ホーム画面に追加
- 必要なのはサーバー側の LAN バインド（`MACP_HOST=0.0.0.0`）とトークン設定のみ
- 制約: OS 通知は出ない（HTTP のため Notification API 不可）。「開けば最新履歴と未読が見える」運用

### Phase 4b: ネイティブアプリ（起動中 SSE 受信）

- Kotlin + OkHttp（`okhttp-sse`）で `/api/stream` を購読し、`NotificationManager` でローカル通知を表示
- `last_event_id` は `SharedPreferences` に永続化し、Windows クライアントと同じ再接続手順を踏む
- **アプリ起動中（フォアグラウンド）での受信に限定**する。バックグラウンド常時受信・FCM は Phase 6 で検討
- 環境構築の注意点（過去の中断点への対策）は [`android-client-notes.md`](./android-client-notes.md) に集約

## 5. クライアント共通ルール

1. 未知のフィールド・未知の `action_type` は無視する（前方互換）
2. `agent_message` 欠落時は `summary` にフォールバック
3. `result.url` → `/api/artifacts/{task_id}` → `path` 文字列表示、の優先順位（`notification-packet.md` §3）
4. `last_event_id` の永続化と再送カーソル付き再接続を必ず実装する（**Web UI もブラウザ任せにせず** `localStorage` + `?last_event_id=` を実装する）
5. 表示抑制はクライアント側の責務（サーバーは全イベントを配信する）
