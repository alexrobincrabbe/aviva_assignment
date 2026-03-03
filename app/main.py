"""Shim module to maintain backward compatibility with `python -m app.main`."""

from app.cli.main import main

if __name__ == '__main__':
    main()
