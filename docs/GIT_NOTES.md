# Git 運用の注意点（今回つまずいた点まとめ）

## 1. `--trailer` が付いて `unknown option 'trailer'` で失敗する場合
今回 `git commit` が失敗した原因は、実行環境に `--trailer` を渡してしまうラッパー/設定が混ざり、古い Git 互換で `--trailer` が解釈できなかったことです。

### 回避策
- まずは「`--trailer` を付けない」形でコミットします（例: `git commit -m "..."`）。
- もしそれでも失敗する場合は、以下のラッパー経由でコミットしてください（`--trailer` を除去してから本体 `git.exe` を実行します）。
  - 例（PowerShell / 管理者権限不要）:
    - `powershell -NoProfile -ExecutionPolicy Bypass -File "C:\\Users\\chiyo\\bin\\git.ps1" commit -m "メッセージ"`

## 2. Push の認証で入力待ちになって失敗する
HTTPS で push すると、GitHub 認証のためにユーザー入力（Username 等）を求められて止まることがありました。

### 回避策（おすすめ）
- remote を SSH に切り替えます。
  - 例:
    - `git remote set-url origin git@github.com:huguchiyo/hotel_check.git`
    - `git push -u origin main`

## 3. secrets / ローカルデータを push しない
今回のプロジェクトは `.env` や `watch_selections.json` がローカル専用です。

### 対策
- `.gitignore` に以下が入っていることを確認してください。
  - `.env`
  - `watch_selections.json`
  - `tmp_*.json` / `tmp_*.txt` 等の作業ファイル

## 4. `git init` の前提
このディレクトリは最初 git 管理ではない（`.git/` が無い）状態でした。

### 初期化手順（再現用）
1. `git init`
2. `git add -A`
3. `git commit -m "初回コミット: ..."`
4. remote 設定（必要なら）
5. `git push`

## 5. 事前チェック（毎回これだけ）
- `git status` で、意図しないファイル（`.env` など）が staged / commit 対象になっていないこと
- `git log -1 --oneline` で、直近コミットが意図した内容になっていること

## 6. 今回（今回の環境）で使ったコマンド例

### 初回セットアップ（このディレクトリで初めて git を始める場合）
1. `git init`
2. `git add -A`
3. コミット（`--trailer` 問題を踏んだので、必要ならラッパー経由で実行）:
   - `powershell -NoProfile -ExecutionPolicy Bypass -File "C:\\Users\\chiyo\\bin\\git.ps1" commit -m "メッセージ"`
4. remote 設定（SSH 推奨）:
   - `git remote add origin "git@github.com:huguchiyo/hotel_check.git"`
   - 既に `origin` がある場合: `git remote set-url origin "git@github.com:huguchiyo/hotel_check.git"`
5. push:
   - `git push -u origin main`

### よくある確認コマンド
- `git status`
- `git diff --stat --cached`（コミット対象の内容サマリを見る）
- `git log -1 --oneline`

