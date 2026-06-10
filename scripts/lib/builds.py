"""Read, write, and query builds.json.

On-disk format: keys sorted at every level, 2-space indent, trailing
newline. Writes go through `dump()` which writes to a tempfile in the
same directory and then `os.replace()`s into place so a partially-
written file never lands.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from lib import rust_keys, semver

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PATH = REPO_ROOT / "builds.json"


def load(path: Path | None = None) -> dict[str, Any]:
    target = path or DEFAULT_PATH
    return json.loads(target.read_text())


def dump(data: dict[str, Any], path: Path | None = None) -> None:
    target = path or DEFAULT_PATH
    encoded = json.dumps(data, indent=2, sort_keys=True) + "\n"
    parent = target.parent
    fd, tmp_name = tempfile.mkstemp(prefix=".builds.", suffix=".json", dir=parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(encoded)
        os.replace(tmp_name, target)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def find_cli(data: dict[str, Any], version: str) -> dict[str, Any] | None:
    for entry in data.get("stellar_cli_versions", []):
        if entry.get("version") == version:
            return entry
    return None


def stellar_cli_ref(data: dict[str, Any], version: str) -> str:
    entry = find_cli(data, version)
    if entry is None or not entry.get("ref"):
        raise ValueError(f"no stellar_cli_versions entry for version: {version}")
    return entry["ref"]


def split_entry(pin: str) -> tuple[str, str]:
    """Split a rust base pin into its (label, digest) parts.

    A pin is `<rust_base_key>@<image_digest>`, e.g.
    `1.94.0-slim-trixie@sha256:<64 hex>`. The label drives the upstream
    `rust:<label>` base and the published tag's `rust<label>` segment;
    the digest pins the exact base bytes.
    """
    label, sep, digest = pin.partition("@")
    if not sep or not digest:
        raise ValueError(f"invalid rust base pin (expected <label>@<digest>): {pin}")
    return label, digest


def label_of(pin: str) -> str:
    return split_entry(pin)[0]


def digest_of(pin: str) -> str:
    return split_entry(pin)[1]


def assert_pair_declared(data: dict[str, Any], cli: str, rust_pin: str) -> None:
    entry = find_cli(data, cli)
    if entry is None or rust_pin not in entry.get("rust_versions", []):
        raise ValueError(
            f"stellar-cli {cli} is not declared with rust base pin {rust_pin} in builds.json"
        )


def resolve_rust_digest(
    data: dict[str, Any], cli: str, label: str, digest: str | None = None
) -> str:
    """Resolve the pinned base digest for a (cli, rust label) pair.

    When `digest` is given, assert the exact `<label>@<digest>` pin is declared
    and return it. When `digest` is omitted, return the sole digest declared for
    the label; raise if the label is undeclared, or if it carries more than one
    digest (the caller must then disambiguate with an explicit digest).
    """
    if digest is not None:
        assert_pair_declared(data, cli, f"{label}@{digest}")
        return digest

    entry = find_cli(data, cli)
    if entry is None:
        raise ValueError(f"unknown stellar-cli version: {cli}")
    pins = [pin for pin in entry.get("rust_versions", []) if label_of(pin) == label]
    if not pins:
        raise ValueError(f"stellar-cli {cli} is not declared with rust base {label} in builds.json")
    if len(pins) > 1:
        choices = ", ".join(digest_of(pin) for pin in pins)
        raise ValueError(
            f"stellar-cli {cli} declares multiple digests for rust base {label}; "
            f"pass --rust-image-digest to select one of: {choices}"
        )
    return digest_of(pins[0])


def derive_default_rust(data: dict[str, Any], cli: str) -> str:
    distro = data.get("default_distro")
    if not distro:
        raise ValueError("builds.json is missing default_distro")
    suffix = f"slim-{distro}"
    entry = find_cli(data, cli)
    if entry is None:
        raise ValueError(f"unknown stellar-cli version: {cli}")
    matches = [
        (semver.parse(rust_keys.version_of(label_of(pin))), idx, pin)
        for idx, pin in enumerate(entry.get("rust_versions", []))
        if label_of(pin).endswith(f"-{suffix}")
    ]
    if not matches:
        raise ValueError(
            f"no rust_versions[] pin matches default_distro {distro!r} "
            f"(suffix {suffix!r}) for stellar-cli {cli}"
        )
    # Highest rust version wins; among equal versions (a relabelled base), the
    # last-appended pin — the freshest digest — wins.
    matches.sort(key=lambda t: (t[0], t[1]))
    return matches[-1][2]
