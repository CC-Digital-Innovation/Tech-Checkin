FROM python:3.13.14-alpine3.24 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .

RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir --prefix=/install -r requirements.txt

COPY ./src .


FROM python:3.13.14-alpine3.24 AS runtime

LABEL org.opencontainers.image.authors="Anthony Farina"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup -S -g 10015 techchekin && \
    adduser -S -u 10014 -G techchekin techcheckin

COPY --from=builder /install /usr/local
COPY --from=builder /app /app

USER techcheckin:techchekin

EXPOSE 8000

ENTRYPOINT ["python", "main.py"]