# MACP 全体設計書

## 1. システム目的

複数 AI エージェントの処理結果を共通 JSON パケット（MACP パケット）として集約し、
ローカルサーバー経由で PC・スマホ・Web UI に通知・履歴表示する最小基盤を提供する。

人間は「見に行く」のではなく「通知で受け取る」。回線切断・端末不在があっても、
履歴と再送によって後から必ず追跡できることを設計の中心に置く。

## 2. 想定ユースケース

1. **長時間タスクの完了通知**: PC 上のエージェントが PR 監査や仕様書化を終えたら、外出中のスマホ（ブラウザ）と Windows 通知で結果を受け取る
2. **外出先からの追加指示出し**: スマホの Web UI で結果を確認し、ack（確認済み）や retry（再実行要求）を返す
3. **AI→AI の直列処理**: 分類（/triage）→ レビュー（/review）→ 仕様化（/spec）をエージェント間でハンドオフし、最終結果だけ人間に通知する
4. **Multi-agent-Platform からの通知**: ブラウザ上の Multi-agent-Platform（React アプリ）がエージェント処理の完了時に MACP サーバーへパケットを POST する

## 3. 全体アーキテクチャ

```text
┌────────────────────────── producers（クライアント）──────────────────────────┐
│  AI Agent (Claude Code / Codex / スクリプト)      Multi-agent-Platform (React) │
└──────────────┬───────────────────────────────────────────┬────────────────┘
               │ POST /api/notify, /api/handoff (JSON packet, token)│  ※CORS 必須
               ▼                                                    ▼
┌──────────────────────────── MACP notify server（メイン PC 常駐）─────────────┐
│  FastAPI (uvicorn)                                                          │
│   ├─ schemas.py   … pydantic によるパケット検証・mood 導出                    │
│   ├─ store.py     … SQLite（tasks / events / handoffs）+ JSONL 監査ログ      │
│   ├─ event_bus.py … in-process 購読キュー（asyncio.Queue per subscriber）    │
│   └─ app.py       … API + SSE 配信 + Web UI / 成果物の静的配信               │
└──────┬────────────────────────┬──────────────────────────┬─────────────────┘
       │ SSE /api/stream         │ SSE / HTTP               │ HTTP (polling も可)
       ▼                        ▼                          ▼
┌──────────────┐   ┌─────────────────────┐   ┌──────────────────────────┐
│ Windows 通知  │   │ Web UI (ブラウザ)     │   │ Android                   │
│ notify_       │   │ ・PC ブラウザ         │   │ Phase 4a: スマホブラウザで │
│ receiver.py   │   │ ・スマホブラウザ       │   │   Web UI を閲覧            │
│ (toast 表示)  │   │  一覧/詳細/ack/retry  │   │ Phase 4b: ネイティブアプリ │
└──────────────┘   └─────────────────────┘   │   (起動中 SSE 受信)        │
                                              └──────────────────────────┘
```

- **producers**: MACP パケットを生成して POST する側。エージェント本体・外部ツール・Multi-agent-Platform など。MACP はこれらの実装に関与しない（疎結合）
- **MACP notify server**: パケットの検証・保存・配信を行う唯一の常駐プロセス。メイン PC 1台でホストする
- **consumers**: SSE またはポーリングで通知を受け取る側。Windows 通知クライアント、Web UI、Android

## 4. コンポーネント構成

| コンポーネント | 配置 | 役割 |
| --- | --- | --- |
| `server/app.py` | メイン PC | FastAPI アプリ本体。API ルーティング、SSE 配信、Web UI 静的配信 |
| `server/schemas.py` | 同上 | pydantic モデル。パケット検証、`mood_computed` 導出、エイリアス正規化 |
| `server/store.py` | 同上 | SQLite への保存・照会と JSONL 追記。ストレージ差し替え可能な薄い抽象 |
| `server/event_bus.py` | 同上 | 接続中 SSE クライアントへの in-process ブロードキャスト |
| `clients/windows/notify_receiver.py` | PC（両方可） | SSE を購読し Windows toast 通知を表示 |
| `clients/web/` | サーバーが配信 | 通知履歴の一覧・詳細・ack/retry 操作。スマホブラウザ対応 |
| `clients/android/` | Android | Phase 4a はブラウザ運用のためコードなし（手順書のみ）。Phase 4b でネイティブ |
| `commands/*.md` | リポジトリ | `/review` `/polish` `/triage` `/spec` の各コマンド定義 |
| `examples/*.json` | リポジトリ | 検証・テストに使うサンプルパケット |

## 5. データフロー

### 5.1 通知（正常系）

```text
1. Agent が MACP パケットを生成
2. POST /api/notify（トークン付き）
3. schemas.py が検証・正規化（エイリアス解決、mood_computed 導出）
4. store.py が SQLite に保存
   - events に event_id（単調増加）付きで追記
   - tasks の最新状態を upsert
   - JSONL に生パケットを追記
5. event_bus.py が接続中の全 SSE クライアントに配信（id: event_id）
6. クライアントが表示（toast / Web UI 更新）
```

### 5.2 切断からの復帰（再送）

```text
1. クライアントの SSE 接続が切れる（回線断・スリープ・アプリ終了）
2. その間もサーバーは events にイベントを蓄積し続ける
3. クライアントが再接続時に Last-Event-ID（または ?last_event_id=）を送る
4. サーバーは event_id > Last-Event-ID のイベントを SQLite から読み出して先に再送
5. 以降はライブ配信に合流（event_id 単調増加・クライアント側で重複破棄）
```

詳細アルゴリズムは [`transport.md`](./transport.md) §5。

### 5.3 ack / retry

```text
ack:   ユーザー操作 → POST /api/tasks/{id}/ack
       → tasks.acknowledged = true（status は元の終端状態を維持）, ack イベントを events に追記 → SSE 配信
retry: ユーザー操作 → POST /api/tasks/{id}/retry
       → retry_requested イベントを events に追記（宛先 = 元パケットの from.agent_id）
       → SSE 配信。実行はエージェント側の責務（サーバーは AI を実行しない）
```

### 5.4 ハンドオフ（Phase 5）

[`handoff.md`](./handoff.md) 参照。Phase 1 時点では `POST /api/handoff` が記録のみ行う。

## 6. Multi-agent-Platform との接続点

- Platform（ブラウザ完結の React アプリ）は MACP の**クライアント**であり、`fetch` で `POST /api/notify` にパケットを送るだけ
- 送信元がブラウザであるため、MACP サーバーは **CORS 許可リスト**（既定: `http://localhost:3000`）を持つ
- MACP は JSON Schema と TypeScript 型定義（`.d.ts`）を配布する予定である（**現時点で実ファイルはなく、Phase 1 で pydantic モデルから生成・配布する**）。Platform 側はそれをインポートして検証する
- Platform 内のハンドオフ概念と MACP `handoff` フィールドのマッピングは、Platform 側リポジトリでの別タスクとして扱う

## 7. 最小実装と将来拡張の切り分け

| 区分 | 内容 |
| --- | --- |
| **最小実装（Phase 1–2.5）** | `POST /api/notify` → SQLite/JSONL 保存 → `GET /api/tasks` 照会 → SSE 配信（再送含む）→ Web UI → Windows 通知復旧 |
| **中期（Phase 3–4）** | ack / retry、スマホブラウザ運用の整備、Android ネイティブ（起動中 SSE 受信） |
| **後期（Phase 5–6）** | AI→AI ハンドオフの実行制御、FCM 等の本格プッシュ通知 |
| **対象外** | クラウド基盤、ユーザー管理、大規模配信、LLM 実装、各 AI サービス API 統合 |

段階の詳細と完了条件は [`roadmap.md`](./roadmap.md)。
