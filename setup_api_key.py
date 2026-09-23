"""Store the ALIVE demo's OpenAI API key outside the repository."""

from __future__ import annotations

import getpass
import os
from pathlib import Path


KEY_FILE = Path.home() / ".config" / "alive" / "openai_api_key"


def main() -> None:
    key = getpass.getpass("New OpenAI API key (input hidden): ").strip()
    if not key.startswith("sk-") or any(char.isspace() for char in key):
        raise SystemExit("No valid-looking API key entered; file unchanged")
    KEY_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(KEY_FILE.parent, 0o700)
    descriptor = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(key + "\n")
    os.chmod(KEY_FILE, 0o600)
    print(f"Key saved to {KEY_FILE}; press Send on the ALIVE page to test it")


if __name__ == "__main__":
    main()
