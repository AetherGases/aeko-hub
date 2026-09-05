"""Read a GHG inventory from the `ms-inventory` microservice.

The inventory file is not this application's to hold. It used to be pulled out
of S3 here and converted from `.xlsx` to Markdown before the SDK could read it;
both steps belong to the microservice that owns the file, which answers with
the inventory already rendered:

    GET {MS_INVENTORY_BASE_URL}/aether-api/v1/ms-inventory/resolve/{id}
    -> {"content": "## Escopo 1 ..."}

The transport is plain HTTPS with `requests`, like `cmd/api/integrations/`
next door and unlike `database/`, which is why this repository lives in its own
package: one repository per transport, not one per domain.
"""

import os

import requests

from improvement_plan.improvement_plan import IInventoryRepository
from shared import Module, logged

MS_INVENTORY_BASE_URL_ENV_VAR = "MS_INVENTORY_BASE_URL"

# Versioned by the microservice itself, in the path.
MS_INVENTORY_RESOLVE_PATH = "/aether-api/v1/ms-inventory/resolve"

# A report waits on this call, and a request with no timeout waits forever by
# default in `requests` — the caller would watch the report hang.
MS_INVENTORY_REQUEST_TIMEOUT = 30.0


class Repository(IInventoryRepository):
    @logged(Module.INTEGRATION, "ms_inventory.get_inventory_markdown")
    def get_inventory_markdown(self, id_external_inventory: int) -> str:
        url = f"{_base_url()}{MS_INVENTORY_RESOLVE_PATH}/{id_external_inventory}"

        try:
            response = requests.get(url, timeout=MS_INVENTORY_REQUEST_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except Exception as e:
            raise RuntimeError(f"Error fetching inventory {id_external_inventory} from ms-inventory: {e}")

        content = payload.get("content") if isinstance(payload, dict) else None
        if not content:
            # Nothing to analyze, which is the caller's problem to hear about:
            # this is the 400 the unreadable spreadsheet used to raise.
            raise ValueError(
                f"ms-inventory answered inventory {id_external_inventory} without content."
            )

        return content


def _base_url() -> str:
    base_url = os.getenv(MS_INVENTORY_BASE_URL_ENV_VAR)
    if not base_url:
        raise RuntimeError(
            f"{MS_INVENTORY_BASE_URL_ENV_VAR} is not set: there is nowhere to resolve the inventory."
        )
    return base_url.rstrip("/")
