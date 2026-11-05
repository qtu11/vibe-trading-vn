"""Operator-only discovery of running Windows terminals; no credential scraping."""

import hashlib
import json
import os
import subprocess

from .adapters.mt5 import probe_terminal
from .errors import ForexError
from .models import Connection


def running_terminals():
    if os.name != "nt":
        raise ForexError("WINDOWS_REQUIRED", "Automatic local MT5 attachment requires Windows")
    try:
        response = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); @(Get-CimInstance Win32_Process -Filter \"Name = 'terminal64.exe'\" | Select-Object -ExpandProperty ExecutablePath -Unique) | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            timeout=15,
            creationflags=0x08000000,
        )
        if response.returncode != 0:
            raise ForexError("DISCOVERY_UNAVAILABLE", "Windows could not enumerate running MT5 terminals")
        paths = json.loads(response.stdout or "[]")
        return [paths] if isinstance(paths, str) else paths or []
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ForexError("DISCOVERY_UNAVAILABLE", "Cannot enumerate running MT5 terminals") from exc


def attach_running(service):
    attached, issues = [], []
    for path in running_terminals()[:10]:
        try:
            identity = probe_terminal(path)
            # Autoconnect never enables execution or guesses a native symbol.
            existing = next(
                (
                    c
                    for c in service.store.connections()
                    if c.connector == "mt5"
                    and c.terminal_path.casefold() == path.casefold()
                    and c.account_ref == identity["account_ref"]
                    and c.server == identity["server"]
                    and c.environment == identity["environment"]
                ),
                None,
            )
            if existing and existing.session_mode != "existing_terminal":
                # Preserve a separately configured credential connection.
                attached.append(existing.model_dump(mode="json"))
                continue
            config = existing or Connection(
                id="mt5-"
                + hashlib.sha256((path.casefold() + identity["server"] + identity["account_ref"]).encode()).hexdigest()[
                    :16
                ],
                label="MT5 · " + identity["server"],
                connector="mt5",
                account_ref=identity["account_ref"],
                environment=identity["environment"],
                terminal_path=path,
                server=identity["server"],
                session_mode="existing_terminal",
            )
            if existing is None:
                service.save_connection(config)
            attached.append(config.model_dump(mode="json"))
        except ForexError as exc:
            issues.append({"terminal_path": path, "code": exc.code, "error": str(exc)})
    return {"connections": attached, "issues": issues}
