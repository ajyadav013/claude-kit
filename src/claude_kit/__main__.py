"""Enable ``python -m claude_kit`` as an alias for the CLI."""

from claude_kit.cli import main

if __name__ == "__main__":
    main()  # Typer's app() raises SystemExit with the right code itself.
