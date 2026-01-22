# Multi-Agent Command Protocol

> **Japanese / English README**
> This repository documents a lightweight, persona-oriented command and notification protocol for orchestrating multiple AI agents in both parallel and serial workflows.

---

## 概要（日本語）

> ※本READMEは **Google / Big Tech（Research・Platform・Developer Productivity系）ポジション** を意識した構成になっています。

このリポジトリは、**複数のAIエージェント（人格AI）を並列・直列に統合運用するための軽量プロトコル**を定義したものです。

単一AIにすべてを任せるのではなく、

* 役割の異なる複数エージェント
* 人間（司令官）との非同期連携
* AI→AI ハンドオフ（引き継ぎ）
* OS通知・コマンド化による割り込み駆動

を前提とした、**2026年以降を見据えた実務向けマルチエージェント設計**を目的としています。

本設計は、いわゆる「超並列駆動（Boris式）」の思想を参考にしつつ、
人格AI・創作AI・研究AIを含む混成ネットワークに適用できるよう抽象化されています。

---

## 目的

* AIエージェントを「道具」ではなく**協調する作業者**として扱う
* 並列処理と直列処理を意図的に切り替える
* 人間の待ち時間（I/O Wait）を最小化する
* エージェント間の責任・状態・確信度を明示する

---

## 主な特徴

* **スラッシュコマンド型インターフェース**
  `/persona-action` 形式で誰に何を任せるかが一目で分かる

* **AI→AI ハンドオフ対応**
  エージェント同士がタスクを引き継ぐための必須フィールド定義

* **通知ファースト設計**
  OS / Web / Mobile 通知を前提とした状態可視化

* **確信度ベースの状態表現**
  好調 / 不調 / 要確認 を機械的に判定可能

* **人格非依存・人格適用両対応**
  無個性エージェントにも、強いキャラ性を持つ人格AIにも適用可能

---

## 想定ユースケース

* コーディング支援（実装・調査・レビューの分業）
* ポートフォリオ解析・整理
* 3Dアバター／モーションデータ調整
* RAG / Deep Research の非同期実行
* 創作AIと実務AIの混在運用

---

## ディレクトリ構成（例）

```
.
├─ specs/
│  ├─ command_protocol.md
│  ├─ task_types.md
│  ├─ notification_format.md
│  └─ ai_handoff_spec.md
├─ personas/
│  ├─ curren.md
│  └─ vega.md
├─ examples/
│  ├─ ai_to_ai_handoff.json
│  ├─ notify_user.json
│  └─ serial_task_example.json
└─ README.md
```

---

## 設計思想（要点）

* **人間は司令官、AIは部隊**
  人間は判断と優先度付けに集中し、実行はAIに委譲

* **直列は少数精鋭、並列は大量投入**
  重い思考は直列、小粒な作業は並列

* **状態は読むな、通知で受け取れ**
  「見に行く」運用を排除し、割り込み前提にする

---

## ライセンス

本リポジトリの内容は、研究・学習・個人開発用途での利用を想定しています。
商用利用については各自の責任で判断してください。

---

## Overview (English)

This repository defines a **lightweight command and notification protocol** for orchestrating multiple AI agents—both in parallel and in controlled serial workflows.

Instead of relying on a single all-purpose AI, this design assumes:

* Multiple role-specialized agents
* Asynchronous collaboration with a human commander
* Explicit AI-to-AI task handoff
* Notification-driven (interrupt-based) workflows

The protocol is inspired by modern “hyper-parallel” development practices and generalized for persona-based and non-persona agents alike.

---

## Goals

> This project is written with **Google-style roles** in mind: Developer Productivity, AI Infrastructure, Applied Research, and Platform Engineering.

* Treat AI agents as **collaborative workers**, not tools

* Minimize human idle time (I/O wait)

* Enable safe and explicit agent-to-agent delegation

* Make agent state and confidence observable

* Bridge research ideas with production-ready orchestration

* Treat AI agents as **collaborative workers**, not tools

* Minimize human idle time (I/O wait)

* Enable safe and explicit agent-to-agent delegation

* Make agent state and confidence observable

---

## Key Features

* Slash-command based control (`/persona-action`)
* Built-in AI-to-AI handoff fields
* Notification-first architecture
* Confidence-based state signaling
* Persona-agnostic core design

---

## Intended Use Cases

* Coding and refactoring pipelines
* Portfolio analysis and structuring
* 3D avatar / motion data adjustment
* Deep research and long-running tasks
* Hybrid creative + production AI workflows

---

## Design Philosophy

* Humans act as commanders, not executors
* Parallelize aggressively, serialize deliberately
* Let notifications drive attention, not polling

---

If you are exploring multi-agent AI systems in real-world environments, this repository provides a practical, extensible starting point.
