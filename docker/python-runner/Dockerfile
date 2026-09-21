FROM python:3.12-slim

RUN groupadd --gid 65532 codementor \
    && useradd --uid 65532 --gid 65532 --create-home --shell /usr/sbin/nologin codementor

WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 65532:65532
