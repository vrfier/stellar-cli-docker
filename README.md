# stellar-cli-docker

Docker images for the [Stellar CLI](https://github.com/stellar/stellar-cli).

Also compatible as a [SEP-58](https://github.com/stellar/stellar-protocol/blob/master/ecosystem/sep-0058.md) image image for reproducible Stellar contract builds.

Each image:

- Pins its base via the official `rust:<version>-<suffix>` multi-arch
  index digest. See
  [`RELEASE.md` → Base image policy](./RELEASE.md#base-image-policy) for
  how the version + suffix are chosen per release.
- Pins the Rust toolchain via `RUSTUP_TOOLCHAIN`, baked in so an in-source
  `rust-toolchain.toml` cannot silently swap it.
- Pins `stellar-cli` to a specific upstream commit, installed with
  `cargo install --locked`.
- Ships with the `wasm32v1-none` target preinstalled.
- Sets `WORKDIR /source` and `ENTRYPOINT ["stellar"]`.

## Quick start

Pull a published image (per-host arch):

```sh
docker run --rm docker.io/stellar/stellar-cli:latest --version
```

Confirm the rustc version used:

```sh
docker run --rm --entrypoint rustc docker.io/stellar/stellar-cli:latest --version
```

Build a contract by mounting the contract directory at `/source`:

```sh
docker run --rm -v "$PWD:/source" docker.io/stellar/stellar-cli:latest contract build --locked
```

The image exposes four well-known paths:

| Path       | What                                                                              |
| ---------- | --------------------------------------------------------------------------------- |
| `/source`  | `WORKDIR`. Bind-mount your contract here.                                         |
| `/config`  | `STELLAR_CONFIG_HOME`. Mount to persist network and identity configuration.       |
| `/data`    | `STELLAR_DATA_HOME`. Mount to persist CLI data.                                   |
| `/stellar` | Home for user `stellar` (UID 1000). Mount to persist the cargo cache (see below). |

The image runs as user `stellar` (UID 1000) with `/stellar` as the home
directory. `CARGO_HOME` resolves to `/stellar/.cargo` inside the
container, which is wiped on exit by default.

To reuse cargo's registry index, git checkouts, and crate sources across
runs — and to make the image work under `--user "$(id -u):$(id -g)"` on
Linux hosts whose UID is not 1000 — mount a writable host directory at
`/stellar`:

```sh
mkdir -p /tmp/myproject
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v /tmp/myproject:/stellar \
  -v "$PWD:/source" \
  docker.io/stellar/stellar-cli:latest contract build --locked
```

## Verifiable builds ([SEP-58](https://github.com/stellar/stellar-protocol/blob/master/ecosystem/sep-0058.md))

For verifiable references, **always pin to a per-arch single-architecture
digest (`@sha256:…`)** — it is the only stable reference. Never use a tag or a
multi-arch manifest list digest in `bldimg`:

```sh
# Find the per-arch digest for the architecture you used to build.
# Pick any of the manifest-list tags from the release notes,
# e.g. :26.0.0-rust1.94.0-slim-trixie, or the :26.0.0 alias:
docker buildx imagetools inspect docker.io/stellar/stellar-cli:26.0.0
```

Record the per-arch digest in your contract's `bldimg` metadata. A verifier
will pull the same per-arch image, run the same `docker run` invocation, and
compare the resulting WASM sha256.

## Repo layout

| Path                       | What                                                                                                                                                                                                                                 |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `Dockerfile`               | Two-stage builder + runtime, args-driven.                                                                                                                                                                                            |
| `builds.json`              | Source of truth for which (stellar-cli, rust base key) pairs we publish.                                                                                                                                                             |
| `builds.schema.json`       | JSON Schema for `builds.json`.                                                                                                                                                                                                       |
| `docker/README.md`         | Docker Hub overview. The publish workflow pushes this to the repository's `full_description` on each release.                                                                                                                       |
| `scripts/build_image.py`   | Local single-image build.                                                                                                                                                                                                            |
| `scripts/validate_json.py` | Validates every `*.json` for sorted keys and `builds.json` against the schema.                                                                                                                                                       |
| `scripts/refresh.py`       | For one `--stellar-cli-version`: picks the rust base labels, resolves the upstream cli ref and each base's index digest, and appends the fully-qualified pins `<label>@<digest>` (append-only; already-published pins are retained). |
| `scripts/verify_image.py`  | Consumer-facing verifier. Wraps `gh attestation verify` for both the SLSA build provenance and the SPDX SBOM attestations against a per-arch image digest.                                                                           |
| `scripts/lib/`             | Shared Python helpers imported by the other scripts (builds.json IO, semver/key parsing, subprocess + adapter wrappers).                                                                                                             |

## Local development

```sh
# Validate builds.json.
./scripts/validate_json.py

# Build a local image for a declared (cli, rust base) pair. The rust base is
# given as the label; the digest is resolved from builds.json automatically.
./scripts/build_image.py --stellar-cli-version 26.0.0 \
  --rust-version 1.94.0-slim-trixie

# Only when a label carries more than one digest in builds.json do you need
# --rust-image-digest to say which pin to build.

# Smoke-test the built image.
docker run --rm stellar-cli:26.0.0-rust1.94.0-slim-trixie --version
docker run --rm stellar-cli:26.0.0-rust1.94.0-slim-trixie contract build --help

# Resolve + append rust base pins and the cli ref for a version (maintainer task).
./scripts/refresh.py --stellar-cli-version 26.1.0 --dry-run
```

Requirements: `docker` (with `buildx`) and [`uv`](https://docs.astral.sh/uv/).

## Releasing

Maintainers: see [`RELEASE.md`](./RELEASE.md) for the end-to-end release
process — how `builds.json` works, the PR-driven release flow that fires
the publish workflow when a GitHub Release is published, the published tag
scheme, and how to verify a freshly published image.

## License

[Apache-2.0](./LICENSE).
