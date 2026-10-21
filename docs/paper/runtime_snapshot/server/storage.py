"""Atomic JSON files that tolerate short-lived Windows reader/scanner locks."""

import json
import logging
import os
from pathlib import Path
import tempfile
import time


RETRY_SECONDS = 10.0
WINDOWS_LOCK_ERRORS = {5, 32, 33}  # Access denied, sharing violation, lock violation.


def retry_file_operation(operation, *args, **kwargs):
    deadline = time.monotonic() + RETRY_SECONDS
    delay = 0.01
    while True:
        try:
            return operation(*args, **kwargs)
        except OSError as exc:
            remaining = deadline - time.monotonic()
            if getattr(exc, "winerror", None) not in WINDOWS_LOCK_ERRORS or remaining <= 0:
                raise
            time.sleep(min(delay, remaining))
            delay = min(delay * 2, 0.25)


def atomic_json(path, data):
    path = Path(path)
    # ASCII JSON also round-trips through legacy locale-dependent Windows readers.
    payload = json.dumps(data, ensure_ascii=True, allow_nan=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Each writer owns its temporary file; keep it beside the destination so
    # os.replace remains atomic, and close it before replacing on Windows.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
    try:
        retry_file_operation(os.replace, temporary, path)
    except OSError:
        # Do not delete the old destination or discard the recoverable new result.
        logging.error("Could not replace %s; new JSON retained at %s", path, temporary)
        raise


def unlink_file(path):
    retry_file_operation(Path(path).unlink, missing_ok=True)
