# 楽天トラベル ホテル空室監視ツール

指定したホテル・宿泊日・人数・プラン条件で、楽天トラベルに空室が出たら **LINE（Messaging API）** または **メール** で通知するプログラムです。  
**GitHub Actions** のスケジュール実行で定期チェックできます。

## 機能

- 楽天トラベル **空室検索API** で指定施設・日付・人数の空室をチェック
- 条件に合うプランが1件でもあれば通知（プラン名のキーワード絞り込み対応）
- 通知先: **LINE（Messaging API）**（推奨）、**メール**（SMTP）
- 定期実行: **GitHub Actions** の cron で 1日3回（8:00 / 12:00 / 18:00 JST 想定）または手動実行

## 必要なもの

1. **楽天ウェブサービス** のアプリ登録  
   - [Rakuten Web Service](https://webservice.rakuten.co.jp/) にログイン  
   - アプリを登録して **アプリID** と **アクセスキー** を取得  
   - [空室検索API ドキュメント](https://webservice.rakuten.co.jp/documentation/vacant-hotel-search)

2. **楽天トラベルの施設番号（ホテル番号）**  
   - 予約したいホテルのページURLや検索結果から施設番号を確認（例: `123456`）  
   - 複数施設を指定する場合はカンマ区切り（例: `123456,789012`）

3. **LINE（Messaging API）設定**（推奨）  
   - LINE Developers で作成した Channel の **Channel access token** を用意する  
   - 通知の送信先（個人なら `userId`、グループなら `groupId`）を用意する  
   - ※LINE Notify は 2025/03/31 に終了しています（代替として Messaging API を利用します）。  
     [LINE Notify 終了案内](https://notify-bot.line.me/ja/)  

4. （任意）メール通知用の SMTP 設定（Gmail の場合はアプリパスワードなど）

## ローカルでの使い方

### 1. リポジトリのクローン & 依存関係

```bash
cd rakuten-hotel-monitor
pip install -r requirements.txt
```

### 2. 環境変数の設定

`.env.example` をコピーして `.env` を作成し、値を埋めます。

```bash
cp .env.example .env
```

**.env の例**

```env
RAKUTEN_APPLICATION_ID=あなたのアプリID
RAKUTEN_ACCESS_KEY=あなたのアクセスキー
LINE_CHANNEL_ACCESS_TOKEN=あなたのLINE Channel access token
LINE_TO_USER_ID=あなたの送信先 userId（または groupId）

# 検索条件（必須）
SEARCH_HOTEL_NO=123456
SEARCH_CHECKIN_DATE=2025-03-01
SEARCH_CHECKOUT_DATE=2025-03-02
SEARCH_ADULT_NUM=2
SEARCH_ROOM_NUM=1

# 任意: プラン名に「朝食」が含まれるものだけ
SEARCH_PLAN_KEYWORD=朝食
# 任意: 1室あたりの上限金額（円）
SEARCH_MAX_CHARGE=50000
```

### 3. 実行（コマンドライン）

```bash
python main.py
```

空室がある場合、LINE（またはメール）に通知が送られます。空室がなければ何も送信されず、メッセージだけ表示されます。

### 4. Web UI でローカル検索（任意）

ブラウザから条件を入力して API を試せます（**127.0.0.1 のみ**で待ち受け。楽天キーは `.env` から読み込み）。

```bash
python webapp.py
```

ターミナルに表示された URL（既定は `http://127.0.0.1:5000/`）を開き、条件を指定して「空室を検索」を押します。  
初回表示のデフォルト値は `.env` の `SEARCH_*` です。

- **施設の指定**: ホテル名の一部（2文字以上）でキーワード検索し、候補リストから選択できます（[楽天トラベル キーワード検索API](https://webservice.rakuten.co.jp/documentation/keyword-hotel-search)）。施設番号が分かっている場合は「直接入力」でも可。
- 任意: `RAKUTEN_AFFILIATE_ID`（アプリ一覧のアフィリエイトID。キーワード検索のリクエストに付与するとアフィリエイト付き URL が返る場合があります）
- 任意: `FLASK_SECRET_KEY`（未設定時は開発用の固定値）
- 任意: `WEBAPP_HOST` / `WEBAPP_PORT`（既定 `127.0.0.1` / `5000`）

### 5. WebUIで登録した「監視リスト」を通知する（任意）
WebUIで「監視に追加」すると、`watch_selections.json` に監視対象（プラン＋部屋＋希望チェックイン日）が保存されます。

定期チェック/通知は `watch_main.py` で行います。

```bash
python watch_main.py
```

`watch_selections.json` は `.gitignore` に含まれるため、GitHubには push されません（ローカル運用向け）。

## GitHub Actions で定期実行する

### 1. リポジトリを GitHub に push

このフォルダをそのまま新しいリポジトリとして push するか、既存リポジトリに追加します。

### 2. Secrets の設定

リポジトリの **Settings → Secrets and variables → Actions** で、以下の **Secrets** を追加します。

| Secret 名 | 説明 |
|-----------|------|
| `RAKUTEN_APPLICATION_ID` | 楽天ウェブサービスのアプリID |
| `RAKUTEN_ACCESS_KEY` | 楽天ウェブサービスのアクセスキー |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API の Channel access token |
| `LINE_TO_USER_ID` | 送信先 userId（または groupId） |
| `SEARCH_HOTEL_NO` | 施設番号（複数はカンマ区切り） |
| `SEARCH_CHECKIN_DATE` | チェックイン日（YYYY-MM-DD） |
| `SEARCH_CHECKOUT_DATE` | チェックアウト日（YYYY-MM-DD） |
| `SEARCH_ADULT_NUM` | 大人の人数（省略時は 2） |
| `SEARCH_ROOM_NUM` | 部屋数（省略時は 1） |
| `SEARCH_PLAN_KEYWORD` | （任意）プラン名のキーワード |
| `SEARCH_MAX_CHARGE` | （任意）上限金額（円） |

メール通知を使う場合は、以下も Secrets に追加します。

- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFY_EMAIL`

そのうえで、`.github/workflows/check-vacancy.yml` の `env` にこれらを追加してください。

### 3. スケジュール

`.github/workflows/check-vacancy.yml` の `schedule` で実行時刻を指定しています（UTC）。  
デフォルトは次の 3 回です（日本時間の目安）:

- `0 23 * * *` → 日本時間 8:00 頃
- `0 3 * * *` → 日本時間 12:00 頃  
- `0 9 * * *` → 日本時間 18:00 頃

cron の編集方法は [GitHub のドキュメント](https://docs.github.com/ja/actions/using-workflows/events-that-trigger-workflows#schedule) を参照してください。

### 4. 手動実行

**Actions** タブ → 「楽天トラベル空室チェック」ワークフロー → **Run workflow** で手動実行できます。

## 環境変数一覧

| 変数名 | 必須 | 説明 |
|--------|------|------|
| `RAKUTEN_APPLICATION_ID` | ✅ | 楽天API アプリID |
| `RAKUTEN_ACCESS_KEY` | ✅ | 楽天API アクセスキー |
| `SEARCH_HOTEL_NO` | ✅ | 施設番号（カンマ区切りで複数可） |
| `SEARCH_CHECKIN_DATE` | ✅ | チェックイン日（YYYY-MM-DD） |
| `SEARCH_CHECKOUT_DATE` | ✅ | チェックアウト日（YYYY-MM-DD） |
| `SEARCH_ADULT_NUM` | | 大人の人数（既定: 2） |
| `SEARCH_ROOM_NUM` | | 部屋数（既定: 1） |
| `SEARCH_PLAN_KEYWORD` | | プラン名の部分一致キーワード |
| `SEARCH_MAX_CHARGE` | | 上限金額（円） |
| `LINE_CHANNEL_ACCESS_TOKEN` | * | LINE Messaging API の Channel access token |
| `LINE_TO_USER_ID` | * | 送信先 userId（または groupId） |
| `SMTP_*` / `NOTIFY_EMAIL` | * | メール通知用（任意） |

* 通知は LINE（Messaging API）かメールのどちらか（または両方）が設定されていれば送信されます。

## 注意事項

- 楽天API は短時間に同じリクエストを連打すると制限される場合があります。定期実行は 1 日数回程度にしておくことを推奨します。
- 施設番号は楽天トラベルのホテル詳細ページのURLなどから確認できます。
- （Messaging API の）送信制限は LINE 側の仕様に従います。

## ライセンス

MIT
