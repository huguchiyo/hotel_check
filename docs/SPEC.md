# 仕様概要（空室監視 & 通知）

## 目的
指定ホテルについて、楽天トラベルの空室検索APIを使って「空きが出たプラン」を検出し、通知（LINE Messaging API / メール）します。

## データフロー
1. WebUIで検索（チェックイン日未定も可）
2. 表示された「プラン＋部屋（＋食事条件）」から監視したいものを選択
3. 希望チェックイン日（固定日）を指定し、監視リストに保存
4. 定期実行（`watch_main.py`）で希望日ごとに再検索し、合致したものが見つかったら通知

## WebUI（`webapp.py` / `templates/index.html`）
- チェックイン日が未入力の場合は日付レンジ（まず `今日+75〜今日+90`、空なら `今日+60〜今日+90` かつ週末含む）でプラン一覧を取得します。
- 監視に追加したい行（プラン＋部屋＋食事条件）はチェックボックスで選択し、`watch_selections.json` に保存します。
- 「希望チェックイン日」は固定日として、カレンダー入力（複数可）で保存します。

## 監視リスト保存（`watch_storage.py`）
- 保存先: `watch_selections.json`（`.gitignore` で無視）
- 保存キー: `hotelNo|planId|roomClass|mealText`
- 画面表示用情報: `planName` / `roomName`

## 定期チェック（`watch_main.py`）
- `watch_selections.json` を読み込み、希望チェックイン日（固定日）ごとに `run_vacancy_check_date_range()` を実行します（固定日なので `start_date=end_date`）。
- 429レート制限が出た場合は再試行します。
- 直近の通知はクールダウン（デフォルト24時間）で抑制します。

### 通知マッチングキー（重要）
- 先に確かめた通り、同一 `planId` でも `roomClass/roomName` が日付で揺れる場合がありました。
- そのため、通知マッチングは **`planId + mealText`** を基準にしています（暫定方針）。

## 通知（`notify.py`）
- LINE: Messaging API（Push）で `予約できるURL` を各プラン行に出力します。
- メール: SMTP 送信（設定されている場合のみ）。

