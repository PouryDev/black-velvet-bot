FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8033 \
    DB_PATH=/app/data/bot.db \
    PIP_INDEX_URL=https://mirror.arvancloud.ir/pypi/simple \
    PIP_TRUSTED_HOST=mirror.arvancloud.ir

WORKDIR /app

RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|deb.debian.org|mirror.arvancloud.ir|g; s|security.debian.org|mirror.arvancloud.ir|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's|deb.debian.org|mirror.arvancloud.ir|g; s|security.debian.org|mirror.arvancloud.ir|g' /etc/apt/sources.list; \
    fi

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    || pip install --no-cache-dir \
         --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
         --trusted-host pypi.tuna.tsinghua.edu.cn \
         -r requirements.txt

COPY app ./app
RUN mkdir -p /app/data

EXPOSE 8033

CMD ["python", "-m", "uvicorn", "app.main:create_app", "--host", "0.0.0.0", "--port", "8033", "--factory"]
