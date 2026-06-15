#!/usr/bin/env -S uv run python
"""Smoke-test a built image.

Verifies the binary reports the expected version, that
`contract build --help` works offline, and that the org.opencontainers.*
labels carry the values they should — including the base.digest
cross-checked against builds.json.
"""

import argparse
import json
import sys

from lib import builds, common, runner, rust_keys


def check_version_output(image: str, expected: str) -> bool:
    common.log(f"checking 'stellar version --only-version' == {expected} ...")
    got = runner.capture(["docker", "run", "--rm", image, "version", "--only-version"]).strip()
    if got == expected:
        common.log("  ok")
        return True
    common.err(f"  version mismatch: got '{got}', expected '{expected}'")
    return False


def check_contract_build_help(image: str) -> bool:
    common.log("checking 'stellar contract build --help' runs offline ...")
    result = runner.run(
        ["docker", "run", "--rm", "--network=none", image, "contract", "build", "--help"],
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        common.log("  ok")
        return True
    common.err("  'contract build --help' failed under --network=none")
    return False


def check_labels(
    image: str,
    *,
    cli: str,
    stellar_ref: str,
    rust_version: str,
    rust_base_suffix: str,
    rust_image_digest: str,
) -> bool:
    common.log("checking OCI image labels ...")
    raw = runner.capture(["docker", "inspect", "--format", "{{json .Config.Labels}}", image])
    labels = json.loads(raw)

    expected_base_name = f"docker.io/library/rust:{rust_version}-{rust_base_suffix}"
    expectations = {
        "org.opencontainers.image.version": cli,
        "org.opencontainers.image.revision": stellar_ref,
        "org.opencontainers.image.base.name": expected_base_name,
    }
    # The pinned base digest is optional: callers that don't pass one (e.g. the
    # CI smoke step) skip this cross-check rather than fail on a missing value.
    if rust_image_digest:
        expectations["org.opencontainers.image.base.digest"] = rust_image_digest
    ok = True
    for key, want in expectations.items():
        got = labels.get(key, "<missing>")
        if got != want:
            common.err(f"  label {key}: got '{got}', expected '{want}'")
            ok = False
    if ok:
        common.log("  ok")
    return ok


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--image", required=True, metavar="REF")
    parser.add_argument("--stellar-cli-version", required=True, metavar="V")
    parser.add_argument("--rust-version", required=True, metavar="KEY")
    parser.add_argument("--rust-image-digest", required=False, metavar="DIGEST")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    common.preflight_checks(["buildx"])

    data = builds.load()
    try:
        parsed = rust_keys.parse(args.rust_version)
        stellar_ref = builds.stellar_cli_ref(data, args.stellar_cli_version)
    except ValueError as exc:
        common.die(str(exc))

    ok = True
    ok &= check_version_output(args.image, args.stellar_cli_version)
    ok &= check_contract_build_help(args.image)
    ok &= check_labels(
        args.image,
        cli=args.stellar_cli_version,
        stellar_ref=stellar_ref,
        rust_version=parsed.version,
        rust_base_suffix=parsed.suffix,
        rust_image_digest=args.rust_image_digest,
    )

    if ok:
        common.log(f"smoke-test: image {args.image} passed all checks")
        return 0
    common.err(f"smoke-test: image {args.image} FAILED one or more checks")
    return 1


if __name__ == "__main__":
    sys.exit(main())
