# これまでやったこと（実装まとめ）

## Rakuten API 側
- `VacantHotelSearch` / `KeywordHotelSearch` のクライアントを整備
- `accessKey` をクエリパラメータで渡す、`Referer`/`Origin` ヘッダを付与するよう修正
- 404（not_found）は「空結果」として扱うように変更
- レート制限（429）に対する待機・リトライを実装
- `VacantHotelSearch` の分割されたレスポンス（プラン/部屋情報と料金情報が別要素で返る）をマージ
- `hits=30` の制限に合わせてページングして結果を取得

## WebUI/検索結果表示
- チェックイン日未入力時の「日付レンジ探索 + フォールバック」を実装
- 検索実行中かどうかが分かるように、バックグラウンド実行＋進捗ログ表示を追加
- 結果は `planName` 単位でグルーピングし、内部は部屋名・料金でソート
- 表示できない項目（部屋タイプコード/広さ等）は隠す方針に整理

## 監視リスト & 定期通知
- WebUIの「監視に追加」で `watch_selections.json` に監視対象を保存
- `preferred_checkin_dates`（固定日）をカレンダー入力で追加
- 定期チェックは `watch_main.py` で実行（希望日ごとにピンポイント判定）
- 通知マッチングの安定性を確保するため、現状は `planId + mealText` を中心に照合

## LINE通知
- LINE Notify の終了を踏まえて、LINE Messaging API（Push）へ対応
- 通知本文に「予約入力画面へ飛べるURL（RsvInput.do）」を含めるよう改善

