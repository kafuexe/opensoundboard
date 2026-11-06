"""How the plugin is attached to a mic's effect settings (its MMDevices FxProperties key), as pure
functions over a {value name: (kind, data)} dict so they can be tested without a registry.

kind is "String" (REG_SZ, data is a str) or "MultiString" (REG_MULTI_SZ, data is a list of str),
the same spelling the old install.ps1 used in its backups, so those still restore.
"""
from __future__ import annotations

from . import CLSID

EFX = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},7"            # PKEY_FX_EndpointEffectClsid
COMPOSITE_EFX = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},15"  # PKEY_CompositeFX_EndpointEffectClsid
EFX_MODES = "{d3993a3f-99c2-4402-b5ec-a92a0367664b},7"       # PKEY_EFX_ProcessingModes_Supported_For_Streaming
DEFAULT_MODE = "{C18E2F7E-933D-4965-B7D1-1EEF228D2AF3}"
TOUCHED = (EFX, COMPOSITE_EFX, EFX_MODES)

Values = dict[str, tuple[str, object]]


def _same(a: str, b: str) -> bool:
    return a.strip().lower() == b.strip().lower()


def _as_list(entry) -> list[str]:
    if entry is None:
        return []
    kind, data = entry
    return [str(x) for x in data] if kind == "MultiString" else [str(data)]


def has_plugin(values: Values) -> bool:
    return any(_same(x, CLSID) for name in (EFX, COMPOSITE_EFX) for x in _as_list(values.get(name)))


def backup_of(values: Values) -> Values:
    """The values we'll change, to put back on uninstall."""
    return {name: values[name] for name in TOUCHED if name in values}


def attached(values: Values) -> Values:
    """The mic's values with the plugin added, keeping whatever effect it already had."""
    out = dict(values)
    if COMPOSITE_EFX in values:
        # The driver uses a composite chain: run first, then its own effects.
        chain = [x for x in _as_list(values[COMPOSITE_EFX]) if not _same(x, CLSID)]
        out[COMPOSITE_EFX] = ("MultiString", [CLSID, *chain])
    elif EFX in values and not _same(str(values[EFX][1]), CLSID):
        # One vendor effect: keep it by making the slot a chain of two.
        out[COMPOSITE_EFX] = ("MultiString", [CLSID, str(values[EFX][1])])
    else:
        out[EFX] = ("String", CLSID)
    modes = _as_list(values.get(EFX_MODES))
    if not any(_same(m, DEFAULT_MODE) for m in modes):
        out[EFX_MODES] = ("MultiString", [DEFAULT_MODE, *modes])
    return out


def restored(values: Values, backup: Values | None) -> Values:
    """The mic's values with the plugin taken out: the backup if there is one, otherwise just
    our CLSID removed from wherever it is."""
    out = dict(values)
    if backup is not None:
        for name in TOUCHED:
            if name in backup:
                out[name] = backup[name]
            else:
                out.pop(name, None)
        return out
    if EFX in out and _same(str(out[EFX][1]), CLSID):
        del out[EFX]
    if COMPOSITE_EFX in out:
        rest = [x for x in _as_list(out[COMPOSITE_EFX]) if not _same(x, CLSID)]
        if rest:
            out[COMPOSITE_EFX] = ("MultiString", rest)
        else:
            del out[COMPOSITE_EFX]
    return out
