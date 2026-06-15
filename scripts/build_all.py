#!/usr/bin/env -S uv run python
"""Build and publish every (cli, rust base) pair declared in builds.json.

This is the local, all-in-one equivalent of the `publish` GitHub workflow:
for each stellar-cli version it walks the same `resolve_matrix.py` rows
(latest pin per rust label) and builds+pushes each pair to the registry.

Two arch modes:
  * single-arch (default, --arch amd64): build one platform and push it
    straight to the final pull tag `<registry>:<cli>-rust<key>` — no
    per-arch suffix, no manifest list to assemble.
  * --arch all: build both amd64 and arm64 as per-arch tags
    `<registry>:<cli>-rust<key>-<arch>`, then assemble the multi-arch
    manifest list with `publish_manifests.py` (mirrors the CI workflow).

Optionally re-points the moving `:<cli>` / `:latest` aliases via
`publish_aliases.py`.

Defaults target the vrfier fork:
    registry     ghcr.io/vrfier/stellar-cli
    source-repo  vrfier/stellar-cli-docker
    arch         amd64 (single-arch)

Pushing is an outward-facing action: run with --dry-run first to print the
exact commands, and make sure you are logged in to the registry
(e.g. `docker login ghcr.io`) before a real run.
"""

import argparse
import sys

import build_image
import publish_aliases
import publish_manifests
import resolve_matrix
import tag_names
from lib import builds, common

DEFAULT_REGISTRY = "ghcr.io/vrfier/stellar-cli"
DEFAULT_SOURCE_REPO = "vrfier/stellar-cli-docker"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", default=DEFAULT_REGISTRY, metavar="REF")
    parser.add_argument("--source-repo", default=DEFAULT_SOURCE_REPO, metavar="SLUG")
    parser.add_argument(
        "--stellar-cli-version",
        default="",
        metavar="V",
        help="Limit to one cli version (default: every version in builds.json).",
    )
    parser.add_argument(
        "--arch",
        choices=("amd64", "arm64", "all"),
        default="amd64",
        help=(
            "Architecture(s) to build. Default 'amd64' is single-arch: the image "
            "is pushed straight to <cli>-rust<key> with no manifest list. 'all' "
            "builds amd64+arm64 per-arch tags and assembles the multi-arch list."
        ),
    )
    parser.add_argument(
        "--aliases",
        action="store_true",
        help="Also re-point the moving :<cli> and :latest aliases.",
    )
    parser.add_argument(
        "--skip-manifests",
        action="store_true",
        help="With --arch all, only push per-arch images; skip the multi-arch lists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print every build/manifest command without running anything.",
    )
    return parser


def clis_to_build(data: dict, only_cli: str) -> list[str]:
    versions = [entry["version"] for entry in data.get("stellar_cli_versions", [])]
    if not only_cli:
        return versions
    if only_cli not in versions:
        common.die(f"stellar-cli {only_cli} is not declared in builds.json")
    return [only_cli]


def build_one_cli(cli: str, args: argparse.Namespace) -> None:
    """Build + push every image for one cli version's matrix rows.

    Single-arch (--arch amd64/arm64) keeps only the matching rows and pushes
    each straight to the final `<cli>-rust<key>` pull tag. --arch all keeps
    both arches and pushes per-arch `<cli>-rust<key>-<arch>` tags that
    publish_manifests.py later stitches into a multi-arch list.
    """
    single_arch = args.arch != "all"
    data = builds.load()
    rows = resolve_matrix.build_matrix(data, only_cli=cli)["include"]
    if single_arch:
        rows = [r for r in rows if r["platform"] == f"linux/{args.arch}"]
    common.log(f"::group::build {cli} ({len(rows)} image(s), arch={args.arch})")
    for row in rows:
        # Single-arch pushes straight to the list tag (no -<arch> suffix) since
        # there is no second arch to stitch together; --arch all keeps the
        # per-arch suffix for the manifest step.
        tag = tag_names.compose_tag(
            stellar_cli_version=row["stellar_cli_version"],
            rust_version=row["rust_base_key"],
            platform="" if single_arch else row["platform"],
        )
        build_argv = [
            "--stellar-cli-version",
            row["stellar_cli_version"],
            "--rust-version",
            row["rust_base_key"],
            "--rust-image-digest",
            row["rust_image_digest"],
            "--platform",
            row["platform"],
            "--tag",
            f"{args.registry}:{tag}",
            "--source-repo",
            args.source_repo,
            "--push",
        ]
        if args.dry_run:
            common.log("build_image.py " + " ".join(build_argv))
        else:
            rc = build_image.main(build_argv)
            if rc != 0:
                common.die(f"build_image failed for {cli} {tag} (exit {rc})")
    common.log("::endgroup::")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    common.preflight_checks(["buildx"])

    data = builds.load()
    clis = clis_to_build(data, args.stellar_cli_version)
    common.log(f"building {len(clis)} cli version(s) into {args.registry}")
    common.log(f"source-repo {args.source_repo}")
    if args.dry_run:
        common.log("(dry run — no images will be built or pushed)")

    for cli in clis:
        build_one_cli(cli, args)

        # Single-arch already pushed straight to the list tag, so there is no
        # per-arch list to assemble — only --arch all needs the manifest step.
        if args.arch == "all" and not args.skip_manifests:
            manifest_argv = ["--stellar-cli-version", cli, "--registry", args.registry]
            if args.dry_run:
                manifest_argv.append("--dry-run")
            publish_manifests.main(manifest_argv)

        if args.aliases:
            alias_argv = ["--stellar-cli-version", cli, "--registry", args.registry]
            if args.dry_run:
                alias_argv.append("--dry-run")
            publish_aliases.main(alias_argv)

    common.log("")
    common.log(f"done: {len(clis)} cli version(s) processed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
