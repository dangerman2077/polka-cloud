FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 POLKA_DATA=/srv/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --system --uid 10001 --home /app polka && install -d -o polka -g polka /srv/data /app/public
COPY --chown=10001:10001 . .
USER polka
CMD ["sh","deploy/start.sh"]
