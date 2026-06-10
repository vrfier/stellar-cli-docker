import json
from pathlib import Path

import pytest

from lib import builds


def test_load_default_path() -> None:
    data = builds.load()
    assert "stellar_cli_versions" in data


def test_load_explicit_path(fixtures_dir: Path) -> None:
    data = builds.load(fixtures_dir / "builds_minimal.json")
    assert data["default_distro"] == "trixie"


def test_dump_writes_sorted_pretty_with_trailing_newline(
    tmp_path: Path, minimal_builds: dict
) -> None:
    target = tmp_path / "out.json"
    builds.dump(minimal_builds, target)
    text = target.read_text()
    assert text.endswith("\n")
    reloaded = json.loads(text)
    assert reloaded == minimal_builds
    # Sorted at the root level.
    root_keys = [line.split('"')[1] for line in text.splitlines() if line.startswith('  "')]
    assert root_keys == sorted(root_keys)


def test_dump_matches_existing_builds_json_byte_for_byte(tmp_path: Path) -> None:
    # Round-tripping the real builds.json through dump() must produce the same
    # bytes already on disk. If this drifts, refresh-* scripts will emit noisy
    # whitespace diffs into git.
    on_disk = builds.DEFAULT_PATH.read_text()
    target = tmp_path / "out.json"
    builds.dump(builds.load(), target)
    assert target.read_text() == on_disk


def test_dump_is_atomic(tmp_path: Path, minimal_builds: dict) -> None:
    target = tmp_path / "out.json"
    target.write_text("preexisting")
    builds.dump(minimal_builds, target)
    assert json.loads(target.read_text()) == minimal_builds
    # No leftover tempfiles.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".builds.")]
    assert leftovers == []


def test_find_cli_returns_entry(multi_cli_builds: dict) -> None:
    entry = builds.find_cli(multi_cli_builds, "26.0.0")
    assert entry is not None
    assert entry["ref"] == "60f7458e7ecffddf2f2d91dc6d0d2db4fab03ecc"


def test_find_cli_returns_none_for_unknown(multi_cli_builds: dict) -> None:
    assert builds.find_cli(multi_cli_builds, "99.0.0") is None


def test_stellar_cli_ref_known(multi_cli_builds: dict) -> None:
    assert builds.stellar_cli_ref(multi_cli_builds, "25.1.0").startswith("a048a57")


def test_stellar_cli_ref_unknown(multi_cli_builds: dict) -> None:
    with pytest.raises(ValueError, match="no stellar_cli_versions entry"):
        builds.stellar_cli_ref(multi_cli_builds, "99.0.0")


_DIGEST_94 = "sha256:f7bf1c266d9e48c8d724733fd97ba60464c44b743eb4f46f935577d3242d81d0"
_PIN_94 = f"1.94.0-slim-trixie@{_DIGEST_94}"


def test_split_entry_returns_label_and_digest() -> None:
    label, digest = builds.split_entry(_PIN_94)
    assert label == "1.94.0-slim-trixie"
    assert digest == "sha256:f7bf1c266d9e48c8d724733fd97ba60464c44b743eb4f46f935577d3242d81d0"


def test_label_of_and_digest_of() -> None:
    assert builds.label_of(_PIN_94) == "1.94.0-slim-trixie"
    assert builds.digest_of(_PIN_94).startswith("sha256:")


def test_split_entry_rejects_bare_label() -> None:
    with pytest.raises(ValueError, match="invalid rust base pin"):
        builds.split_entry("1.94.0-slim-trixie")


def test_assert_pair_declared_passes(multi_cli_builds: dict) -> None:
    builds.assert_pair_declared(multi_cli_builds, "26.0.0", _PIN_94)


def test_assert_pair_declared_rejects_unknown_cli(multi_cli_builds: dict) -> None:
    with pytest.raises(ValueError, match="not declared"):
        builds.assert_pair_declared(multi_cli_builds, "99.0.0", _PIN_94)


def test_assert_pair_declared_rejects_undeclared_pair(multi_cli_builds: dict) -> None:
    with pytest.raises(ValueError, match="not declared"):
        builds.assert_pair_declared(multi_cli_builds, "25.1.0", _PIN_94)


def test_resolve_rust_digest_returns_sole_digest(minimal_builds: dict) -> None:
    # One pin for the label → digest is unambiguous, no explicit digest needed.
    assert builds.resolve_rust_digest(minimal_builds, "26.0.0", "1.94.0-slim-trixie") == _DIGEST_94


def test_resolve_rust_digest_honors_explicit_digest(multi_cli_builds: dict) -> None:
    assert (
        builds.resolve_rust_digest(multi_cli_builds, "26.0.0", "1.94.0-slim-trixie", _DIGEST_94)
        == _DIGEST_94
    )


def test_resolve_rust_digest_rejects_explicit_undeclared_pin(multi_cli_builds: dict) -> None:
    with pytest.raises(ValueError, match="not declared"):
        builds.resolve_rust_digest(
            multi_cli_builds, "26.0.0", "1.94.0-slim-trixie", "sha256:" + "0" * 64
        )


def test_resolve_rust_digest_rejects_undeclared_label(minimal_builds: dict) -> None:
    with pytest.raises(ValueError, match="not declared"):
        builds.resolve_rust_digest(minimal_builds, "26.0.0", "1.99.0-slim-trixie")


def test_resolve_rust_digest_requires_digest_when_ambiguous() -> None:
    # Same label carrying two digests → caller must disambiguate.
    data = {
        "default_distro": "trixie",
        "stellar_cli_versions": [
            {
                "ref": "a" * 40,
                "version": "26.0.0",
                "rust_versions": [
                    "1.94.0-slim-trixie@sha256:" + "a" * 64,
                    "1.94.0-slim-trixie@sha256:" + "b" * 64,
                ],
            }
        ],
    }
    with pytest.raises(ValueError, match="multiple digests"):
        builds.resolve_rust_digest(data, "26.0.0", "1.94.0-slim-trixie")


def test_derive_default_rust_picks_highest_matching_suffix(multi_cli_builds: dict) -> None:
    assert builds.derive_default_rust(multi_cli_builds, "26.0.0") == _PIN_94


def test_derive_default_rust_newest_digest_for_repeated_label() -> None:
    # When a label carries two digests, the newest (last appended) wins.
    newest = "1.94.0-slim-trixie@sha256:" + "b" * 64
    data = {
        "default_distro": "trixie",
        "stellar_cli_versions": [
            {
                "ref": "a" * 40,
                "version": "26.0.0",
                "rust_versions": [
                    "1.94.0-slim-trixie@sha256:" + "a" * 64,
                    newest,
                ],
            }
        ],
    }
    assert builds.derive_default_rust(data, "26.0.0") == newest


def test_derive_default_rust_skips_non_matching_suffix(multi_cli_builds: dict) -> None:
    # 25.1.0 has only bookworm; default_distro is trixie → no match.
    with pytest.raises(ValueError, match="no rust_versions"):
        builds.derive_default_rust(multi_cli_builds, "25.1.0")


def test_derive_default_rust_missing_default_distro(multi_cli_builds: dict) -> None:
    data = {**multi_cli_builds}
    del data["default_distro"]
    with pytest.raises(ValueError, match="missing default_distro"):
        builds.derive_default_rust(data, "26.0.0")


def test_derive_default_rust_unknown_cli(multi_cli_builds: dict) -> None:
    with pytest.raises(ValueError, match="unknown"):
        builds.derive_default_rust(multi_cli_builds, "99.0.0")
