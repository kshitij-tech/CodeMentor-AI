FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates \
       g++ \
       golang-go \
       openjdk-17-jdk-headless \
       nodejs \
       npm \
       python3 \
       rustc \
       cargo \
    && npm install -g typescript \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 65532 codementor \
    && useradd --uid 65532 --gid 65532 --create-home --shell /usr/sbin/nologin codementor

WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GOCACHE=/tmp/go-cache \
    CARGO_HOME=/tmp/cargo \
    RUSTUP_HOME=/tmp/rustup

USER 65532:65532
