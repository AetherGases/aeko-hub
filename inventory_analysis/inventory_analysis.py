from abc import ABC, abstractmethod
from inventory_analysis.entity import InventoryAnalysis

class IRepository(ABC):
    @abstractmethod
    def get_by_id_external_inventory(self, id_external_inventoru: int) -> InventoryAnalysis:
        pass

    @abstractmethod
    def create(self, inventory_analysis: InventoryAnalysis) -> InventoryAnalysis:
        pass

class IService(ABC):
    @abstractmethod
    def get_by_id_external_inventory(self, id_external_inventory: int) -> InventoryAnalysis:
        pass

    @abstractmethod
    def input_inventory(self, id_external_inventory: int) -> InventoryAnalysis:
        pass