"""On-demand cloud model discovery (pull-based, powers review dropdowns)."""
from app.discovery.base import DiscoveredModel, DiscoveryDriver, get_driver, list_supported_clouds

__all__ = ["DiscoveredModel", "DiscoveryDriver", "get_driver", "list_supported_clouds"]
