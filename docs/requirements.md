# MACP 要件定義書（確定版）

Multi-Agent Command Protocol（以下 **MACP**）の要件定義。
2026-07-07 時点の要件定義ドラフトと、その後の質疑で確定した設計判断を統合した確定版である。

> **位置づけ**: 本プロジェクトは完全な新規設計ではなく、
> **過去に一度動作していた FastAPI + SSE + Windows toast 通知の試作を、再設計して堅牢化する**ものである。
> 過去試作は Android ネイティブ通知の環境構築段階で中断しており、その反省
> （最初からネイティブ実装に進まない、切断・不在を前提にする）を本設計に織り込む。

---

## 1. 目的

複数 AI エージェントの処理結果を**共通の JSON パケット形式（MACP パケット）**で扱えるようにし、以下を可能にする。

1. AI エージェントから人間への通知
2. AI エージェントから別 AI エージェントへのハンドオフ
3. 複数 AI による直列処理（分類 → レビュー → 整形 → 仕様化）
4. Windows / Android / Web UI など複数端末への結果通知
5. 長時間タスクや外部 AI サービスの結果を、チャット画面に張り付かずスマホ等で受け取る運用

中心にあるのは「スマホ通知アプリ」ではなく、
**AI タスク結果を共通パケットとして扱うための軽量プロトコル**である。

## 2. 想定利用者・端末

- 利用者: 単一ユーザー（司令官モデル。人間は判断と優先度付けに集中し、実行は AI に委譲する）
- 端末:
  - PC 2台（うち **メイン PC 1台が MACP サーバーの常駐ホスト**。もう1台はクライアント）
  - 外出時の Android スマホ（**初期はスマホブラウザで Web UI を閲覧**。ネイティブアプリは後続 Phase）
  - Web UI（通知履歴の確認・追跡用）
- 通知先: Windows 通知 / Android（ブラウザ→将来ネイティブ）/ Web 画面上の通知・履歴表示

## 3. 対象タスク種別（`task_type`）

初期対応:

| task_type | 用途 |
| --- | --- |
| `portfolio` | ポートフォリオ作成、README 整備、成果物整理 |
| `coding` | コードレビュー、実装修正、設計指示、PR 監査 |
| `avatar_3d` | 3D アバター調整、Blender ワークフロー、モデル修正指示 |

将来追加予定: `research` / `document` / `slides` / `agent_handoff` / `notification_test` / `maintenance`

未知の `task_type` は受理する（前方互換。詳細は `protocol.md`）。

## 4. 機能要件

### 4.1 通知パケット
- AI エージェントは処理結果を自然文だけでなく、共通 JSON パケットとして出力する
- パケット仕様は [`protocol.md`](./protocol.md) / [`notification-packet.md`](./notification-packet.md) で定義
- 機械的要約（`summary`）・要求充足の要約（`requirement_summary`）・人格ごとの通知文（`agent_message`）を分離して保持する

### 4.2 配送
- FastAPI サーバーが `POST /api/notify` でパケットを受理し、SSE（`GET /api/stream`）でリアルタイム配信する
- **回線切断・端末不在を前提**とし、SSE の `Last-Event-ID` による再接続時に、SQLite 上の `event_id` を用いて取りこぼし分を再送する（仕様だけでなく再送ロジックまで設計に含める。詳細は [`transport.md`](./transport.md)）

### 4.3 履歴・状態管理
- 全パケットを SQLite に保存し、JSONL に生パケットを追記（監査ログ）
- タスク状態: `queued` / `running` / `done` / `failed` / `blocked` / `need_review`
- 既読（acknowledged）は `status` とは**独立のサーバー管理フラグ**（`acknowledged` / `acknowledged_at`）として保持する。ack しても元の終端状態（`done` / `failed` 等）は一覧上で失われない

### 4.4 ack / retry
- `POST /api/tasks/{task_id}/ack`: ユーザーが確認済みにする
- `POST /api/tasks/{task_id}/retry`: **再実行「要求」の記録・配信**。サーバー自体は AI タスクを実行しない。再実行要求イベントを生成して送信元エージェント宛に記録・SSE 配信し、実行はエージェント側（またはエージェントを操作する人間）の責務とする

### 4.5 成果物参照
- **PC ローカルで開ける `result.path` と、スマホ・Web UI から参照できる `result.url` を明確に分離する**
- `open_file` アクションは PC 上でのみ有効
- Phase 2 で `GET /api/artifacts/{task_id}`（任意機能）を追加し、サーバー経由でスマホへ成果物を配信できるようにする

### 4.6 AI→AI ハンドオフ
- 2〜3 個体の直列処理を想定。人間通知と同一のパケット形式で扱う
- `hop` / `max_hops` による無限ループ防止、`confidence_gate` による人間確認への差し戻し、`must_return_to` による呼び出し元への返却制御
- **仕様は Phase 0 で固定、実装は Phase 5**。ただし `POST /api/handoff` は Phase 1 から「受理して記録するだけ」の形で先置きする
- 詳細は [`handoff.md`](./handoff.md)

### 4.7 好調・不調（mood）
- 感情ではなく実務的な評価: `good` / `caution` / `bad` / `blocked` / `unknown`
- **エージェント申告は任意**。未指定時はサーバーが導出規則で自動計算する
- 申告値と導出値が矛盾する場合は、申告値と `mood_computed` を併記する
- 導出規則は [`notification-packet.md`](./notification-packet.md) に定義

## 5. 非機能要件

### 5.1 実行環境
- サーバー: Python 3.11+、Windows 上で uvicorn 直接起動
- 依存: FastAPI / uvicorn / pydantic の最小限
- クライアント（Windows 通知）: Python スクリプト
- Web UI: 依存なしの静的 HTML + vanilla JS（FastAPI が配信）

### 5.2 セキュリティ・公開範囲
- ローカルまたは LAN 内利用を前提とし、外部公開を前提にしない
- ローカル開発用と LAN 運用用の設定を分ける
- `POST /api/notify` 等の書き込み系 API を簡易トークンで保護する
- 通知本文に機密情報を直接入れすぎず、詳細はファイルパス・ローカル URL 参照に逃がす
- 成果物配信はディレクトリ許可リストで制限する（任意ファイル読み出しの防止）
- Android 実機で LAN 接続する場合、同一ネットワーク上の他端末から見えないよう注意する

### 5.3 耐切断性
- 通知は一時的なリアルタイムイベントではなく、必ず履歴として残る
- クライアントが未接続でもサーバー側にイベントが蓄積され、再接続時に再送される
- アプリ未起動・通知見逃しでも、後から Web UI / API で追跡できる

## 6. 非目標（初期設計）

- 完全なクラウド通知基盤
- 複雑なユーザー管理・多数端末への大規模配信
- 常時バックグラウンド動作する Android プッシュ通知（FCM は後続 Phase で検討）
- 複雑なマルチエージェント自律実行基盤
- LLM 本体の実装、各 AI サービスの API 統合

最小目標: **AI が出した結果を共通 JSON にし、ローカルサーバー経由で PC・スマホ・Web へ表示できる最小基盤**。

## 7. 確定済み設計判断（決定ログ）

| # | 論点 | 決定 |
| --- | --- | --- |
| 1 | プロジェクト名 | リポジトリ名は `Multi-Agent-Command-Protocol` のまま。略称 **MACP** を導入し、パケットの `protocol` フィールドは `"macp"`。MCP（Model Context Protocol）とは別物である旨を README に明記 |
| 2 | 通信方式 | **SSE** を採用。通知はサーバー→クライアント単方向で、逆方向は POST で足りる。`Last-Event-ID` の再接続・再送が切断前提の要件と整合。WebSocket は双方向が必要になった段階で再検討 |
| 3 | 履歴保存 | **SQLite を主、JSONL を監査ログ**として併用。ack/retry で状態が変わるため追記専用 JSONL は主記録に不適。`store.py` を薄い抽象にして差し替え可能に |
| 4 | Android | **スマホブラウザで Web UI 閲覧から開始**。ネイティブアプリ（起動中 SSE 受信）は Phase 4。ブラウザ Notification API は HTTPS 必須のため LAN 内 HTTP では画面内表示まで |
| 5 | ハンドオフ | 仕様は Phase 0 で固定、実装は Phase 5。`POST /api/handoff` は Phase 1 から記録のみで先置き |
| 6 | コマンド名 | 汎用名（`/review` `/polish` `/triage` `/spec`）を正準とし、`/curren-check` 等は**エイリアス**。パケットには正準名を格納、`command_alias` に入力表記を保持 |
| 7 | 人格通知文 | `summary` / `requirement_summary` / `agent_message` の3フィールド分離までをプロトコルに含め、人格文の生成規則はエージェント側の責務。`agent_message` 欠落時は UI が `summary` にフォールバック |
| 8 | multi-agent-platform 等との接続 | **疎結合**。platform / harness 側は MACP のクライアントであり `POST /api/notify` にパケットを投げる。MACP は JSON Schema と TypeScript 型定義を配布する（**実ファイルは Phase 1 で pydantic モデルから生成・配布予定**）。具体的な接続設計は別タスク |
| 9 | retry の意味 | 再実行**要求**の記録・配信。サーバーは AI タスクを実行しない |
| 10 | 成果物アクセス | `result.path`（PC ローカル）と `result.url`（リモート参照）を分離。Phase 2 で `GET /api/artifacts/{task_id}` を任意機能として追加 |
| 11 | mood 判定 | 申告任意、未指定時サーバー導出。矛盾時は申告値と `mood_computed` を併記 |
| 12 | サーバー常駐 | メイン PC 1台が常駐ホスト。もう1台の PC とスマホはクライアント |
| 13 | 実行環境 | Python 3.11+ / Windows / uvicorn 直接起動 / FastAPI・uvicorn・pydantic 最小依存 |
| 14 | ドキュメント言語 | docs 一式は日本語主体、README のみ日英併記 |
| 15 | Windows 通知の位置づけ | **Phase 2.5「Windows 通知復旧・参考実装」**として扱う（過去に動作実績があり、Android より検証が容易なため疎通確認の基準実装とする） |
| 16 | PR #1 レビュー反映 | 未知 enum の許容は `task_type` / `evaluation.mood` / `action_type` に限定し、`intent` / `status` / `priority` / `to.type` の未知値は 422 で拒否。既読は `status` と独立の `acknowledged` フラグで管理。retry イベント名は `retry_requested` に統一し、payload は MACP パケットと分離した server event envelope とする。`MACP_TOKEN` 設定時は GET 系 API も保護。Web UI も `last_event_id` を `localStorage` に永続化 |

## 8. 関連ドキュメント

| ドキュメント | 内容 |
| --- | --- |
| [`architecture.md`](./architecture.md) | 全体設計書（§18.1） |
| [`protocol.md`](./protocol.md) | プロトコル仕様書（§18.2） |
| [`notification-packet.md`](./notification-packet.md) | パケットフィールド辞書・mood 導出規則 |
| [`handoff.md`](./handoff.md) | AI→AI ハンドオフ仕様 |
| [`transport.md`](./transport.md) | サーバー設計・SSE 再送設計（§18.3） |
| [`clients.md`](./clients.md) | クライアント設計（§18.4） |
| [`android-client-notes.md`](./android-client-notes.md) | Android 側の注意点 |
| [`roadmap.md`](./roadmap.md) | 実装ロードマップ（§18.5） |
| [`codex-instruction.md`](./codex-instruction.md) | Codex 向け実装指示書・全体像（§18.6） |
| [`codex-phase1-instruction.md`](./codex-phase1-instruction.md) | Codex 向け Phase 1 開発指示書（実行用） |
