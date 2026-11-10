"""Settings routes, mounted at /api/settings. No auth: the app listens on
127.0.0.1 only, and nothing here should assume that stays true. No route ever returns an API key."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from . import settings
from .assistant.prompting import DEFAULT_INSTRUCTIONS

router = APIRouter(prefix="/api/settings")


def _fail(e: settings.SettingsError):
    raise HTTPException(e.status, str(e))


@router.get("")
def settings_get():
    return {**settings.snapshot(), "readonly": {"assistant.default_instructions": DEFAULT_INSTRUCTIONS,
                                                                  "hotkeys.reserved": list(settings.RESERVED_HOTKEYS), "hotkeys.labels": settings.HOTKEY_LABELS}}


@router.put("/secrets/{name}")
def secret_put(name: str, body: dict = Body(...)):
    try:
        return settings.set_secret(name, body.get("value"))
    except settings.SettingsError as e:
        _fail(e)


@router.delete("/secrets/{name}")
def secret_delete(name: str):
    try:
        return settings.remove_secret(name)
    except settings.SettingsError as e:
        _fail(e)


@router.post("/runtimes")
def runtime_add(body: dict = Body(...)):
    """Add a connection to another runtime `{kind, name, url, key?}`. The key is stored apart and never returned."""
    try:
        return settings.add_runtime(body.get("kind"), body.get("name"), body.get("url"), body.get("key"))
    except settings.SettingsError as e:
        _fail(e)


@router.put("/runtimes/{rid}")
def runtime_edit(rid: str, body: dict = Body(...)):
    """Change a connection. `key`: a string replaces the key, null removes it, leaving it out keeps it."""
    given = {k: body[k] for k in ("name", "url", "key") if k in body}
    try:
        return settings.edit_runtime(rid, **given)
    except settings.SettingsError as e:
        _fail(e)


@router.delete("/runtimes/{rid}")
def runtime_delete(rid: str):
    try:
        return settings.remove_runtime(rid)
    except settings.SettingsError as e:
        _fail(e)


@router.put("/{section}")
def settings_put(section: str, body: dict = Body(...)):
    """Save some values of one section (nested like the GET answer). null puts a value back to its default."""
    try:
        return settings.update(section, body)
    except settings.SettingsError as e:
        _fail(e)
