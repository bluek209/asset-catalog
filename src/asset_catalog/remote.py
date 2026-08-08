from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import urlopen

from .app_publishing import PublicationVerificationError, verify_site
from .crypto_publishing import CryptoPublicationVerificationError, verify_crypto_site


class RemoteStateError(RuntimeError):
    pass


OpenBytes = Callable[[str, float], bytes]


def _download(url: str, timeout: float) -> bytes:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - caller supplies HTTPS Pages URL
        return response.read()


def _relative(raw: object) -> str:
    value = str(raw)
    path = PurePosixPath(value)
    if path.is_absolute() or not value or any(part in {"", ".", ".."} for part in path.parts):
        raise RemoteStateError("remote manifest contains an unsafe path")
    return value


def hydrate_site(
    base_url: str,
    site_root: Path,
    *,
    opener: OpenBytes = _download,
    timeout: float = 30.0,
) -> bool:
    normalized = base_url.rstrip("/") + "/"
    site_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{site_root.name}-hydrate-", dir=site_root.parent))
    try:
        stock_found = _hydrate_manifest_tree(
            normalized,
            staging,
            opener=opener,
            timeout=timeout,
            optional=True,
            verifier=verify_site,
        )
        if not stock_found:
            return False
        _hydrate_manifest_tree(
            urljoin(normalized, "crypto/"),
            staging / "crypto",
            opener=opener,
            timeout=timeout,
            optional=True,
            verifier=verify_crypto_site,
        )
        _replace_tree(staging, site_root)
        return True
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _hydrate_manifest_tree(
    base_url: str,
    destination: Path,
    *,
    opener: OpenBytes,
    timeout: float,
    optional: bool,
    verifier: Callable[[Path], None],
) -> bool:
    try:
        manifest_data = opener(urljoin(base_url, "manifest.json"), timeout)
    except HTTPError as error:
        if optional and error.code == 404:
            return False
        raise RemoteStateError("remote catalog could not be downloaded") from error
    except Exception as error:
        raise RemoteStateError("remote catalog could not be downloaded") from error
    try:
        manifest = json.loads(manifest_data.decode("utf-8"))
        paths = [_relative(manifest["f"]["p"])]
        paths.extend(_relative(entry["p"]) for entry in manifest.get("d", {}).values())
    except Exception as error:
        raise RemoteStateError("remote manifest is invalid") from error

    destination.mkdir(parents=True, exist_ok=True)
    (destination / "manifest.json").write_bytes(manifest_data)
    for relative in paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_bytes(opener(urljoin(base_url, relative), timeout))
        except Exception as error:
            raise RemoteStateError("remote catalog could not be downloaded") from error
    try:
        verifier(destination)
    except (PublicationVerificationError, CryptoPublicationVerificationError) as error:
        raise RemoteStateError("remote catalog verification failed") from error
    return True


def _replace_tree(staging: Path, destination: Path) -> None:
    backup = destination.parent / f".{destination.name}-hydrate-backup"
    if backup.exists():
        shutil.rmtree(backup)
    if destination.exists():
        destination.replace(backup)
    try:
        staging.replace(destination)
    except Exception:
        if backup.exists():
            backup.replace(destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)
