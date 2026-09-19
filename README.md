# 野球場・ソフトボール場 空き状況自動閲覧システム (さいたま市 & 埼玉県営公園)

[さいたま市公共施設予約システム](https://saitama.rsv.ws-scs.jp/web/)および[埼玉県県営公園施設予約サービス](https://saitama-pref-reserve.michi-shiru.jp/facilitysearchcondition)から、野球場・ソフトボール場の空き状況を定期的に自動収集し、GitHub Pages上でマトリクス形式で常時閲覧可能にするシステムです。

---

## 1. プロジェクト概要と検索条件

### 1.1 さいたま市公共施設予約システム（少年野球場 9グラウンド・全20面）
* **対象グラウンド**:
  1. 荒川総合運動公園 (5面)
  2. 八王子公園 (1面)
  3. 見沼臨時グラウンド (2面)
  4. 大間木公園 (4面)
  5. 浦和総合運動場 (2面)
  6. さくら草公園 (1面)
  7. 宝来運動公園 (2面)
  8. 西遊馬公園 (2面)
  9. 三橋総合公園 (1面)
* **特徴**: 午前・午後スロット対応、一部空き日の自動ドリルダウン詳細判定対応。

### 1.2 埼玉県営公園施設予約サービス（秋ヶ瀬公園・全7面）
* **対象施設**: 秋ヶ瀬公園（軟式野球場・ソフトボール場）
* **特徴**: 午前・午後スロット対応、抽選受付・空き状況のリアルタイム判定。

### 1.3 共通仕様
* **定期実行**: GitHub Actions（Ubuntu環境、cron定期実行）
* **データ公開**: `docs/data.json` および `docs/data_city.json` を出力・更新し、`docs/index.html`（GitHub Pages）で描画・常時公開（**日本の祝日・土日限定フィルタ、午前・午後別表示、明るい高密度レイアウト対応**）

---

## 2. ディレクトリ構成

```text
.
├── .github/
│   └── workflows/
│       └── scrape.yml        # GitHub Actions定期実行ワークフロー
├── scraper/
│   ├── requirements.txt      # Python依存パッケージ
│   ├── scrape.py             # 統括スクレイピング実行スクリプト (両対応)
│   └── saitama_city_scraper.py # さいたま市専用スクレイパー
├── docs/
│   ├── index.html            # 閲覧用Webダッシュボード (GitHub Pages)
│   ├── data.json             # 埼玉県営公園 収集データ
│   └── data_city.json        # さいたま市 収集データ
├── run_scraper.bat           # Windows用 ワンクリックデータ更新
├── start_server.bat          # Windows用 ワンクリックWeb表示
├── .gitignore                # Git除外設定
└── README.md                 # セットアップ＆実行手順
```


---

## 3. ローカル環境でのセットアップと実行手順

### 3.1 動作要件
* Python 3.10 以上
* Node.js / Playwright ブラウザ依存パッケージ

### 3.2 依存ライブラリのインストール
リポジトリ直下で以下のコマンドを実行します。

```bash
# Python依存パッケージのインストール
pip install -r scraper/requirements.txt

# Playwright用Chromiumブラウザのインストール
python -m playwright install chromium
```

### 3.3 スクレイピングのローカル実行
以下のコマンドでスクレイパーを実行し、最新の空き状況データを `docs/data.json` に出力・更新します。

```bash
python scraper/scrape.py
```

実行ログ例:
```text
[19:19:25] Starting Saitama Park Reservation Scraper...
Navigating to target site: https://saitama-pref-reserve.michi-shiru.jp/facilitysearchcondition
Selecting '音声読み上げ予約: 利用しない'...
Selecting '利用日: 月単位'...
Selecting '施設: 秋ヶ瀬公園'...
Selecting '利用目的: 軟式野球' & 'ソフトボール'...
Submitting search condition form...
Scrolling initial result set...
[19:19:36] Intercepted 150 availability slots
Clicking '次の室場を表示' to load remaining courts...
[19:19:40] Intercepted 60 availability slots
Clicking '後の期間 >' to load next month...
[19:19:44] Intercepted 217 availability slots

[SUCCESS] Successfully scraped 427 time slots!
[SUCCESS] Total available slots: 24
[SUCCESS] Saved data file to C:\mywork\playright1\docs\data.json
```

### 3.4 Web画面のローカルプレビュー
作成した bat ファイルをダブルクリックするか、コマンドでローカルWebサーバーを立ち上げて `docs/index.html` を確認します。

**バッチファイルでワンクリック起動（Windows）:**
- **`start_server.bat`**: ダブルクリックすると、Webサーバーを起動し自動的にブラウザで `http://localhost:8000` を開きます。
- **`run_scraper.bat`**: ダブルクリックするとスクレイピングを実行してデータを更新し、続けてサーバーを起動するか選択できます。

**コマンドラインで起動:**
```bash
# Pythonの簡易Webサーバーでdocsディレクトリを公開
python -m http.server 8000 --directory docs
```

ブラウザで `http://localhost:8000` にアクセスすると、収集した空き状況がマトリクス表で綺麗に表示されます。

---

## 4. GitHub Actions & GitHub Pages 設定手順

### 4.1 リポジトリ権限の設定 (GitHub Actions)
自動更新された `docs/data.json` をリポジトリに書き込むため、以下の設定を行ってください。

1. GitHubリポジトリの **Settings** > **Actions** > **General** を開く
2. **Workflow permissions** セクションで **Read and write permissions** を選択
3. **Save** をクリックして保存

### 4.2 GitHub Pages の公開設定
1. GitHubリポジトリの **Settings** > **Pages** を開く
2. **Build and deployment** の **Source** で **Deploy from a branch** を選択
3. **Branch** に `main`（または `master`）を選択し、フォルダに `/docs` を指定して **Save**
4. 数分後、提供された GitHub Pages URL（例: `https://<username>.github.io/<repository-name>/`）にて空き状況ダッシュボードが常時公開されます。

### 4.3 手動実行 (Workflow Dispatch)
定期実行（3時間ごと）を待たずに今すぐ最新データを取得したい場合は、GitHubの **Actions** タブ > **Scrape Saitama Park Reservation** ワークフローから **Run workflow** ボタンをクリックして即座にスクレイピングを実行できます。

---

## 5. ステータスコード定義

本システムでは埼玉県県営公園施設予約サービスのステータスコードを以下のようにマッピングしています。

| ステータスコード | 内容 | 記号 | 可否 |
| :--- | :--- | :---: | :---: |
| `1`, `7` | 空き・予約可能 / 一般開放 | **○** | **予約可** |
| `4` | 抽選受付中 | **△** | **抽選可** |
| `8`, `0`, `6` | 予約済 / ロック / 点検不可 | **×** | 不可 |
| `3`, `5` | 申込期間外 / 休場 | **-** / **休** | 不可 |
