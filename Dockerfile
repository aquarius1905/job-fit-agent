FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app app

# このDockerfileはCloud Run等での公開用。ローカル専用データ保存モードのまま
# 公開してしまうと全訪問者がスキルシート・履歴を共有/上書きしてしまうため、
# デフォルトでPUBLIC_MODE=1を固定する（ブラウザ側保存に切り替わる）。
# デプロイ時のフラグ指定に依存させないための安全策。
ENV PUBLIC_MODE=1
ENV PORT=8080
EXPOSE 8080

# rootのまま実行しない。storage.pyが/app/dataを実行時に作成するため、
# /appの書き込み権限も合わせて付与する。
RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && chown -R appuser:appuser /app
USER appuser

CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
