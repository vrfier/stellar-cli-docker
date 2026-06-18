# syntax=docker/dockerfile:1.10

# Reproducible stellar-cli image. See SEP-58 for the full contract:
# https://github.com/stellar/stellar-protocol/blob/master/ecosystem/sep-0058.md
#
# Every input is pinned. The base image is referenced by its multi-arch
# index digest exclusively — FROM never carries a tag — so a drifting tag
# cannot silently change what we build against. RUST_VERSION and
# RUST_BASE_SUFFIX are surfaced in labels (and RUST_VERSION drives
# RUSTUP_TOOLCHAIN) but are metadata, not load-bearing on FROM. The Rust
# toolchain is pinned by version, and stellar-cli by a specific upstream
# commit SHA. Build args are not optional; the build scripts and CI
# workflows always supply them.

ARG RUST_VERSION
ARG RUST_BASE_SUFFIX
ARG RUST_IMAGE_DIGEST
# Falls back to RUST_IMAGE_DIGEST so direct `docker build` usage keeps working
# without supplying CLI_RUST_IMAGE_DIGEST. The build scripts and CI always set
# it explicitly (from cli_rust_version) so the builder stage can diverge from
# the final stage's base image.
ARG CLI_RUST_IMAGE_DIGEST=${RUST_IMAGE_DIGEST}
ARG STELLAR_CLI_REV
ARG STELLAR_CLI_VERSION
ARG BUILD_DATE
ARG SOURCE_REPO

FROM rust@${CLI_RUST_IMAGE_DIGEST} AS builder
ARG STELLAR_CLI_REV
ARG STELLAR_CLI_VERSION
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]
ENV CARGO_HOME=/usr/local/cargo \
    DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
        libdbus-1-dev \
        libssl-dev \
        libudev-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*
RUN cargo install --locked --features opt --root /out \
        --git https://github.com/stellar/stellar-cli.git \
        --rev "${STELLAR_CLI_REV}" \
        stellar-cli

# Fail the build loudly if the binary's reported version disagrees with the
# version the caller declared. Catches accidental ref/version drift in
# builds.json at build time, not later when an image is already published.
#
# Skipped for stellar-cli < 23.0.0: those releases lack `version
# --only-version` (it returns empty) and don't print the commit rev in a
# parseable form, so the check can't run against them.
#
# Full `stellar version` output is captured first, then parsed in memory.
# Piping `stellar version | head -n1` closes head's read end after the
# first line, leaving stellar with a broken pipe on its remaining writes;
# Rust 1.96+ panics on EPIPE from stdio rather than exiting quietly, and
# pipefail propagates that as a build failure even though the values matched.
RUN major="${STELLAR_CLI_VERSION%%.*}" \
     && if [ "${major:-0}" -lt 23 ]; then \
            echo "skipping stellar-cli version check for ${STELLAR_CLI_VERSION} (< 23.0.0)" >&2; \
        else \
            installed_version="$(/out/bin/stellar version --only-version)" \
             && stellar_version_output="$(/out/bin/stellar version)" \
             && installed_rev="$(printf '%s\n' "$stellar_version_output" | grep -oE '[0-9a-f]{40}' | head -n1)" \
             && test "$installed_version" = "${STELLAR_CLI_VERSION}" \
             && test "$installed_rev" = "${STELLAR_CLI_REV}" \
             || { echo "stellar-cli mismatch: binary reports version='$installed_version' rev='$installed_rev', expected version='${STELLAR_CLI_VERSION}' rev='${STELLAR_CLI_REV}'" >&2; exit 1; }; \
        fi

FROM rust@${RUST_IMAGE_DIGEST}
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]
ARG RUST_VERSION
ARG RUST_BASE_SUFFIX
ARG RUST_IMAGE_DIGEST
ARG STELLAR_CLI_REV
ARG STELLAR_CLI_VERSION
ARG BUILD_DATE
ARG SOURCE_REPO

# RUSTUP_TOOLCHAIN is baked in so an in-source `rust-toolchain.toml` in a
# consumer's contract can't silently swap our pinned toolchain at build
# time. Required by SEP-58 "self-contained build environment". Consumers can
# still override with `-e RUSTUP_TOOLCHAIN=...` if they know what they're
# doing.
ENV DEBIAN_FRONTEND=noninteractive \
    RUSTUP_TOOLCHAIN=${RUST_VERSION}

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libdbus-1-3 \
        libssl3 \
        libudev1 \
    && rm -rf /var/lib/apt/lists/*
RUN rustup target add wasm32v1-none

RUN useradd --create-home --home-dir /stellar --uid 1000 --shell /bin/bash stellar \
    && mkdir -p /source /config /data \
    && chown stellar:stellar /source /config /data

COPY --from=builder --chown=root:root --chmod=0755 /out/bin/stellar /usr/local/bin/stellar

ENV CARGO_HOME=/stellar/.cargo \
    HOME=/stellar \
    STELLAR_CONFIG_HOME=/config \
    STELLAR_DATA_HOME=/data \
    STELLAR_NO_UPDATE_CHECK=1
USER stellar
WORKDIR /source

ENTRYPOINT ["stellar"]
CMD []

LABEL org.opencontainers.image.title="stellar-cli" \
      org.opencontainers.image.description="Stellar CLI image (SEP-58-compatible image for Stellar smart contracts)." \
      org.opencontainers.image.source="https://github.com/${SOURCE_REPO}" \
      org.opencontainers.image.url="https://github.com/${SOURCE_REPO}" \
      org.opencontainers.image.documentation="https://github.com/${SOURCE_REPO}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.vendor="Stellar Development Foundation" \
      org.opencontainers.image.version="${STELLAR_CLI_VERSION}" \
      org.opencontainers.image.revision="${STELLAR_CLI_REV}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.base.name="docker.io/library/rust:${RUST_VERSION}-${RUST_BASE_SUFFIX}" \
      org.opencontainers.image.base.digest="${RUST_IMAGE_DIGEST}"
