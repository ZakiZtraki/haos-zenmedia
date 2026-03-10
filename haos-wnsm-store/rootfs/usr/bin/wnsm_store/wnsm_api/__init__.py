"""Unofficial Python wrapper for the Wiener Netze Smart Meter private API.

Copied from the WNSM custom integration with the homeassistant dependency
removed so it can run standalone inside the addon.
"""
from .client import Smartmeter

__all__ = ["Smartmeter"]
