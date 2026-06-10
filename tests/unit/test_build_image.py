import subprocess
from unittest.mock import MagicMock

import pytest

import build_image

DIGEST = "sha256:f7bf1c266d9e48c8d724733fd97ba60464c44b743eb4f46f935577d3242d81d0"


def _completed() -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="")


def test_main_invokes_docker_with_build_args(
    monkeypatch: pytest.MonkeyPatch, minimal_builds: dict
) -> None:
    monkeypatch.setattr(build_image.builds, "load", lambda: minimal_builds)
    monkeypatch.setattr(build_image.common, "preflight_checks", lambda _: None)
    captured = MagicMock(return_value=_completed())
    monkeypatch.setattr(build_image.runner, "run", captured)

    rc = build_image.main(
        [
            "--stellar-cli-version",
            "26.0.0",
            "--rust-version",
            "1.94.0-slim-trixie",
            "--rust-image-digest",
            DIGEST,
        ]
    )

    assert rc == 0
    args = captured.call_args[0][0]
    assert args[0:3] == ["docker", "buildx", "build"]
    assert "--load" in args
    assert "--tag" in args
    assert "stellar-cli:26.0.0-rust1.94.0-slim-trixie" in args
    assert "RUST_VERSION=1.94.0" in args
    assert "RUST_BASE_SUFFIX=slim-trixie" in args
    assert "STELLAR_CLI_VERSION=26.0.0" in args
    assert f"RUST_IMAGE_DIGEST={DIGEST}" in args


def test_main_respects_platform_flag(monkeypatch: pytest.MonkeyPatch, minimal_builds: dict) -> None:
    monkeypatch.setattr(build_image.builds, "load", lambda: minimal_builds)
    monkeypatch.setattr(build_image.common, "preflight_checks", lambda _: None)
    captured = MagicMock(return_value=_completed())
    monkeypatch.setattr(build_image.runner, "run", captured)

    build_image.main(
        [
            "--stellar-cli-version",
            "26.0.0",
            "--rust-version",
            "1.94.0-slim-trixie",
            "--rust-image-digest",
            DIGEST,
            "--platform",
            "linux/arm64",
        ]
    )

    args = captured.call_args[0][0]
    assert "--platform" in args
    assert "linux/arm64" in args


def test_main_respects_custom_tag(monkeypatch: pytest.MonkeyPatch, minimal_builds: dict) -> None:
    monkeypatch.setattr(build_image.builds, "load", lambda: minimal_builds)
    monkeypatch.setattr(build_image.common, "preflight_checks", lambda _: None)
    captured = MagicMock(return_value=_completed())
    monkeypatch.setattr(build_image.runner, "run", captured)

    build_image.main(
        [
            "--stellar-cli-version",
            "26.0.0",
            "--rust-version",
            "1.94.0-slim-trixie",
            "--rust-image-digest",
            DIGEST,
            "--tag",
            "my-local:test",
        ]
    )

    args = captured.call_args[0][0]
    assert "my-local:test" in args


def test_main_infers_digest_when_unambiguous(
    monkeypatch: pytest.MonkeyPatch, minimal_builds: dict
) -> None:
    # minimal_builds declares 26.0.0 with a single 1.94.0-slim-trixie pin, so the
    # digest can be resolved without --rust-image-digest.
    monkeypatch.setattr(build_image.builds, "load", lambda: minimal_builds)
    monkeypatch.setattr(build_image.common, "preflight_checks", lambda _: None)
    captured = MagicMock(return_value=_completed())
    monkeypatch.setattr(build_image.runner, "run", captured)

    rc = build_image.main(
        [
            "--stellar-cli-version",
            "26.0.0",
            "--rust-version",
            "1.94.0-slim-trixie",
        ]
    )

    # Expect the sole digest the fixture declares for this (cli, label), so the
    # assertion can't drift from the digest build_image actually infers.
    expected_digest = minimal_builds["stellar_cli_versions"][0]["rust_versions"][0].split("@", 1)[1]
    assert rc == 0
    args = captured.call_args[0][0]
    assert f"RUST_IMAGE_DIGEST={expected_digest}" in args


def test_main_dies_when_digest_omitted_and_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Two digests share the 1.94.0-slim-trixie label → the digest must be given.
    ambiguous = {
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
    monkeypatch.setattr(build_image.builds, "load", lambda: ambiguous)
    monkeypatch.setattr(build_image.common, "preflight_checks", lambda _: None)
    monkeypatch.setattr(build_image.runner, "run", lambda *_, **__: _completed())

    with pytest.raises(SystemExit):
        build_image.main(
            [
                "--stellar-cli-version",
                "26.0.0",
                "--rust-version",
                "1.94.0-slim-trixie",
            ]
        )


def test_main_dies_for_undeclared_pair(
    monkeypatch: pytest.MonkeyPatch, minimal_builds: dict
) -> None:
    monkeypatch.setattr(build_image.builds, "load", lambda: minimal_builds)
    monkeypatch.setattr(build_image.common, "preflight_checks", lambda _: None)
    monkeypatch.setattr(build_image.runner, "run", lambda *_, **__: _completed())

    with pytest.raises(SystemExit):
        build_image.main(
            [
                "--stellar-cli-version",
                "26.0.0",
                "--rust-version",
                "1.99.0-slim-trixie",
                "--rust-image-digest",
                DIGEST,
            ]
        )
