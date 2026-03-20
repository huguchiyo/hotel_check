# 運用手順

## 通知経路（LINE）
`.env` に以下を設定してください。

- `LINE_CHANNEL_ACCESS_TOKEN`（Messaging API の Channel access token）
- `LINE_TO_USER_ID`（個人の `userId` またはグループの `groupId`）

## メール通知（任意）
- SMTP 設定（`SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD`）
- `NOTIFY_EMAIL`

## WebUIの使い方（監視登録）
1. `python webapp.py` で起動し、ローカルWebUIを開く
2. チェックイン日を未入力にして「空室を検索」
3. 表示された「プラン＋部屋（食事条件）」から、監視したい行をチェック
4. そのあと「希望チェックイン日（固定日）」をカレンダーで指定し、「選択したプランを監視に追加」

## 定期チェック（通知テスト含む）
- `python watch_main.py` を手動で実行
- 定期運用は GitHub Actions のワークフロー（別途追加）を想定

