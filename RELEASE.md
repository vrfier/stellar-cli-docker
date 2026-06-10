# Releasing Stellar CLI images

This document covers the maintainer side of `stellar/stellar-cli-docker` — how to publish a new Stellar CLI image and what the publish workflow does on your behalf.

## What gets published

Each release publishes to `docker.io/stellar/stellar-cli`:

- **Per-architecture images** — `:<cli>-rust<rust>-amd64` and `:<cli>-rust<rust>-arm64`. Each one is a single-architecture manifest with its own SHA-256 digest.
- **Multi-arch manifest list** per `(cli, rust base)` pair — `:<cli>-rust<rust>` resolves to the right per-arch image at pull time.
- **Moving tags** — `:<cli>` points at the manifest list for that cli paired with the default rust base (highest `rust_versions[]` pin whose label matches the top-level `default_distro`, newest digest wins on a tie). `:latest` points at the same derivation for the newest declared cli. Both re-point on every publish.
- **Two attestation chains** — buildx-native (SLSA build provenance + SPDX SBOM attached in the registry alongside the image) and GitHub-native (the same predicates signed and stored in the repo's attestation store, verifiable via `gh attestation verify`).
- **A GitHub Release** for every publish run, with per-architecture digests in the body and the SBOM + provenance files attached as downloadable assets. The release is created by a maintainer following the link in the release PR (see [Releasing](#releasing--new-cli-version-or-refreshing-an-existing-one) below); publishing it triggers the workflow that enriches the release with the images' digests and supply-chain artifacts.

The single source of truth for which `(cli, rust)` pairs we publish is [`builds.json`](./builds.json). Releases happen one stellar-cli version per workflow run.

## Repository setup

The workflows expect the following GitHub repository configuration. Settings live under **Settings → Secrets and variables → Actions** on the repo.

### Required secrets

| Secret               | Used by       | Purpose                                                                                          |
| -------------------- | ------------- | ------------------------------------------------------------------------------------------------ |
| `DOCKERHUB_USERNAME` | `publish.yml` | Username for the `docker/login-action` that authenticates pushes to Docker Hub.                  |
| `DOCKERHUB_TOKEN`    | `publish.yml` | Access token for the same Docker Hub login. Use a scoped access token, not the account password. |

### Optional variables

| Variable   | Default                         | Purpose                                                                                                                                                                                                                                                                                                                        |
| ---------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `REGISTRY` | `docker.io/stellar/stellar-cli` | Registry path to push images to. Override on a fork to publish to a personal registry for testing (e.g. `docker.io/<user>/stellar-cli-experimental`). Threaded through `publish.yml`'s build/manifest/aliases jobs and into `scripts/release_body.py` so the rendered release body matches whatever registry was published to. |

### Required workflow permissions

These are set in the workflow YAML, not in repo settings — but worth knowing what each is for if you're reviewing or hardening:

- `contents: write` (`publish.yml`, `release.yml`) — `publish.yml`'s release job updates the GitHub Release; `release.yml` pushes the release branch.
- `attestations: write` (`publish.yml`) — `actions/attest-build-provenance` and `actions/attest-sbom` publish to the repo's attestation store.
- `id-token: write` (`publish.yml`) — OIDC token used by buildx provenance and the attest actions for keyless Sigstore signing.
- `pull-requests: write` (`release.yml`) — `gh pr create` opens the release PR.

### Branch protection

`ci.yml` is the single PR gate. It runs on `pull_request` (and pushes to `main`), calls `lint.yml` and `build.yml` as reusable workflows, and rolls them up into one `complete` job that `needs` both. Configure branch protection on `main` to require that one check before merging:

- `complete`

Because `complete` `needs` lint and build, the check can't report success until both finish — so auto-merge waits on all of CI through a single required check. The `publish` and `release` workflows fire on release events / dispatch and don't gate merges to `main`.

## Release tag scheme

Every release gets a unique tag. Tags are never reused or updated in place.

- **First release of a stellar-cli version**: `v<version>` (e.g. `v26.0.0`).
- **Refresh of the same stellar-cli version**: `v<version>-<N>` (e.g. `v26.0.0-1`, `v26.0.0-2`). The `-N` increments per refresh.

The `release` workflow picks the next available tag automatically by looking at existing releases. Each release page is the snapshot of `builds.json` at that iteration; the historical `v26.0.0` page stays intact when `v26.0.0-1` is later published.

Docker image tags (`:<cli>-rust<key>[-<arch>]`) are unaffected by the `-N` suffix — they're keyed by the cli version + rust base label + arch. They are **mutable**: re-publishing a `(cli, rust base)` pair (e.g. after a refreshed base) overwrites the tag in place. Moving tags (`:<cli>`, `:latest`) re-point on every publish.

## Releasing — new cli version, or refreshing an existing one

Same workflow for both. PR review is the gate; a GitHub Release is the publish trigger. No manual tag pushes.

1. **Trigger the `release` workflow** from the Actions UI with the stellar-cli version (e.g. `26.1.0` for a brand-new release, or `26.0.0` to refresh an already-published cli with the current latest rust pairings). The workflow:

   - Detects whether this is a **new release** (cli not yet declared) or a **refresh** (cli exists in `builds.json`).
   - Picks the last two minor stable rust versions, at their latest patch each, from Docker Hub's `library/rust` tag list, filtered by the `slim-<default_distro>` suffix.
   - Updates `builds.json`: adds a new entry, or **appends** to the existing entry's `rust_versions[]`. For each picked rust base it resolves the upstream cli commit SHA and the base's current index digest, then appends the fully-qualified pin `<label>@sha256:<digest>` — deduped on the full pin (a rebuilt base, i.e. same label with a new digest, is a new pin) and numerically sorted.
   - Validates the result.
   - Picks the next available release tag — `v<version>` for a fresh release, `v<version>-<N>` for a refresh.
   - Pushes a `release/<tag>` branch and opens a PR with a body modeled on stellar-cli's release PRs, including a pre-filled link to create the GitHub Release on merge.

2. **Review and adjust** the PR. The auto-pick of rust versions is a sensible default but not always right; if you want different `rust_versions` for this iteration, push commits to the release branch before merging. The PR-time `lint` and `build` workflows re-do validation and smoke-build on every push.

3. **Merge the PR** once approved. `builds.json` now declares the new release state.

4. **Publish the release** by following the `Create release` link in the PR body. That opens `Releases → New release` with the tag pre-filled; add notes (or use `Generate release notes`), then **Publish release**.

   The `publish` workflow fires on the `release: published` event and:

   - Builds and pushes per-arch images for every declared (cli, rust) pair; tags are mutable, so an existing tag is overwritten in place.
   - Generates SLSA build provenance + SPDX SBOM attestations on each freshly-built image (buildx-native + GitHub-native chains).
   - Re-points the `:<cli>` and (if newest) `:latest` aliases.
   - Updates the new GitHub Release: appends per-architecture digests for every declared pair (whether built fresh or previously published) and verification commands to the body, attaches the SBOM and provenance files for the freshly-built pairs as downloadable assets.

### Manual / local prepare

If you'd rather run the prepare step yourself (e.g. to debug an auto-pick that's failing), do it locally:

```sh
./scripts/release_prepare.py --stellar-cli-version 26.1.0
# Optional: pin specific rust base keys instead of the auto-pick
./scripts/release_prepare.py --stellar-cli-version 26.1.0 \
  --rust-versions 1.94.0-slim-trixie,1.95.0-slim-trixie
```

The script prints the chosen release tag as its final stdout line. Commit and push the resulting `builds.json` change yourself, open the PR with that tag, and continue from step 3 above.

### Validating locally before pushing

```sh
./scripts/validate_json.py
# --rust-version is the label; build_image.py resolves its pinned digest from
# builds.json (the digest pins the FROM and is cross-checked against the image's
# org.opencontainers.image.base.digest label). The built tag is label-only.
# Pass --rust-image-digest only when one label carries multiple digests.
./scripts/build_image.py --stellar-cli-version 26.1.0 --rust-version 1.95.0-slim-trixie
./scripts/smoke_test_image.py --image stellar-cli:26.1.0-rust1.95.0-slim-trixie \
  --stellar-cli-version 26.1.0 --rust-version 1.95.0-slim-trixie \
  --rust-image-digest sha256:e14e87345b4d5964ddcc3491d27ee046a0f23820f340c3c1e24da6880141f7c0
./scripts/repro_test.py --image stellar-cli:26.1.0-rust1.95.0-slim-trixie
```

The smoke test confirms the binary reports the expected version and the labels are correct. The repro test confirms `stellar contract build --locked` produces byte-identical WASM across two clean builds. CI does the same against the freshly-built image on every PR push.

## What the publish workflow does

Triggered exclusively by the `release: published` event — when a maintainer clicks **Publish release** in the GitHub UI for a `v<version>` tag. There is no manual-dispatch entry point: publishing always goes through a reviewed `builds.json` PR and a GitHub Release page, so accidental ad-hoc publishes are off the table. Each run publishes **exactly one** cli version.

| Job              | What it does                                                                                                                                                                                                                                                                                                                                                                                           |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `matrix`         | Validates `builds.json`, derives the cli version (from the release's tag name or the dispatch input), then runs `scripts/resolve_matrix.py --stellar-cli-version <v>` to produce a matrix of `(rust base key, arch)` rows for that one cli.                                                                                                                                                            |
| `build` (matrix) | Native runner per arch (`ubuntu-24.04` for amd64, `ubuntu-24.04-arm` for arm64). Builds + pushes every pair via `docker/build-push-action` with `provenance: mode=max` and `sbom: true`, then attests with `actions/attest-build-provenance` and `actions/attest-sbom`. Tags are mutable, so an existing tag is overwritten. The per-arch metadata + SBOM/provenance artifacts feed the `release` job. |
| `manifest`       | Assembles the multi-arch manifest list `:<cli>-rust<key>` per rust base. Lists are (re)created via `docker buildx imagetools create`, overwriting any existing list.                                                                                                                                                                                                                                   |
| `aliases`        | Re-points `:<cli>` to the manifest list of `(cli, default rust pin)` — the highest `rust_versions[]` pin whose label matches `default_distro`, newest digest winning a tie. If this cli is the newest declared, also re-points `:latest`. Both tags are intentionally moving; the job fails loudly if no `rust_versions[]` pin matches `default_distro`.                                               |
| `release`        | Downloads every per-arch metadata + (when present) SBOM/provenance artifact, calls `scripts/release_body.py` to compose a structural body section, then **appends** that section to the just-created release body and attaches the SBOM + provenance files for freshly-built pairs as release assets. Any human-written notes already in the release body are preserved.                               |
| `complete`       | Single aggregator for the publish workflow. Fails if any upstream job failed or was cancelled.                                                                                                                                                                                                                                                                                                         |

## Mutable tags and restarts

Per-architecture tags (`:<cli>-rust<key>-<arch>`) and multi-arch manifest lists (`:<cli>-rust<key>`) on Docker Hub are **mutable** — re-publishing a `(cli, rust base)` pair overwrites the tag in place. Reproducibility is anchored by the per-arch image content digest and by the `builds.json` pins, not by tag stability.

Moving aliases (`:<cli>`, `:latest`) re-point each release.

To recover from a failed run, use **Re-run failed jobs** from the GitHub Actions UI; re-runs simply rebuild and overwrite. Recovering from a corrupt push is the same — just re-run, no manual tag deletion needed.

## Base image policy

The Rust base image carries two choices we make deliberately: the **variant** (`slim` vs the default buildpack-deps-based image) and the **Debian codename** (e.g. `bookworm`, `trixie`). Both appear in the upstream Rust image tag — `rust:<version>-[slim-]<debian>` — and we encode them into our own image tag so the choices are visible and stay unique across future switches.

**Variant — use the `slim` upstream image.** SPDX JSON SBOMs grow with the file count of the image, not the package count. The buildpack-deps-based base ships the full GNU/Linux build toolchain (gcc, autoconf, make, perl, python, headers, locale data, manpages), pushing the file count into the tens of thousands and producing an SBOM that exceeds the per-file size limit imposed by `actions/attest` — the GitHub-native SBOM attestation step in `publish.yml` then fails. Slim's file count is roughly an order of magnitude smaller, so the SBOM fits. The builder stage installs `build-essential`, `ca-certificates`, `git`, `libssl-dev`, and `pkg-config` explicitly because slim doesn't ship them.

**Debian codename — track the latest Ubuntu LTS upstream.** Each Ubuntu LTS is based on a Debian release. We default to that Debian. The current latest Ubuntu LTS is 26.04, which is based on Debian 13 (`trixie`), so `trixie` is today's value of `default_distro`. We don't move to the newest Debian release the day it ships — we wait for the next Ubuntu LTS to track it, so users on the prevailing LTS host distro aren't running on a Debian newer than what their host's upstream tracks.

**Tag — include variant + Debian.** The composite rust base key (e.g. `1.94.0-slim-trixie`) flows verbatim into the published image tag: `<cli>-rust<key>[-arch]`. When we eventually move off `trixie`, the new images get a new tag suffix and the historical tags stay addressable.

### Switching the default

`default_distro` is the single switch. The picker queries Docker Hub for tags with the `slim-<default_distro>` suffix; the aliases job derives `:<cli>` and `:latest` targets the same way. Historical entries with the old suffix stay in each cli's `rust_versions[]` so the file stays consistent with what's already been published.

1. Edit `builds.json:default_distro` to the new codename (the schema's `enum` lists the supported values).
2. Run `./scripts/validate_json.py` and the local smoke build (see [Validating locally before pushing](#validating-locally-before-pushing)).
3. Open a PR as usual. On merge, dispatch the `release` workflow against the cli you want to re-target; the picker appends the new-suffix keys to that cli's `rust_versions[]` and the publish flow re-points the moving aliases.

The `Dockerfile`'s `FROM` lines reference the image by digest only; the variant + Debian codename show up in `org.opencontainers.image.base.name` (e.g. `docker.io/library/rust:1.95.0-slim-trixie`) via a build-arg passed from the matrix.

## Adopting a rebuilt base image

To adopt a freshly-rebuilt rust base for an already-published cli — e.g. upstream republished `rust:1.95.0-slim-trixie` under a new index digest after a CVE patch — run `refresh` against that cli:

```sh
./scripts/refresh.py --stellar-cli-version 26.1.0 --rust-versions 1.95.0-slim-trixie
```

`refresh` resolves the label's current upstream index digest and **appends** it as a new `label@sha256:<digest>` pin. Appending rather than rewriting keeps `builds.json` an append-only ledger of every base a release was built against — an audit trail of what shipped — while the mutable `:<cli>-rust<label>` tag tracks the most recent publish. Don't hand-edit the pin: `refresh` resolves the digest from the registry and keeps the file sorted and consistent, so it's the single supported way to change a base.

Commit the change and run the release flow as a refresh iteration (`v<cli>-<N>`). On publish, the `:26.1.0-rust1.95.0-slim-trixie` tag is rebuilt against the new base and overwritten in place; its per-arch image content digest changes accordingly. Other cli versions are unaffected — their tags carry a different cli prefix. To build against a different upstream stellar-cli commit instead, declare a new cli version.

## Verifying a freshly published release

After a release publish succeeds, sanity-check the attestations:

```sh
# Extract a per-arch digest:
docker buildx imagetools inspect docker.io/stellar/stellar-cli:26.1.0

# Verify both attestation chains in one command:
./scripts/verify_image.py --image docker.io/stellar/stellar-cli@sha256:<digest>
```

Or directly:

```sh
gh attestation verify oci://docker.io/stellar/stellar-cli@sha256:<digest> \
  --repo stellar/stellar-cli-docker
cosign verify-attestation --type slsaprovenance \
  docker.io/stellar/stellar-cli@sha256:<digest>
```

Both attestation chains have the same trust root (the runner's GitHub Actions OIDC identity); they differ only in verification UX.

## Pairing an already-released cli with a new rust toolchain

Use the same `release` workflow with the existing cli version. The workflow detects the cli is already declared, runs in refresh mode, picks the current last-two-minor rusts, and **appends** them to the cli's `rust_versions[]` (existing keys are kept), then opens a PR. After merging, create the GH Release pre-filled at `v<cli>-1` (or `-2`, etc.) per the [release tag scheme](#release-tag-scheme). The new rust pair builds; already-published pairs skip with a warning; aliases re-point as needed.

No friction, no manual tag deletion. The historical `v<cli>` release page stays as a snapshot of the initial publish.
