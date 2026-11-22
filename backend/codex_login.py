"""Sign in to the same Codex home as the dashboard worker."""
import os
import shutil
import subprocess

from .config import Settings


def main():
    home = Settings().codex_home.resolve()
    home.mkdir(parents=True, exist_ok=True)
    executable = shutil.which("codex")
    if not executable:
        raise SystemExit("Install the Codex CLI before signing in.")
    return subprocess.call([executable, "login"], env={**os.environ, "CODEX_HOME": str(home)})


if __name__ == "__main__":
    raise SystemExit(main())
