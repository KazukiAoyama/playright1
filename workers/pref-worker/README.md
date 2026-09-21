# 埼玉県営公園（秋ヶ瀬公園）オンタイム取得用 Cloudflare Worker

埼玉県営公園施設予約サービス（秋ヶ瀬公園）の予約枠を、ブラウザやGitHub Pagesから直接オンタイム（リアルタイム）で取得するための中継エッジワーカーです。

## 主な機能
- **CORS 解除**: 任意のオリジン（GitHub Pages やローカル環境）からのアクセスを許可
- **Origin 検証のバイパス**: Direct API が要求する `Origin: https://saitama-pref-reserve.michi-shiru.jp` をエッジで自動付与
- **オンタイム一括取得**: エッジからDirect APIを高速並行実行し、約1〜2秒で整形済みJSONを返却
- **無料枠制限クリア**: サブリクエスト制限（50件）を安全に回避する分割取得パラメータ（`?days=30&offset=0`）対応
- **【NEW】GitHub Actions 定期実行 Cron Triggers**: GitHub Actions 組み込みcronの遅延・スキップ問題を解消するため、Cloudflareから定刻（JST 06:08〜22:38、30分ごと）に GitHub API（workflow_dispatch）を高精度トリガー

---

## デプロイ手順

### 方法1: Cloudflare ダッシュボードから自動デプロイ（推奨・簡単）
1. [Cloudflare ダッシュボード](https://dash.cloudflare.com/) にログイン
2. 左メニュー **「Workers & Pages」** > **「Create application」** をクリック
3. **「Pages」** タブではなく **「Workers」** で作成、または GitHub 連携リポジトリから本リポジトリを選択
4. ルートディレクトリを `workers/pref-worker` に指定してデプロイ
5. デプロイ完了後、発行された URL（例: `https://saitama-pref-reservation-worker.<your-subdomain>.workers.dev`）を取得

### 方法2: Wrangler CLI でワンコマンドデプロイ
リポジトリ直下または `workers/pref-worker` ディレクトリで以下を実行します：

```bash
cd workers/pref-worker
npx wrangler login
npx wrangler deploy
```

---

## GitHub Actions 定期実行（Cron Triggers）のシークレット設定

本 Worker から GitHub Actions の `scrape.yml` をキックするために、GitHub の Personal Access Token (PAT) を登録します。

### 1. GitHub PAT の作成
1. GitHub の **[Settings] -> [Developer Settings] -> [Personal access tokens] -> [Fine-grained tokens]**（または Classic）を開く
2. **Generate new token** をクリック
3. リポジトリへのアクセス対象として **`KazukiAoyama/playright1`** を選択
4. 権限設定（Permissions）:
   - **Actions**: `Read and write`（ワークフローの起動に必要）
5. 生成されたトークン（`github_pat_...` または `ghp_...`）をコピー

### 2. Cloudflare Worker にシークレットを登録
以下のいずれかで登録します：

**方法 A (CLI):**
```bash
cd workers/pref-worker
npx wrangler secret put GITHUB_PAT
# プロンプトが表示されたらコピーしたトークンを貼り付け
```

**方法 B (Cloudflare ダッシュボード):**
1. 対象の Worker（`saitama-pref-reservation-worker`）を開く
2. **[Settings]** -> **[Variables and Secrets]** を開く
3. **Add** を押し、Type を **Secret**、Name を `GITHUB_PAT`、Value にトークンを貼り付けて保存

### 3. 動作テスト（手動キック）
Worker の URL に `/trigger-scrape` を付けてブラウザまたは curl でアクセスすると、GitHub Actions が即座に起動するかテストできます：
- 通常判定でキック: `https://<your-worker>.workers.dev/trigger-scrape`
- 強制実行（強制スクレイピング）: `https://<your-worker>.workers.dev/trigger-scrape?force=true`

---

## デプロイ後のWeb画面への反映
発行された Worker の URL を、`docs/index.html` の `CLOUDFLARE_WORKER_URL` に設定することで、GitHub Pages 上で「**県(即時): HH:mm**」のオンタイム取得が完全動作するようになります。

