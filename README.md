# Multi-Agent Command Protocol (MACP)

> **Japanese / English README**
> A lightweight command and notification protocol for orchestrating multiple AI agents and delivering their results to humans across devices (Windows / Android / Web).

> **注意 / Note**: 本プロトコルは Model Context Protocol (MCP) とは無関係の別物です。名前が紛らわしいため、略称は **MACP** を用います。過去の検討では `Multi-Agent-Command-Protocol` と呼んでいた経緯があり、リポジトリ名はそのまま維持しています。
> This protocol is **not** related to the Model Context Protocol (MCP). To avoid confusion we use the abbreviation **MACP**.

---

## 概要（日本語）

このリポジトリは、**複数のAIエージェントの処理結果を共通のJSONパケットとして扱い、人間や別のAIへ通知・引き継ぎするための軽量プロトコル（MACP）**を定義したものです。

中心にあるのは「スマホ通知アプリ」ではなく、**AIタスク結果を共通パケットとして扱うためのプロトコル**です。その上で、

* AIエージェントから人間への通知（Windows / Android / Web UI）
* AIエージェントから別AIエージェントへのハンドオフ
* 複数AIによる直列処理（分類 → レビュー → 整形 → 仕様化）
* 長時間タスクの結果を、チャット画面に張り付かずスマホ等で受け取る運用

を可能にします。

本プロジェクトは、過去に一度動作していた FastAPI + SSE + Windows toast 通知の試作を、
**再設計して堅牢化する**ものです。回線切断や端末不在を前提に、履歴保存・`Last-Event-ID` による再送・状態確認を設計の中心に置いています。

### 主な特徴

* **スラッシュコマンド型インターフェース** — `/review` `/polish` `/triage` `/spec`（旧 `/curren-check` 等はエイリアスとして互換維持）
* **AI→AIハンドオフ対応** — `hop` / `max_hops` によるループ防止、`confidence_gate` による人間差し戻し
* **通知ファースト設計** — 「見に行く」のではなく通知で受け取る。見逃しても履歴と再送で追跡できる
* **確信度ベースの状態表現** — `good` / `caution` / `bad` / `blocked` / `unknown` を機械的に導出可能
* **人格非依存・人格適用両対応** — 機械的要約（`summary`）と人格ごとの通知文（`agent_message`）を分離

### ドキュメント

設計は `docs/` に揃っています。読み順の推奨:

| ドキュメント | 内容 |
| --- | --- |
| [`docs/requirements.md`](./docs/requirements.md) | 要件定義（確定版）と設計判断の決定ログ |
| [`docs/architecture.md`](./docs/architecture.md) | 全体設計書 |
| [`docs/protocol.md`](./docs/protocol.md) | プロトコル仕様（フィールド・intent・status・command） |
| [`docs/notification-packet.md`](./docs/notification-packet.md) | パケット詳細・mood 導出規則 |
| [`docs/handoff.md`](./docs/handoff.md) | AI→AIハンドオフ仕様 |
| [`docs/transport.md`](./docs/transport.md) | サーバー設計（FastAPI / SSE 再送 / SQLite） |
| [`docs/clients.md`](./docs/clients.md) | クライアント設計（Windows / Web / Android） |
| [`docs/android-client-notes.md`](./docs/android-client-notes.md) | Android 側の注意点 |
| [`docs/roadmap.md`](./docs/roadmap.md) | 実装ロードマップ（Phase 0〜6） |
| [`docs/codex-instruction.md`](./docs/codex-instruction.md) | Codex 向け実装指示書 |

### パケット例

```json
{
  "protocol": "macp",
  "version": "0.1.0",
  "task_id": "task-20260707-001",
  "task_type": "coding",
  "intent": "notify_user",
  "from": { "agent_id": "vega", "agent_role": "spec_writer" },
  "command": "/spec",
  "status": "done",
  "summary": "Codex向けの実装指示書を作成しました。",
  "agent_message": "指示書は最小構成でまとめてあります。",
  "evaluation": { "confidence": 0.86, "requirement_satisfaction": 0.9, "mood": "good", "requires_user_action": true },
  "created_at": "2026-07-07T06:00:00+09:00"
}
```

完全なサンプルは [`examples/`](./examples/) を参照してください。

### ディレクトリ構成

```text
.
├─ README.md
├─ docs/                  … 設計ドキュメント一式（上表）
├─ examples/              … サンプルパケット（notify_done / notify_failed / notify_need_review / handoff_agent / report_agent）
├─ commands/              … コマンド定義（review / polish / triage / spec）
├─ server/                … FastAPI notify server（Phase 1 で実装）
├─ clients/
│  ├─ windows/            … Windows toast 通知クライアント（Phase 2.5）
│  ├─ web/                … Web UI（Phase 2）
│  └─ android/            … Android（Phase 4。まずはスマホブラウザ運用）
└─ tests/                 … スキーマ・API・ハンドオフのテスト（Phase 1〜）
```

（`server/` 以下は [`docs/roadmap.md`](./docs/roadmap.md) の Phase に沿って実装予定）

### 設計思想（要点）

* **人間は司令官、AIは部隊** — 人間は判断と優先度付けに集中し、実行はAIに委譲
* **直列は少数精鋭、並列は大量投入** — 重い思考は直列、小粒な作業は並列
* **状態は読むな、通知で受け取れ** — 「見に行く」運用を排除し、割り込み前提にする
* **切断は起きるものとして設計する** — 履歴・再送・ackで、見逃しをゼロにするのではなく回復可能にする

### ライセンス

本リポジトリの内容は、研究・学習・個人開発用途での利用を想定しています。
商用利用については各自の責任で判断してください。詳細は [LICENSE](./LICENSE) を参照。

---

## Overview (English)

This repository defines **MACP (Multi-Agent Command Protocol)** — a lightweight command and notification protocol that turns the outputs of multiple AI agents into a common JSON packet, so they can be delivered to humans (Windows / Android / Web UI) or handed off to other agents.

Instead of relying on a single all-purpose AI, this design assumes:

* Multiple role-specialized agents
* Asynchronous collaboration with a human commander
* Explicit AI-to-AI task handoff with loop prevention (`hop` / `max_hops`) and a confidence gate
* Notification-driven (interrupt-based) workflows, with **history and replay** (`Last-Event-ID` over SSE) so that disconnects and missed notifications are recoverable

### Goals

* Treat AI agents as **collaborative workers**, not tools
* Minimize human idle time (I/O wait)
* Enable safe and explicit agent-to-agent delegation
* Make agent state and confidence observable
* Deliver results to phones and PCs without babysitting a chat window

### Key Features

* Slash-command based control — canonical `/review` `/polish` `/triage` `/spec` (legacy persona-style names kept as aliases)
* Built-in AI-to-AI handoff fields
* Notification-first architecture with SSE replay for offline clients
* Confidence-based state signaling (`good` / `caution` / `bad` / `blocked` / `unknown`)
* Persona-agnostic core: machine summary (`summary`) and persona message (`agent_message`) are separate fields

### Documentation

All design documents live in [`docs/`](./docs/) (Japanese-first; see the table in the Japanese section above). Sample packets live in [`examples/`](./examples/), command definitions in [`commands/`](./commands/). Implementation follows the phased plan in [`docs/roadmap.md`](./docs/roadmap.md).

### Design Philosophy

* Humans act as commanders, not executors
* Parallelize aggressively, serialize deliberately
* Let notifications drive attention, not polling
* Design for disconnection: history, replay, and acknowledgement instead of "never miss anything"
