"""TLS / CA bundle helpers — system + MinDigital + corporate CAs in containers."""

from __future__ import annotations

import os
from pathlib import Path

CERTS_DIR_ENV = "FM21_CERTS_DIR"
EXTRA_CERTS_DIRS_ENV = "FM21_EXTRA_CERTS_DIRS"
CA_BUNDLE_ENV = "FM21_CA_BUNDLE"
CA_BUNDLE_CACHE_ENV = "FM21_CA_BUNDLE_CACHE"
SYSTEM_CA_PATH = "/etc/ssl/certs/ca-certificates.crt"
DEFAULT_CERTS_DIR = "/certs"
DEFAULT_EXTRA_CERTS_DIRS = ("ca-certificates-21",)
DEFAULT_BUNDLE_CACHE = "/tmp/fm21_ca_bundle.pem"
CERT_SUFFIXES = (".pem", ".crt")

ROOT_CA_NAME = "russian_trusted_root_ca.pem"
SUB_CA_NAME = "russian_trusted_sub_ca.pem"


def _verify_disabled(env_name: str, *, default: str = "true") -> bool:
    raw = os.environ.get(env_name, default).strip().lower()
    return raw in {"0", "false", "no", "off"}


def _extra_cert_dirs(certs_dir: Path) -> list[Path]:
    raw = os.environ.get(EXTRA_CERTS_DIRS_ENV, "").strip()
    if raw:
        names = [part.strip() for part in raw.split(",") if part.strip()]
    else:
        names = list(DEFAULT_EXTRA_CERTS_DIRS)
    return [certs_dir / name for name in names]


def _collect_cert_files(certs_dir: Path) -> list[Path]:
    """System store + corporate dir + Russian MinDigital PEMs at certs root."""
    files: list[Path] = []

    system_ca = Path(SYSTEM_CA_PATH)
    if system_ca.is_file():
        files.append(system_ca)

    seen: set[Path] = set()
    for extra_dir in _extra_cert_dirs(certs_dir):
        if not extra_dir.is_dir():
            continue
        for path in sorted(extra_dir.iterdir()):
            if path.suffix.lower() in CERT_SUFFIXES and path.is_file():
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    files.append(path)

    for name in (ROOT_CA_NAME, SUB_CA_NAME):
        path = certs_dir / name
        if path.is_file():
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(path)

    return files


def get_ca_bundle_path(*, rebuild: bool = False) -> str | None:
    """Return combined CA bundle path, or None when no cert sources exist."""
    explicit = os.environ.get(CA_BUNDLE_ENV) or os.environ.get("SSL_CERT_FILE")
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return str(path)

    certs_dir = Path(os.environ.get(CERTS_DIR_ENV, DEFAULT_CERTS_DIR))
    cert_files = _collect_cert_files(certs_dir)
    if not cert_files:
        return None

    cache_path = Path(os.environ.get(CA_BUNDLE_CACHE_ENV, DEFAULT_BUNDLE_CACHE))
    source_mtime = max(path.stat().st_mtime for path in cert_files)
    if (
        not rebuild
        and cache_path.is_file()
        and cache_path.stat().st_mtime >= source_mtime
    ):
        return str(cache_path)

    chunks: list[str] = []
    for path in cert_files:
        text = path.read_text(encoding="utf-8").strip()
        if text:
            chunks.append(text)

    cache_path.write_text("\n".join(chunks) + "\n")
    return str(cache_path)


def httpx_verify(*, disable_env: str | None = None) -> bool | str:
    """``verify`` argument for httpx — CA bundle path, True, or False."""
    if disable_env and _verify_disabled(disable_env):
        return False

    bundle = get_ca_bundle_path()
    if bundle:
        return bundle
    return True


def gigachat_ssl_kwargs() -> dict[str, object]:
    """SSL kwargs for official GigaChat SDK client."""
    if _verify_disabled("GIGACHAT_VERIFY_SSL_CERTS"):
        return {"verify_ssl_certs": False}

    bundle = get_ca_bundle_path()
    if bundle:
        return {"verify_ssl_certs": True, "ca_bundle_file": bundle}
    return {"verify_ssl_certs": True}


def salutespeech_verify() -> bool | str:
    """``verify`` for SaluteSpeech httpx clients."""
    return httpx_verify(disable_env="SALUTESPEECH_VERIFY_SSL_CERTS")
