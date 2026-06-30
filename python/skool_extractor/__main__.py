"""Enable ``python -m skool_extractor``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
