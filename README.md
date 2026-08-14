# job-fit-agent

スキルシートと求人票を読み込ませて、案件ごとの適合度・必須スキルの充足(○×)・懸念点・応募文をClaudeに自動生成させるローカルWebアプリ。

## セットアップ

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env  # ANTHROPIC_API_KEY を設定
```

## 起動

```bash
.venv/bin/uvicorn app.main:app --reload
```

http://127.0.0.1:8000 を開く。

## 使い方

1. `/skill-sheet` で自分のスキルシート（.xlsx / .docx / テキスト）を登録する（初回のみ、以後は使い回し）
2. トップページで求人票のテキストを貼り付け（またはファイルを選択）て「判定する」
3. 適合度スコア・必須/歓迎スキルの○×判定・懸念点・応募文が表示される
4. 判定結果は `/history` に蓄積される

スキルシートおよび判定履歴は `data/` にローカル保存されます。
判定時には、求人票とスキルシートから抽出したテキストのみをClaude APIへ送信します。
`data/` と `.env` はgit管理対象外です。
