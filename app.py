from __future__ import annotations

import logging
import sys

from qt_controller import run_app
from version import APP_VERSION


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger(__name__).info("启动 ArkosGameMan v%s", APP_VERSION)
    sys.exit(run_app())
if __name__ == "__main__":
    main()
