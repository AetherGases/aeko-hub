"""Retrieve inventory Markdown from the ms-inventory HTTP API.

MS_INVENTORY_BASE_URL is the service origin. The resolve endpoint returns a
JSON object whose content field supplies the inventory to the analyzer.
"""

import os

import requests

from improvement_plan.improvement_plan import IInventoryRepository
from internal.shared import Module, logged


MS_INVENTORY_RESOLVE_PATH = "/aether-api/v1/ms-inventory/resolve"


MS_INVENTORY_REQUEST_TIMEOUT = 30.0


class Repository(IInventoryRepository):
    @logged(Module.INTEGRATION, "ms_inventory.get_inventory_markdown")
    def get_inventory_markdown(self, id_external_inventory: int) -> str:
        """Retrieve the inventory content as Markdown from the inventory service."""
        url = f"{_base_url()}{MS_INVENTORY_RESOLVE_PATH}/{id_external_inventory}"

        try:
            response = requests.get(url, timeout=MS_INVENTORY_REQUEST_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except Exception as e:
            raise RuntimeError(f"Error fetching inventory {id_external_inventory} from ms-inventory: {e}")

        content = payload.get("content") if isinstance(payload, dict) else None
        if not content:
            raise ValueError(
                f"ms-inventory answered inventory {id_external_inventory} without content."
            )

        return content


def _base_url() -> str:
    base_url = os.getenv('MS_INVENTORY_BASE_URL')
    if not base_url:
        raise RuntimeError(
            "MS_INVENTORY_BASE_URL is not set: there is nowhere to resolve the inventory."
        )
    return base_url.rstrip("/")
