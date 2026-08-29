"""Adapter-Registry."""
from __future__ import annotations

from .base import DeviceAdapter
from .shelly_gen2 import ShellyGen2Adapter
from .smlight import SmlightAdapter

ADAPTERS: list[type[DeviceAdapter]] = [ShellyGen2Adapter, SmlightAdapter]
