"""Host adapters: stock Moonraker, Paxx Moonraker, OctoPrint. Importing registers them."""
from .. import registry
from .moonraker_paxx import INSTANCE as _PAXX
from .moonraker_stock import INSTANCE as _STOCK
from .octoprint import INSTANCE as _OCTOPRINT

for _adapter in (_STOCK, _PAXX, _OCTOPRINT):
    registry.register(_adapter)

__all__ = ["classify", "moonraker_base", "moonraker_parse", "moonraker_paxx", "moonraker_stock",
           "octoprint", "reader"]
