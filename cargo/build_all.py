#!/usr/bin/env -S uv run python
"""Build and publish the cargo build image for every rust version in builds_rust.json.

This is the cargo analogue of scripts/build_all.py, but radically simpler:
there is no (cli x rust) matrix here, just a flat list of rust base pins. For
each pin we build cargo/Dockerfile.cargo on top of the pinned `rust:<label>`
base and push it to `<registry>:<rust_version>` (e.g. docker.io/vrfier/rust:1.94.0).

The image is a thin customization of the upstream rust base (apt deps + wasm
targets + a non-root user), so each build is fast and mostly cache hits.

Each builds_rust.json entry is a pin `<label>@<digest>`, e.g.
`1.94.0-slim-trixie@sha256:...`. We split it into:
  RUST_VERSION       1.94.0        -> also the published tag
  RUST_BASE_SUFFIX   slim-trixie
  RUST_IMAGE_DIGEST  sha256:...    -> pins the exact FROM bytes

Pushing is outward-facing: run with --dry-run first to print the exact
commands, and make sure you are logged in to the registry (`docker login`)
before a real run.
"""

import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILDS_FILE = HERE / "builds_rust.json"
DOCKERFILE = HERE / "Dockerfile.cargo"

DEFAULT_REGISTRY = "docker.io/vrfier/rust"
DEFAULT_SOURCE_REPO = "vrfier/stellar-cli-docker"
DEFAULT_PLATFORM = "linux/amd64"

# Version is always three dotted ints; suffix is everything after the first dash.
_PIN = re.compile(r"^(?P<version>[0-9]+\.[0-9]+\.[0-9]+)-(?P<suffix>[^@]+)@(?P<digest>sha256:[0-9a-f]+)$")


def log(message: str) -> None:
    print(message, file=sys.stderr)


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def parse_pin(pin: str) -> tuple[str, str, str]:
    """Split `<version>-<suffix>@<digest>` into (version, suffix, digest)."""
    match = _PIN.match(pin.strip())
    if match is None:
        raise ValueError(f"invalid rust base pin: {pin!r} (expected <version>-<suffix>@sha256:...)")
    return match["version"], match["suffix"], match["digest"]


def load_pins(only_version: str) -> list[str]:
    data = json.loads(BUILDS_FILE.read_text())
    pins = data.get("rust_versions", [])
    if not only_version:
        return pins
    kept = [p for p in pins if parse_pin(p)[0] == only_version]
    if not kept:
        die(f"rust {only_version} is not declared in {BUILDS_FILE.name}")
    return kept


def require_buildx() -> None:
    if shutil.which("docker") is None:
        die("docker is required (needed for buildx)")
    if subprocess.run(["docker", "buildx", "version"], capture_output=True).returncode != 0:
        die("docker buildx plugin is required; install it or upgrade docker")
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        die("docker daemon is not reachable; start it (e.g. start Docker Desktop / OrbStack)")


def build_one(pin: str, args: argparse.Namespace, build_date: str) -> None:
    version, suffix, digest = parse_pin(pin)
    tag = f"{args.registry}:{version}"

    cmd = ["docker", "buildx", "build", "-f", str(DOCKERFILE)]
    if args.platform:
        cmd += ["--platform", args.platform]
    cmd += [
        "--push" if args.push else "--load",
        "--build-arg", f"RUST_VERSION={version}",
        "--build-arg", f"RUST_BASE_SUFFIX={suffix}",
        "--build-arg", f"RUST_IMAGE_DIGEST={digest}",
        "--build-arg", f"BUILD_DATE={build_date}",
        "--build-arg", f"SOURCE_REPO={args.source_repo}",
        "--tag", tag,
        str(HERE),
    ]

    log(f"building {tag}")
    log(f"  base     rust:{version}-{suffix} ({digest})")
    log(f"  platform {args.platform or '<host native>'}")
    log(f"  output   {'push to registry' if args.push else 'load into local docker'}")
    if args.dry_run:
        log("  " + " ".join(cmd))
        return
    subprocess.run(cmd, check=True)
    log(f"done: {tag}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", default=DEFAULT_REGISTRY, metavar="REF")
    parser.add_argument("--source-repo", default=DEFAULT_SOURCE_REPO, metavar="SLUG")
    parser.add_argument(
        "--rust-version",
        default="",
        metavar="V",
        help="Limit to one rust version (default: every version in builds_rust.json).",
    )
    parser.add_argument(
        "--platform",
        default=DEFAULT_PLATFORM,
        metavar="P",
        help=(
            "buildx --platform value. Default linux/amd64. Pass e.g. "
            "linux/amd64,linux/arm64 for a multi-arch push (requires --push)."
        ),
    )
    parser.add_argument(
        "--load",
        dest="push",
        action="store_false",
        help="Load the image into the local docker instead of pushing it.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print every build command without running anything.",
    )
    parser.set_defaults(push=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.dry_run:
        require_buildx()

    pins = load_pins(args.rust_version)
    build_date = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    log(f"building {len(pins)} image(s) into {args.registry}")
    log(f"source-repo {args.source_repo}")
    if args.dry_run:
        log("(dry run — no images will be built or pushed)")

    for pin in pins:
        build_one(pin, args, build_date)

    log("")
    log(f"done: {len(pins)} image(s) processed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
