FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY insider_trades ./insider_trades
RUN pip install --no-cache-dir .
ENV INSIDER_DB=/data/insider_trades.db
VOLUME ["/data"]
EXPOSE 8000
CMD ["insider-trades", "serve", "--host", "0.0.0.0", "--port", "8000"]
