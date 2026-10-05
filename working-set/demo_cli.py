"""Handle user interruption at the outer CLI boundary, after async cleanup."""

import sys
from collections.abc import Callable


def run_cli(main: Callable[[], None], *, stderr: bool = False) -> None:
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Goodbye!", file=sys.stderr if stderr else sys.stdout, flush=True)
