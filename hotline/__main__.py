"""Module entry point so ``python -m hotline`` runs the CLI.

The import is kept at module top so ``python -m hotline`` resolves once
``cli.py`` exists (delivered in a later feature); it is only exercised at
runtime, not at import time of the other ``hotline`` modules.
"""

from hotline.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
