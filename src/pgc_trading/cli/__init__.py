"""Command-line interface package for PGC trading workflows."""

from __future__ import annotations


def main(*args: object, **kwargs: object) -> int:
    from pgc_trading.cli.main import main as cli_main

    return cli_main(*args, **kwargs)


__all__ = ["main"]
