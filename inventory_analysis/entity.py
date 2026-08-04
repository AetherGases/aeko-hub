from datetime import datetime

class InventoryAnalysis:
    id: str
    id_external_inventory: int
    gas: str
    emitted_tons: float
    observations: list
    created_at: datetime

    def __init__(self, id: str, id_external_inventory: int, gas: str, emitted_tons: float, observations: list, created_at: datetime):
        self.id = id
        self.id_external_inventory = id_external_inventory
        self.gas = gas
        self.emitted_tons = emitted_tons
        self.observations = observations
        self.created_at = created_at