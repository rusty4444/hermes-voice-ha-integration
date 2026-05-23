"""Constants for the Hermes Home Assistant integration."""

DOMAIN = "hermes"

# Config flow keys
CONF_ENTITY_FILTER = "entity_filter"
CONF_VERIFY_SSL = "verify_ssl"

# Default entity filter — subscribe to all state changes
DEFAULT_ENTITY_FILTER: list[str] = []
DEFAULT_VERIFY_SSL: bool = True
