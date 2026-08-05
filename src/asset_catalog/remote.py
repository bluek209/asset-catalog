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
    try:
        manifest_data = opener(urljoin(normalized, "manifest.json"), timeout)
    except HTTPError as error:
        if error.code == 404:
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

    site_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{site_root.name}-hydrate-", dir=site_root.parent))
    try:
        (staging / "manifest.json").write_bytes(manifest_data)
        for relative in paths:
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.write_bytes(opener(urljoin(normalized, relative), timeout))
            except Exception as error:
                raise RemoteStateError("remote catalog could not be downloaded") from error
        try:
            verify_site(staging)
        except PublicationVerificationError as error:
            raise RemoteStateError("remote catalog verification failed") from error
        if site_root.exists():
            shutil.rmtree(site_root)
        staging.replace(site_root)
        return True
    finally:
        if staging.exists():
            shutil.rmtree(staging)
