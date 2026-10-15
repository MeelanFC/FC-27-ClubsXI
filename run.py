"""Start ClubsXI without installing anything.

  python run.py check    confirm the clubs resolve
  python run.py poll     one cycle, then exit
  python run.py run      poll forever
  python run.py status   what is in the database
  python run.py web      start the viewer

Settings come from environment variables. If a file named .env is next to
this file, its values are used for any variable that is not already set.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (x.strip() for x in line.split("=", 1))
        if value:
            os.environ.setdefault(key, value)


load_env_file(ROOT / ".env")
sys.path.insert(0, str(ROOT / "src"))

from clubsxi.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
