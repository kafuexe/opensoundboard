"""Entry point: the app, or `--admin <command>` for the mic plugin steps that need admin."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--admin"]:
        from .micplugin.admin import main as admin_main
        sys.exit(admin_main(argv[1:]))
    from .ui.app import main as app_main
    app_main()
