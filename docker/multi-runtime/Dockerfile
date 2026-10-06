FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update     && apt-get install -y --no-install-recommends        ca-certificates        g++        golang-go        openjdk-17-jdk-headless        nodejs        npm        python3        python-is-python3        rustc        cargo     && rm -rf /var/lib/apt/lists/*     && mkdir -p /opt/codementor     && npm install --prefix /opt/codementor typescript @types/node     && groupadd --gid 65532 codementor     && useradd --uid 65532 --gid 65532 --create-home --shell /usr/sbin/nologin codementor     && chmod -R a+rx /opt/codementor

WORKDIR /workspace

ENV PATH=/opt/codementor/node_modules/.bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin     PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     GOCACHE=/tmp/go-cache     GOMODCACHE=/tmp/go-mod-cache     CARGO_HOME=/tmp/cargo     RUSTUP_HOME=/tmp/rustup

USER 65532:65532
