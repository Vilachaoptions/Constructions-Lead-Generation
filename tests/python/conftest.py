import sys
from pathlib import Path

# Make the package importable without an install.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
