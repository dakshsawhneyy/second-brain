"""Encrypted backup of the memory (cards, archive, profile) into a folder he chooses (e.g. a cloud-synced one).

The zip is encrypted with a key derived from a passphrase he keeps OUTSIDE this machine's .env (otherwise a dead disk
takes the key with it). No passphrase = no backup: a plaintext copy of a private journal is never written.
"""

from __future__ import annotations

import base64
import io
import os
import zipfile
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"SBK1"
SALT_BYTES = 16
FOLDERS = ("cards", "archive", "profile")
PREFIX = "secondbrain-backup-"
SUFFIX = ".sbk"
KEEP = 14


class BackupError(Exception):
    pass


def _key(passphrase: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def _zip_bytes(root: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in FOLDERS:
            base = Path(root) / name
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_file() and not path.name.endswith(".tmp"):
                    zf.write(path, path.relative_to(root).as_posix())
    return buf.getvalue()


def backup_name(now: datetime) -> str:
    return f"{PREFIX}{now.strftime('%Y%m%d')}{SUFFIX}"


def make_backup(root: Path, dest_dir: Path, passphrase: str | None, now: datetime, keep: int = KEEP) -> Path:
    """Write today's encrypted backup (replacing an earlier one from today) and prune to the newest `keep`."""
    if not passphrase:
        raise BackupError("SB_BACKUP_PASSPHRASE is not set: refusing to write an unencrypted copy of your journal")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    salt = os.urandom(SALT_BYTES)
    token = Fernet(_key(passphrase, salt)).encrypt(_zip_bytes(Path(root)))
    path = dest_dir / backup_name(now)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(MAGIC + salt + token)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    for old in sorted(dest_dir.glob(f"{PREFIX}*{SUFFIX}"))[:-keep]:
        old.unlink(missing_ok=True)
    return path


def restore_backup(backup: Path, passphrase: str, target: Path) -> int:
    """Decrypt and extract into `target` (must not already hold cards). Returns the number of files restored."""
    data = Path(backup).read_bytes()
    if not data.startswith(MAGIC) or len(data) < len(MAGIC) + SALT_BYTES:
        raise BackupError("not a second-brain backup file")
    salt = data[len(MAGIC):len(MAGIC) + SALT_BYTES]
    try:
        raw = Fernet(_key(passphrase, salt)).decrypt(data[len(MAGIC) + SALT_BYTES:])
    except InvalidToken as e:
        raise BackupError("wrong passphrase or damaged backup") from e
    target = Path(target)
    if (target / "cards").exists() and any((target / "cards").rglob("*.json")):
        raise BackupError(f"{target / 'cards'} already has cards: restore into an empty folder")
    count = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for info in zf.infolist():
            dest = (target / info.filename).resolve()
            if not str(dest).startswith(str(target.resolve())):
                raise BackupError("unsafe path inside the backup")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(info))
            count += 1
    return count


def backed_up_today(dest_dir: Path | None, now: datetime) -> bool:
    return bool(dest_dir) and (Path(dest_dir) / backup_name(now)).is_file()
