#!/usr/bin/env bash
# Cloud Runへのデプロイコマンドを固定化するスクリプト。
#
# --max-instances=1 は必須。public_usage.json（1日の利用上限カウンタ）と
# telemetry.jsonlはインスタンスのローカルファイルにプロセス内ロックで
# 書き込んでおり、複数インスタンスをまたいだ共有・排他制御をしていない。
# 上限を上げると「1日20回まで」の制約がインスタンス数倍に緩んでしまう。
# 複数インスタンスに対応させるには、これらの状態をFirestore等の
# 共有ストレージに移す作り替えが別途必要（フェーズ3のマルチユーザー化と合わせて検討）。
set -euo pipefail

# PROJECT_IDは環境変数必須（未設定なら現在のgcloud configから取得を試みる）。
# 決め打ちにしないのは、このリポジトリがライセンスなしのPublicリポジトリで、
# GCPプロジェクトIDをコードに残したくないため。
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
if [ -z "${PROJECT_ID}" ]; then
  echo "PROJECT_IDが未設定です。環境変数PROJECT_IDを指定するか、gcloud config set projectで設定してください。" >&2
  exit 1
fi
REGION="${REGION:-asia-northeast1}"

gcloud run deploy job-fit-agent \
  --source . \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --allow-unauthenticated \
  --max-instances=1 \
  --min-instances=0 \
  --set-secrets=ANTHROPIC_API_KEY=anthropic-api-key:latest
