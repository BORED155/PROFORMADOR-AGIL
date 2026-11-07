"""Punto de entrada."""

from __future__ import annotations

import sys


def main() -> int:
    from .ui.aplicacion import ejecutar

    return ejecutar(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
