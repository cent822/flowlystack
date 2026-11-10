"""What every write must do afterwards, the way the HTTP routes do it: keep the search indexes in step with the files. Imports are lazy so the
protocol layer loads under a bare python3."""
from __future__ import annotations


def studio_changed() -> None:
    from .. import studio_api
    from ..rag import service
    studio_api.sync_search()
    service.kick()


def linkshell_changed() -> None:
    from .. import linkshell_api
    linkshell_api.sync_search()
