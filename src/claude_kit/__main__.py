"""Enable ``python -m claude_kit`` as an alias for the CLI."""

import sys

from claude_kit.cli import main

if __name__ == "__main__":
    sys.exit(main())
