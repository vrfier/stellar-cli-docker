#!/usr/bin/env -S uv run python
"""Build a single stellar-cli image locally for a declared (cli, rust base) pair.

Looks up the pinned base image digest and stellar-cli commit SHA from
builds.json so the build inputs come from one source of truth.
"""

import argparse
import datetime
import sys

import tag_names
from lib import builds, common, runner, rust_keys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stellar-cli-version", required=True, metavar="V")
    parser.add_argument("--rust-version", required=True, metavar="KEY")
    parser.add_argument("--rust-image-digest", default=None, metavar="DIGEST")
    parser.add_argument("--platform", default="", metavar="P")
    parser.add_argument("--tag", default="", metavar="REF")
    parser.add_argument("--source-repo", default="stellar/stellar-cli-docker", metavar="SLUG")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    common.preflight_checks(["buildx"])

    data = builds.load()
    try:
        rust_digest = builds.resolve_rust_digest(
            data, args.stellar_cli_version, args.rust_version, args.rust_image_digest
        )
        stellar_ref = builds.stellar_cli_ref(data, args.stellar_cli_version)
        parsed = rust_keys.parse(args.rust_version)
        entry = builds.find_cli(data, args.stellar_cli_version)
        cli_rust_pin = entry.get("cli_rust_version") if entry else None
        cli_rust_digest = builds.digest_of(cli_rust_pin) if cli_rust_pin else rust_digest
    except ValueError as exc:
        common.die(str(exc))

    tag = args.tag or "stellar-cli:" + tag_names.compose_tag(
        stellar_cli_version=args.stellar_cli_version,
        rust_version=args.rust_version,
    )
    build_date = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    common.log(f"building {tag}")
    common.log(f"  stellar-cli {args.stellar_cli_version}         ({stellar_ref})")
    common.log(f"  rust {args.rust_version}           ({rust_digest})")
    common.log(f"  cli-build rust                ({cli_rust_digest})")
    common.log(f"  base rust:{parsed.version}-{parsed.suffix}")
    common.log(f"  platform {args.platform or '<host native>'}")

    cmd = ["docker", "buildx", "build"]
    if args.platform:
        cmd += ["--platform", args.platform]
    cmd += [
        "--load",
        "--build-arg",
        f"RUST_VERSION={parsed.version}",
        "--build-arg",
        f"RUST_BASE_SUFFIX={parsed.suffix}",
        "--build-arg",
        f"RUST_IMAGE_DIGEST={rust_digest}",
        "--build-arg",
        f"CLI_RUST_IMAGE_DIGEST={cli_rust_digest}",
        "--build-arg",
        f"STELLAR_CLI_REV={stellar_ref}",
        "--build-arg",
        f"STELLAR_CLI_VERSION={args.stellar_cli_version}",
        "--build-arg",
        f"BUILD_DATE={build_date}",
        "--build-arg",
        f"SOURCE_REPO={args.source_repo}",
        "--tag",
        tag,
        str(common.repo_root()),
    ]
    runner.run(cmd)

    common.log("")
    common.log(f"built: {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
