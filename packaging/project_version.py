import sys
import tomllib
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("pyproject.toml")
print(tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"])
