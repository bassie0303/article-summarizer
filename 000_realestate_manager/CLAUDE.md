# CLAUDE.md

このファイルは、本リポジトリのコードを扱う際の Claude Code（claude.ai/code）向けガイドです。

## 概要

Gmail（ラベル「不動産物件」）と LINE Bot から不動産投資物件のメッセージを受け取り、Claude API で構造化抽出して Google Sheets に蓄積する Google Apps Script（GAS）プロジェクト。エントリポイントは `Code.gs` の `runAll()`（30分トリガー）・`doGet()`（手動入力フォーム）・`doPost()`（LINE Webhook）の3系統。

## 重要な不変条件（壊してはいけない）

リファクタ中に踏みやすい制約のクイックリファレンス。各項目は後続の該当セクションで詳述しているので、手を入れる前に必ずそちらを読むこと。

- **`Config.gs` の `COLUMNS` 配列と `SheetsWriter.appendProperty` の `appendRow` 順序は一対一対応** — 列の順序や追加は両方を同時に変更しないと列ずれが起きる。既存シートのヘッダーは初回作成時にしか書かれないため、列追加では既存シートの手動更新も必要。（→ *Sheets 列スキーマと書き込みの一対一対応*）
- **LINE Webhook 認証は HMAC ではなく `?secret=` クエリパラメータ** — GAS の `doPost` では HTTP ヘッダーが取得できないため。URL 形式を変えると認証が通らなくなる。（→ *LINE Webhook の制約*）
- **`doPost` は常に HTTP 200 + `{ status: "ok" }` を返す** — 認証失敗・パース失敗・処理例外でもステータスは 200。LINE 側の Webhook 検証と整合させるため。（→ *LINE Webhook の制約*）
- **Claude モデル ID は `claude-haiku-4-5`（`ClaudeAPI.gs:35`）** — 古い ID には戻さない。`max_tokens: 1000` と本文 4000 文字スライス（`text.slice(0, 4000)`）も意図的なコスト/レイテンシ調整。
- **物件名 / 所在地 / 価格 がすべて空のときだけスキップ** — `GmailProcessor._processMessage` と `LineWebhook._processLineMessage` の両方に同じ判定がある。判定キーや論理を変える場合は両方揃えること。
- **Web App のアクセス権は `ANYONE_ANONYMOUS`** — LINE Webhook を受けるための必須設定（`appsscript.json`）。閉じると Bot が止まる。
- **重複チェックは `受信メールURL` 列のみ** — Gmail 経由のみ重複排除（`isAlreadySaved`）。LINE 経由は同じ内容を何度送っても重複保存される。
- **`Config.gs` の `GEMINI_API_KEY` getter はどこからも参照されていない** — Script Properties に値が入っていても無視される。Gemini への切り替え途中で残った定数。（→ *コードに見えるが違うもの*）
- **記述言語は日本語** — UI 文字列・コメント・Logger・ステータス値（`検討中` 等）はすべて日本語。既存スタイルに合わせる。

## コマンド

GAS プロジェクトのため、ローカルでのビルド・実行コマンドはない。各 `.gs` / `.html` ファイルを GAS エディタにコピペし、以下を GAS エディタ上の関数実行で行う。

```text
# 初回セットアップ（シート作成 + 30分トリガー登録）
setup()                 # Code.gs

# Gmail ラベル「不動産物件」を作成
createGmailLabel()      # Code.gs

# 手動実行（30分トリガーを待たずに動かす）
runAll()                # Code.gs → processGmailEmails()
```

テストスイート・リンター・フォーマッタは未設定。検証は GAS エディタの実行ログ（`Logger.log`）と、Google Sheets の行追加で目視確認する。

## デプロイ

Google Apps Script のスタンドアロン or スプレッドシート紐付けプロジェクトとして配置し、Web App としてデプロイする。

- 実行ユーザー: `USER_DEPLOYING`（`appsscript.json`）
- アクセス権: `ANYONE_ANONYMOUS`（LINE Webhook 受信のため必須）
- タイムゾーン: `Asia/Tokyo`
- ランタイム: V8
- 再デプロイで `SCRIPT_ID` が変わった場合、LINE Developers の Webhook URL も更新する（README の手順 8）。

## 環境変数（Script Properties）

GAS の「プロジェクトの設定」→「スクリプト プロパティ」に設定する。

| キー | 用途 |
| --- | --- |
| `CLAUDE_API_KEY` | Anthropic Claude API キー。未設定なら `extractWithClaude` が例外を投げる。 |
| `SHEET_ID` | 書き込み先 Google Sheets の ID。未設定なら `SpreadsheetApp.openById` が失敗。 |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API 長期トークン。未設定なら Bot 返信のみスキップ（Webhook 受信・Sheets 保存は動作）。 |
| `LINE_WEBHOOK_SECRET` | Webhook URL の `?secret=` 認証用。未設定なら認証チェックは無効化される。 |
| `GEMINI_API_KEY` | **コード内で参照されていない**。値を入れても動作に影響しない。 |

## プロジェクト構成

| パス | 役割 |
| --- | --- |
| `Code.gs` | エントリポイント。`runAll` / `doGet` / `doPost` / `setup` / `createGmailLabel` と、フォームから呼ばれる `extractLineInfo` / `saveLineProperty`。 |
| `Config.gs` | `CONFIG` オブジェクト（Script Properties 読み出し getter ＋ 固定値）と `COLUMNS` 配列（Sheets の列定義）。 |
| `ClaudeAPI.gs` | `EXTRACT_PROMPT` と `extractWithClaude(text)`。`claude-haiku-4-5` を呼び、本文先頭 4000 文字を送る。レスポンス本文から `\{[\s\S]+\}` で JSON を切り出す。 |
| `GmailProcessor.gs` | `processGmailEmails`：「不動産物件」ラベルの未読スレッドを走査。`extractWithClaude` → 物件名/所在地/価格すべて空ならスキップ → `appendProperty` → 「物件処理済み」ラベル付与 + 既読化。 |
| `SheetsWriter.gs` | `getSheet`（無ければ作成＋ヘッダー書き込み）、`isAlreadySaved`（`受信メールURL` で重複判定）、`appendProperty`（1行追加。`ステータス` 初期値は `検討中`）。 |
| `DriveHandler.gs` | `saveAttachments`：PDF / 画像（jpeg / png）のみを「不動産資料」フォルダに保存し、リンク共有を有効化して URL を改行区切りで返す。 |
| `LineWebhook.gs` | `handleLineWebhook` / `_processLineMessage` / `_replyToLine`。常に 200 + `status:ok` を返す。 |
| `webapp.html` | LINE フォーム UI。`google.script.run` で `extractLineInfo` / `saveLineProperty` を呼ぶ 2 ステップ（抽出 → プレビュー編集 → 保存）。 |
| `appsscript.json` | GAS マニフェスト（OAuth スコープ、Web App 公開設定、タイムゾーン）。 |
| `README.md` | セットアップ手順（スプレッドシート作成〜LINE Webhook 設定まで）。 |
| `HANDOFF.md` | 引き継ぎメモ。データフロー図あり。 |

## アーキテクチャ

### データフロー

```
Gmail（ラベル「不動産物件」, 未読）
   └─ 30分トリガー → runAll → processGmailEmails
                                  ├─ saveAttachments（PDF/画像のみ）
                                  ├─ extractWithClaude（件名+本文）
                                  ├─ appendProperty（source='Gmail'）
                                  └─ 「物件処理済み」ラベル付与 + markRead

LINE Bot（テキストメッセージ）
   └─ Messaging API → doPost → handleLineWebhook → _processLineMessage
                                                       ├─ extractWithClaude
                                                       ├─ appendProperty（source='LINE'）
                                                       └─ _replyToLine（保存結果）

Web App フォーム（手動補助）
   └─ doGet → webapp.html → extractLineInfo → renderPreview → saveLineProperty
```

抽出は常に `ClaudeAPI.extractWithClaude` を経由する単一窓口。判定ロジック（「物件情報なし」のスキップ）も Gmail / LINE で同じキー（物件名 / 所在地 / 価格）を使う。

### Sheets 列スキーマと書き込みの一対一対応

`Config.gs` の `COLUMNS` 配列（20 列）と、`SheetsWriter.appendProperty` の `appendRow([...])` の値リストは順序込みで対応している。さらに `_initSheet` での列幅設定（3, 4, 9, 15, 16 列目）も位置依存。列を追加・並び替える場合は以下をすべて更新する必要がある：

1. `Config.gs` の `COLUMNS`
2. `SheetsWriter.appendProperty` の `appendRow` 引数順序
3. `_initSheet` の `setColumnWidth` の列番号
4. `isAlreadySaved` の `COLUMNS.indexOf('受信メールURL') + 1` は配列から引いているので自動追従するが、**既存のスプレッドシートは初回作成時のヘッダーのまま**で、再実行してもヘッダーは更新されない。列追加時は手動でヘッダー行も更新する。

### LINE Webhook の制約

`LineWebhook.gs` 冒頭のコメントどおり、GAS の `doPost(e)` では HTTP リクエストヘッダーが取得できない。LINE の標準的な `X-Line-Signature` HMAC 検証は不可能なので、Webhook URL 自体に `?secret=YOUR_LINE_WEBHOOK_SECRET` を付ける簡易認証を採用している。

加えて、`handleLineWebhook` は **どんな失敗経路でも `ContentService` の 200 OK + `{ status: "ok" }` JSON を返す**。これは LINE 側の Webhook 検証ボタンや本番イベント送信が 200 を期待しているため。例外は `Logger.log` に出すだけで、HTTP ステータスは変えない。

### Claude 抽出のプロンプト契約

`EXTRACT_PROMPT`（`ClaudeAPI.gs`）は **必ず固定 14 キーの JSON のみを返す** ことを Claude に強制している。受け側（`SheetsWriter.appendProperty`）は欠損キーを `''` にフォールバックするが、キー名（`物件名`, `所在地`, ... 日本語）はプロンプト・抽出関数・Sheets 列名で一貫している必要がある。キー名を英語化するなら 3 箇所同時に直すこと。

レスポンスからの JSON 切り出しは `raw.match(/\{[\s\S]+\}/)` の最初のマッチに依存している。Claude が JSON 前後に説明文を付ける可能性に備えた正規表現で、JSON 中にネスト `{}` がある場合は正しく切れない（現スキーマはネストなしなので問題なし）。

### Gmail 処理のラベル戦略

`GmailProcessor._getTargetThreads` はラベル「不動産物件」を優先し、存在しない場合のみ `CONFIG.GMAIL_KEYWORDS`（`subject:(物件 OR 不動産 OR 利回り OR 収益 OR 売買) is:unread -label:物件処理済み`）にフォールバックする。処理済みメールには「物件処理済み」ラベル（`CONFIG.PROCESSED_LABEL`）を付け、`markRead` する。重複保存防止は `受信メールURL`（`https://mail.google.com/mail/u/0/#inbox/<msgId>`）の完全一致で行うため、`MAX_THREADS=30` を増やすときは全行スキャンのコストに注意。

## 既知のクセ / コードに見えるが違うもの

- **`Config.gs` の `GEMINI_API_KEY` getter は dead code**。`grep -rn GEMINI` で参照箇所は `Config.gs` のみ。Gemini への切替検討の名残と思われる。実際の抽出は Claude API のみ。
- **`Config.gs` の `CONFIG.LINE_WEBHOOK_SECRET` が空文字列の場合、認証チェックがスキップされる**（`LineWebhook.gs:16` の `if (secret && ...)`）。本番運用では必ず設定する。
- **`saveLineProperty` は Web App フォーム経由でのみ呼ばれる**。LINE Bot 経由の保存は `_processLineMessage` から `appendProperty` を直接呼ぶ別経路。同じ「LINE」ソースでも 2 つの入り口がある。
- **`DriveHandler.saveAttachments` は PDF / 画像以外（Word, Excel など）を黙って捨てる**。`ct.match(/pdf|image|jpeg|png/i)` に一致しない添付はログにも残らない。
- **LINE 経由の保存は重複チェックなし**。同じメッセージを 2 回送ると 2 行追加される。
- **シートが既に存在する場合、`_initSheet` は呼ばれない**ので、後から `COLUMNS` を増やしてもヘッダー行は更新されない。手動で列追加が必要。
