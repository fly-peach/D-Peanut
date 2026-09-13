"""Workspace secrets store: the single home for sensitive values (SQL conn strings,
LLM api keys from N3 onward). Plaintext NEVER enters sqlite, API responses, logs or prompts.

File format: {"<key>": "<secret value>", ...}, written atomically at mode 0600
(chmod is a no-op on Windows; the docker deploy target is Linux).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_MASK = "****"


class SecretsStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    # -- io ------------------------------------------------------------------

    def ensure(self) -> None:
        """Create an empty store at 0600 if absent."""
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._write({})

    def read_all(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, str]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self._path)
        os.chmod(self._path, 0o600)

    # -- access --------------------------------------------------------------

    def get(self, key: str) -> str | None:
        return self.read_all().get(key)

    def set(self, key: str, value: str) -> None:
        data = self.read_all()
        data[key] = value
        self._write(data)

    def delete(self, key: str) -> bool:
        data = self.read_all()
        if key not in data:
            return False
        del data[key]
        self._write(data)
        return True

    def keys(self) -> list[str]:
        return sorted(self.read_all())

    # -- redaction -----------------------------------------------------------

    @staticmethod
    def mask(value: str) -> str:
        """Display-safe form: fixed prefix + last 4 chars only."""
        if len(value) <= 4:
            return _MASK
        return f"{_MASK}{value[-4:]}"

    def masked_view(self) -> dict[str, str]:
        return {k: self.mask(v) for k, v in self.read_all().items()}

    def redact(self, text: str) -> str:
        """Scrub every known secret substring out of log/error text (uniform filter)."""
        for value in self.read_all().values():
            if len(value) >= 6 and value in text:
                text = text.replace(value, "***")
        return text
