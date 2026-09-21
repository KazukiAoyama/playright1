# 埼玉県営公園（秋ヶ瀬公園）オンタイム取得用 Cloudflare Worker

埼玉県営公園施設予約サービス（秋ヶ瀬公園）の予約枠を、ブラウザやGitHub Pagesから直接オンタイム（リアルタイム）で取得するための中継エッジワーカーです。

## 主な機能
- **CORS 解除**: 任意のオリジン（GitHub Pages やローカル環境）からのアクセスを許可
- **Origin 検証のバイパス**: Direct API が要求する `Origin: https://saitama-pref-reserve.michi-shiru.jp` をエッジで自動付与
- **オンタイム一括取得**: エッジからDirect APIを高速並行実行し、約1〜2秒で整形済みJSONを返却
- **無料枠制限クリア**: サブリクエスト制限（50件）を安全に回避する分割取得パラメータ（`?days=30&offset=0`）対応

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

## デプロイ後のWeb画面への反映
発行された Worker の URL を、`docs/index.html` の `CLOUDFLARE_WORKER_URL` に設定することで、GitHub Pages 上で「**県(即時): HH:mm**」のオンタイム取得が完全動作するようになります。
