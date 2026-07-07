# Android 側の注意点

過去試作は Android での表示・通知実装の段階で環境構築・起動不良により中断した。
本書はその再発を防ぐためのチェックリストである。**結論: 最初はアプリを作らない。**

## 1. 段階方針

| 段階 | 内容 | 通知 |
| --- | --- | --- |
| Phase 4a | スマホブラウザで Web UI を開く（実装ゼロ） | OS 通知なし。開けば未読が見える |
| Phase 4b | ネイティブアプリで**起動中のみ** SSE 受信 | ローカル通知（アプリ起動中） |
| Phase 6 | FCM 等の本格プッシュ | バックグラウンド通知（要クラウド） |

最初から FCM へ進むと設定項目が増えて詰まりやすい。**SSE またはポーリングから始める。**

## 2. 接続先アドレス（最初にハマるポイント)

| 環境 | サーバーの指定 |
| --- | --- |
| Android **エミュレータ** → PC 上のローカルサーバー | `http://10.0.2.2:8765`（エミュレータから見たホスト PC の特別アドレス。`localhost` はエミュレータ自身を指すため不可） |
| Android **実機** → PC（同一 LAN） | `http://<PCのLAN IP>:8765`（例 `http://192.168.1.20:8765`。`ipconfig` で確認） |

サーバー側の前提:

- `MACP_HOST=0.0.0.0` でバインドする（既定の `127.0.0.1` では LAN から届かない）
- Windows ファイアウォールでポート 8765 の受信許可を追加する
- 実機接続時は同一ネットワーク上の他端末からも見える。`MACP_TOKEN` を必ず設定する

## 3. Android アプリ実装時（Phase 4b）のチェックリスト

1. **cleartext HTTP**: Android 9+ は平文 HTTP が既定で禁止。開発用には
   `android:usesCleartextTraffic="true"`（または network security config で対象ホストのみ許可）が必要
2. **通知権限**: Android 13+ は `POST_NOTIFICATIONS` の実行時権限リクエストが必要。
   加えて `NotificationChannel` の作成（Android 8+）を忘れない
3. **SSE クライアント**: OkHttp の `okhttp-sse`（`EventSourceListener`）を使用。
   読み取りタイムアウトはハートビート間隔（15 秒）の 2 倍以上に設定する
4. **再接続**: `last_event_id` を `SharedPreferences` に保存し、再接続時に `Last-Event-ID` ヘッダで送る
   （取りこぼし分はサーバーが再送する。`transport.md` §5）
5. **フォアグラウンド限定**: 初期実装はアプリ起動中の受信のみ。Doze・バッテリー最適化との戦いは
   しない（それが必要になったら Phase 6 の FCM へ進むサイン）
6. **INTERNET 権限**: `<uses-permission android:name="android.permission.INTERNET" />`（基本だが忘れがち）

## 4. うまくいかないときの切り分け順序

```text
1. PC 自身のブラウザで  http://localhost:8765/api/health   → サーバー起動確認
2. PC 自身のブラウザで  http://<LAN IP>:8765/api/health    → バインド/FW 確認
3. スマホのブラウザで   http://<LAN IP>:8765/api/health    → LAN 到達確認
4. スマホのブラウザで   Web UI を開き SSE 受信を確認        → ここまで来ればアプリ以外は正常
5. アプリからの接続を試す（cleartext / 権限 / URL を見直す）
```

ステップ 4 まで（= Phase 4a）で日常運用は成立する。ステップ 5 で詰まっても運用は止まらない。
