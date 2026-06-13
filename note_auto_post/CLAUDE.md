# CLAUDE.md

このファイルは、本リポジトリのコードを扱う際の Claude Code（claude.ai/code）向けガイドです。

## 概要

Google Photos（または指定ローカルフォルダ）→ Claude で記事生成 → `note.com` / Notion / ブラウザ確認用 HTML へ出力する、写真起点の note 自動下書きパイプライン。エントリポイントは 3 つ：CLI (`main.py`)、ジョブ実行用 Web UI (`web_server.py`)、Notion 上のドラフトを公開するブログサーバー (`blog_server.py`)。

## 重要な不変条件（壊してはいけない）

リファクタ中に踏みやすい制約のクイックリファレンス。各項目は後続の該当セクションで詳述しているので、手を入れる前に必ずそちらを読むこと。

- **`[写真N]` プレースホルダーは Claude 出力 → 下書き / note / Notion / ブログを貫く共通契約** — `ai_processor` のプロンプトが生成し、`draft_generator` / `note_poster._parse_segments` / `notion_poster._parse_segments` / `blog_server._photo_filename` が同じ正規表現 `r'(\[写真\d+\])'` でパースする。記法を変えると 4 か所同時に壊れる。（→ *アーキテクチャ：写真プレースホルダーの契約*）
- **`google_photos.py`（API クライアント）は現在 `main.py` から呼ばれていない** — 実行経路は `google_photos_playwright.py`（Playwright + システム Chrome）。`credentials/credentials.json` / `token.json` は API 実装の名残で、削除しても通常フローは落ちないが両者を混同しないこと。（→ *既知のクセ / コードに見えるが違うもの*）
- **Claude モデル ID は `claude-sonnet-4-6` 固定** — `ai_processor.py:40`。System プロンプトに `cache_control: ephemeral` を付与しているので、モデルや system テキストを変えるとキャッシュヒットが落ちる。（→ *アーキテクチャ：Claude 呼び出し*）
- **`web_server` は `main.py` の標準出力テキストから URL / 下書きパスを正規表現で抽出する** — 「`下書き生成完了:`」「`editor.note.com`」「`notion.so/`」「`✅` + `note.com/`」のログ文言を変えると、Web UI 上の結果表示が黙って壊れる。（→ *アーキテクチャ：Web UI ジョブ実行*）
- **Notion への画像は実アップロードではなくプレースホルダー Callout** — `notion_poster._image_block` がファイル名を `code` annotation で埋め込み、`blog_server._photo_filename` が `(filename.jpg)` を抽出して `/img/{date}/{filename}` で配信する。Callout の color `blue_background` とファイル名表現はブログ側とペアで変える。（→ *アーキテクチャ：Notion 連携とブログ配信*）
- **`note_poster._paste` は macOS の `pbcopy` + `Meta+V` 依存** — テキスト本文は IME 経由ではなくクリップボード貼り付けで投入している。他 OS では動作しない／クリップボードを汚す副作用がある。（→ *既知のクセ / コードに見えるが違うもの*）
- **Playwright は `launch_persistent_context` + システム Chrome（`channel='chrome'`） + `navigator.webdriver` 隠蔽** — Google / note の自動化検出を回避するため。`headless=True` 化や引数の削除で検出され、ログインや写真選択が静かに失敗する。Google Photos 用 (`credentials/chrome_profile`) と note 用 (`credentials/note_profile`) のプロフィールは別ディレクトリで分離してある。（→ *アーキテクチャ：Playwright 周りの罠*）
- **オプショナル連携（Notion / note 自動投稿）は CLI フラグで明示した時だけ落ちる** — デフォルト `main.py` 実行では `NOTION_TOKEN` 未設定でも HTML 下書きまでは生成できる。`--notion` 指定時のみ `notion_poster` が `ValueError` を投げる設計。env チェックの早期 return を増やすときはこの境界を崩さない。（→ *環境変数*）
- **記述言語は日本語** — UI 文字列・ログ・コメントは日本語。既存スタイルに合わせる。

## コマンド

```bash
# CLI: 今日の Google Photos から下書き生成 → ブラウザで HTML を開く
python main.py

# 日付指定 / ローカルフォルダ指定
python main.py --date 2026-05-02
python main.py --folder ~/Downloads/my_photos --no-date-filter

# 生成後に外部送信
python main.py --post     # note.com に下書き保存
python main.py --notion   # Notion にドラフトページ作成

# Web UI（ジョブ実行）: LAN 公開
python web_server.py
# 外部公開（Cloudflare Quick Tunnel + Basic 認証）
python web_server.py --tunnel --password <パスワード>

# ブログサーバー（Notion 上のドラフトを公開閲覧）
python blog_server.py
python blog_server.py --tunnel --password <パスワード>

# 依存インストール（Playwright ブラウザは別途）
pip install -r requirements.txt
playwright install chromium
```

テストスイート・リンター・フォーマッターは未設定。動作検証は `debug_note.py` / `debug_gp.py`（実 DOM 構造調査用のスクラッチ）と、生成された `output/<日付>/draft_<日付>.html` の目視で行う。

## デプロイ

ローカル実行前提。外部公開する場合は `--tunnel` で Cloudflare Quick Tunnel を起動し、`trycloudflare.com` のドメインを取得する（`cloudflared` を `brew install cloudflare/cloudflare/cloudflared` で入れておく必要あり）。Basic 認証は `--password` で有効化、未指定なら認証なし。

## 環境変数

`.env`（リポジトリ直下）に記述。`config.py` が `python-dotenv` 経由で読み込む。

| 変数 | 用途 |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude API キー。**未設定だと `main.py` は即終了する**。 |
| `NOTE_EMAIL` | note.com 自動ログイン用メール。未設定でもブラウザで手動ログインに切り替えられる。 |
| `NOTE_PASSWORD` | note.com 自動ログイン用パスワード。同上。 |
| `NOTE_URL` | デフォルト `https://note.com`（現状コード内ではほぼ参照されていない）。 |
| `NOTION_TOKEN` | Notion インテグレーションのシークレット。`--notion` / `blog_server` 起動時に必要。未設定なら `notion_poster.post_to_notion` が `ValueError`。 |
| `NOTION_ARTICLES_PARENT_ID` | 記事ドラフトを子ページとして作成する親ページ ID。`blog_server` の記事一覧元にもなる。 |

| サービス | 用途 | 必要な env |
| --- | --- | --- |
| Anthropic Claude | 記事本文・タイトル・タグ生成 | `ANTHROPIC_API_KEY` — 未設定なら `main.py` 即終了 |
| Google Photos (Playwright) | 日付検索 → ZIP 一括ダウンロード | env ではなく `credentials/chrome_profile`（ログイン済み状態を永続化） |
| note.com (Playwright) | 下書き保存 / タグ設定 | `NOTE_EMAIL`, `NOTE_PASSWORD`（手動ログインも可）+ `credentials/note_profile` |
| Notion API | ドラフトページ作成 / ブログ配信 | `NOTION_TOKEN`, `NOTION_ARTICLES_PARENT_ID` — `--notion` 時のみ必須 |
| Cloudflare Tunnel | Web UI / ブログサーバーの外部公開 | `cloudflared` CLI が PATH にあること |
| Nominatim (OpenStreetMap) | EXIF GPS → 地名の逆ジオコーディング | 不要（user-agent 固定で外部呼び出し） |

## プロジェクト構成

| パス | 役割 |
| --- | --- |
| `main.py` | CLI エントリ。引数を解釈し、Photos 取得 → Claude 生成 → 下書き HTML 出力 → 任意で `--post` / `--notion` を呼ぶ。 |
| `config.py` | `.env` 読み込みと `BASE_DIR` / `CREDENTIALS_DIR` / `OUTPUT_DIR` / `SCOPES` 定義。 |
| `ai_processor.py` | Claude 呼び出し本体。画像を最大 10 枚 / 1568px に縮小して送る。JSON のみ返させる system プロンプトと壊れた JSON の補修。 |
| `draft_generator.py` | Claude 出力 + 画像から、サイドバーつきの確認用 HTML を `output/<日付>/draft_<日付>.html` に書き出す。 |
| `google_photos_playwright.py` | **現行の写真取得経路**。Chrome を立ち上げ Google Photos を日本語日付で検索 → 全選択 → Shift+D / 三点メニューから ZIP ダウンロード → 連番リネームで展開。 |
| `google_photos.py` | Google Photos Library API クライアントの旧実装。`main.py` からは現在呼ばれていない（→ *既知のクセ*）。 |
| `local_photos.py` | `--folder` 指定時に EXIF 撮影日でフィルタしつつ画像 / 動画を読み込む。 |
| `location.py` | Nominatim による逆ジオコーディング。観光地 → 街区 → 市区町村の優先順で 1 つの地名キーを返す。LRU キャッシュ + タイムアウト時 1 回リトライ。 |
| `note_poster.py` | Playwright で note.com にログインし、本文 → 画像 → タグ → 下書き保存の順で UI を操作する。 |
| `notion_poster.py` | Notion API 経由でドラフトページ作成。画像は実アップロードせずファイル名つき Callout で代用。 |
| `web_server.py` | FastAPI。`main.py` をサブプロセス起動 → 標準出力を SSE でブラウザに流す。Basic 認証 + Cloudflare Tunnel オプション。 |
| `blog_server.py` | FastAPI。`NOTION_ARTICLES_PARENT_ID` 直下の子ページを記事リスト化し、Notion ブロックを HTML に変換して公開する。画像は `output/<日付>/` から `/img/{date}/{filename}` で配信。 |
| `web_static/index.html` | Web UI のフロント（FastAPI から直接配信）。 |
| `credentials/` | Google Photos / note.com の永続化された Chrome プロフィールと、旧 API 実装用の `credentials.json` / `token.json` を同居させている。`.gitignore` 済み。 |
| `output/<YYYY-MM-DD>/` | 日付ごとの生成物（写真連番ファイル + `draft_<日付>.html`）。`blog_server` の `/img/` がここを直接読む。 |
| `output/debug` / `output/debug_note` | `debug_gp.py` / `debug_note.py` の出力先（DOM 調査用）。 |
| `debug_gp.py` / `debug_note.py` | Google Photos / note.com の DOM 構造を手動調査するスクラッチ。本番フローからは呼ばれない。 |
| `requirements.txt` | 依存固定。`anthropic` / `fastapi` / `uvicorn` / `playwright` / Google 認証 / `Pillow` / `piexif` / `geopy` / `python-dotenv`。 |

## アーキテクチャ

### パイプライン全体

```
[Google Photos 検索 or ローカルフォルダ]
    └→ photos[] / videos[]（local_path・EXIF 緯度経度）
        └→ location.reverse_geocode で place を埋める
            └→ ai_processor.generate_post  …  Claude にテキスト + 画像で JSON を返させる
                └→ post = {title, body([写真N] 入り), tags}
                    ├→ draft_generator.generate_draft → output/<日付>/draft_<日付>.html
                    ├→ note_poster.post_draft        → note.com の下書き
                    └→ notion_poster.post_to_notion → Notion ドラフトページ
```

`web_server.py` はこの CLI を `subprocess.Popen` で起動し、標準出力行を SSE 経由でブラウザに流すラッパー。`blog_server.py` はパイプラインに参加せず、Notion 上に保存済みのドラフトを公開閲覧するための独立サーバー。

### 写真プレースホルダーの契約

`ai_processor._prompt` は Claude に「写真の挿入位置は `[写真1][写真2]...` のプレースホルダーで示すこと」と要求する。`body` の中の `[写真N]` は以下 4 か所で同じ正規表現 `r'(\[写真\d+\])'` によって分割・解釈される：

- `draft_generator._body_to_html` … `<figure><img>` に置換。
- `note_poster._parse_segments` … `{type: photo, path, idx}` のセグメントに分割して画像挿入 UI を駆動。
- `notion_poster._parse_segments` … Notion ブロック化。
- `blog_server._photo_filename` … プレースホルダー Callout からファイル名を抜き出す。

`N` は 1 始まりで、`sendable` 配列（`local_path` が存在する画像のみ）のインデックスと対応する。`google_photos_playwright._extract_zip` で `{i+1:02d}_{name}` の連番にリネームしているのは、ここの番号と一致させるため。

### Claude 呼び出し

- モデル: `claude-sonnet-4-6`（`ai_processor.py:40`）。
- 画像: `MAX_PHOTOS = 10` 枚まで、長辺 `MAX_PX = 1568` で `PIL` で再エンコード（JPEG 85）してから base64。
- System: 「JSON のみで回答」を強制 + `cache_control: ephemeral`。
- 復元: `_parse_json` は最初の `{` と最後の `}` を切り出し、文字列リテラル内の生改行を `\n` にエスケープしてから `json.loads`。Claude が稀に文字列内で改行を吐いても通すための歴史的な後処理なので、シンプルな `json.loads(raw)` への置換は壊れる入力で再発する。

### Google Photos 自動取得（Playwright）

- 検索ワードは日本語の `YYYY年M月D日`（ゼロ埋めなし）。検索 API がない代わりに UI 経由。
- 写真セルは `div[role="checkbox"][aria-label*="写真 - "]`（または英語 `Photo - `）。チェックボックスは常時表示なのでホバー不要。
- 「全選択」は最初の写真クリック → Shift + 最後の写真クリック。
- ダウンロードはまず `Shift+D`、失敗時は三点メニューの「ダウンロード」を JS から直接 `click()`（ロケータ→クリックの 2 段だと先にメニューが閉じてしまうため）。
- ダウンロードタイムアウトは 180 秒（Takeout 経由になる場合がある）。`web_mode=True` のときはユーザー入力プロンプトを 5 秒間隔のポーリングに切り替える。

### note.com 投稿（Playwright）

- 永続コンテキスト `credentials/note_profile` に Cookie を残し、2 回目以降のログインをスキップ。
- 本文は `_paste` がテキストを `pbcopy` で macOS クリップボードに入れ、`Meta+V` で貼り付ける。これは ProseMirror 上での IME 衝突を避けるための実装で、`page.keyboard.type` への単純置換は壊れる。
- 画像挿入後にトリミングモーダルが出る場合は「保存」ボタンを `evaluate` で直接 click（ReactModal の overlay が pointer-events を奪うため、Playwright の通常クリックでは届かない）。
- タグは「公開に進む」パネルを開いた状態で `input[placeholder*="タグ"]` に `type` + `Enter` を 1 つずつ。最大 5 個。
- 最終的には公開せず「下書き保存」ボタンで終了。

### Notion 連携とブログ配信

- `notion_poster.post_to_notion` はページタイトルにアイコン 📒、本文先頭に `📅 YYYY年MM月DD日` と `#タグ` の Callout、`divider` を挟んで本文。
- 写真は **`callout` ブロックで `color: blue_background`**、`rich_text` に `写真N — `（bold）と `filename`（code）。これは Notion API の File Upload が未公開だった当時の代替実装。`blog_server._blocks_to_html` は `color == 'blue_background'` の callout を `<figure><img src="/img/{date}/{filename}">` に置換する。
- Notion の rich_text は 1 ノード 2000 文字制限。`_text_to_paragraphs` は行ごと → 2000 文字ごとに分割する。
- 1 リクエスト 100 ブロックまで。`_append_blocks` で残りを `PATCH` する。
- Notion API バージョンは `2022-06-28` 固定。

### Web UI ジョブ実行

- `/api/run` は `main.py` を `--web` 付きでサブプロセス起動。`--web` フラグは `main.py` 内の `input()` プロンプトをスキップさせ、`open` での自動ブラウザ起動も抑止する。
- `/api/logs/{job_id}` は SSE。`stdout` をリアルタイムにブラウザへ流しつつ、行内に `下書き生成完了:` / `editor.note.com` / `notion.so/` / `note.com/` ＋ `✅` を見つけたら `result_url` / `draft_path` に記録し、終端の `data: {done: true, ...}` に同梱する。**これらのログ文字列を変えるとブラウザ側の結果表示が黙って壊れる**。
- Basic 認証は `--password` 指定時のみ有効化。グローバル変数 `_password` が空なら middleware は素通し。

### Playwright 周りの罠

- 必ず `launch_persistent_context` + `channel='chrome'`（システム Chrome）。`launch` で Chromium を使うと Google のログイン UI で `accounts.google.com` がリダイレクトループに陥ることがある。
- `--disable-blink-features=AutomationControlled` と `navigator.webdriver` プロパティ削除の init script は必須。片方欠けると Google Photos がレイアウト崩壊する。
- `headless=False` 前提。`headless=True` 化は UI 構造が変わって写真セルが検出できなくなる。

## 既知のクセ / コードに見えるが違うもの

- **`google_photos.py` は旧 API 実装で現行フローから呼ばれていない** — `main.py` は `from google_photos_playwright import download_photos` を直接使う。`config.SCOPES` / `config.CREDENTIALS_FILE` / `config.TOKEN_FILE` も同様に旧実装の遺物。`credentials/credentials.json` と `credentials/token.json` を消しても Playwright フローは動く。完全削除には抵抗なく踏み切ってよいが、`google_photos.py` を残したまま中身を「現役」っぽく扱わないこと。
- **`debug_gp.py` / `debug_note.py` は本番経路に含まれない** — 既存の起動中 Chrome に CDP（`localhost:9222`）で接続したり、空ページで DOM 構造を吐き出すための調査スクリプト。動かないように見えても本番には影響しない。
- **`output/` 配下は run ごとの生成物 + ブログ配信ソースを兼ねる** — `blog_server` の `/img/{date}/{filename}` は `output/<date>/` を直接読むので、`output/` を「キャッシュ」扱いで雑に消すとブログ記事の画像が落ちる。`debug` / `debug_note` サブディレクトリだけはデバッグ用。
- **`note_poster._paste` と `subprocess.run(['open', ...])` は macOS 専用** — 前者は `pbcopy`、後者は macOS の `open` コマンドに依存。Linux/Windows 移植時は両方差し替える必要がある（`--web` モードでは `open` の方は呼ばれない）。
- **`config.NOTE_URL` はほぼデッドコード** — 定義はあるが本番経路で参照されていない。削っても挙動は変わらない見込みだが、参照箇所のないことを `grep` で確認してから消すこと。
- **Notion 画像「アップロード」の TODO** — `notion_poster._image_block` のコメントに「画像アップロード API は現時点で未公開」とある。仕様変更で `/v1/file-uploads` が一般化したらここを差し替えると同時に、`blog_server._blocks_to_html` の `blue_background` 分岐も `image` ブロック対応に書き換える必要がある（両側ペア）。
