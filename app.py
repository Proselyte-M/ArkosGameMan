from __future__ import annotations

import logging
import sys

from qt_controller import run_app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    sys.exit(run_app())


if __name__ == "__main__":
    main()
