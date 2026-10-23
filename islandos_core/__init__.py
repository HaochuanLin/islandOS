"""Independent, UI-agnostic building blocks for IslandOS."""

from .signals import SignalReading, SignalValidationError, validate_signal_payload

__all__ = ["SignalReading", "SignalValidationError", "validate_signal_payload"]

from .configuration import ConfigurationError, SiteConfiguration

__all__ += ["ConfigurationError", "SiteConfiguration"]
