# MACP 実装ロードマップ

過去試作（FastAPI + SSE + Windows toast、一度動作）の再設計・堅牢化として段階を切る。
各 Phase は「完了条件」を満たしたら次へ進む。順序の入れ替えは可（特に 2.5 と 3）。

## Phase 0: 仕様固定・サンプル JSON 作成 — ✅ 本ドキュメント一式で完了

- [x] プロトコル仕様（`protocol.md` / `notification-packet.md` / `handoff.md`）
- [x] サーバー・クライアント設計（`transport.md` / `clients.md` / `android-client-notes.md`）
- [x] サンプルパケット 5 種（`examples/`）
- [x] コマンド定義（`commands/`）
- [x] Codex 向け実装指示書（`codex-instruction.md`）

## Phase 1: サーバー最小実装

- `server/`（app / schemas / store / event_bus の骨格）
- `POST /api/notify`（検証・正規化・mood_computed 導出）
- SQLite（events / tasks / handoffs）+ JSONL 監査ログ
- `GET /api/tasks` / `GET /api/tasks/{task_id}` / `GET /api/health`
- `POST /api/handoff`（記録のみ）
- トークン認証（設定時は GET 系 API も保護）・CORS
- JSON Schema / TypeScript 型定義の生成・配布（pydantic モデルから生成。Multi-agent-Platform 等の接続クライアント向け）
- テスト: `tests/test_schema.py`（examples 全件の検証）、`tests/test_notify_api.py`

**完了条件**: `curl` で `examples/notify_done.json` を POST し、`GET /api/tasks` で確認できる。テストが通る。

## Phase 2: SSE + Web UI + 成果物配信

- `GET /api/stream`（`Last-Event-ID` 再送・ハートビート・重複排除。`transport.md` §5）
- Web UI（一覧・詳細・フィルタ・SSE ライブ更新。`clients.md` §2）
- `GET /api/artifacts/{task_id}`（許可リスト式、任意機能）

**完了条件**: ブラウザ 2 枚で同時受信できる。片方をオフライン→復帰させて取りこぼしゼロを確認できる。

## Phase 2.5: Windows 通知の復旧・参考実装

- `clients/windows/notify_receiver.py`（toast 表示・カーソル永続化・指数バックオフ再接続）
- スタートアップ登録手順の文書化

**完了条件**: サーバー再起動・PC スリープ復帰をまたいで通知が復旧し、スリープ中のイベントが再送される。

## Phase 3: ack / retry

- `POST /api/tasks/{id}/ack`（既読の全端末同期）
- `POST /api/tasks/{id}/retry`（再実行要求イベントの記録・配信。サーバーは実行しない）
- Web UI にボタン追加

**完了条件**: スマホブラウザから ack した既読状態が PC の Web UI に即時反映される。

## Phase 4: Android

- **4a**: スマホブラウザ運用の整備（LAN バインド・FW・トークン・ホーム画面追加手順）— 実装ゼロ
- **4b**: ネイティブアプリ（起動中 SSE 受信 + ローカル通知。`android-client-notes.md` §3）

**完了条件（4a）**: 外出想定で Wi-Fi 切断→復帰後、スマホで未読タスクを確認し ack できる。
**完了条件（4b）**: アプリ起動中に通知が表示され、再起動後に未受信分が再送される。

## Phase 5: AI→AI ハンドオフの実行制御

- hop / max_hops 検査、循環検出
- confidence_gate による人間差し戻し（`need_review` 化）
- handoff 状態遷移（pending → accepted → returned / escalated / expired）とタイムアウト
- Web UI のハンドオフ履歴ビュー
- テスト: `tests/test_handoff.py`

**完了条件**: `/triage → /review → /spec` の 3 hop 直列処理が記録され、gate 未達時に人間へ差し戻される。

## Phase 6: 本格スマホ通知の検討（設計のみ先行）

- FCM（またはクラウド中継）の要否判断。判断材料: Phase 4 運用で「アプリを開かないと気づけない」ことが実際にどの程度問題になるか
- 採用する場合もパケット仕様は変えない（配送レイヤーの追加のみ）

## 対象外（非目標の再掲）

クラウド通知基盤 / ユーザー管理 / 大規模配信 / LLM 実装 / 各 AI サービス API 統合
