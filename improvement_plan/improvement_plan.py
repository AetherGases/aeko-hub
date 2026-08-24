from abc import ABC, abstractmethod

from improvement_plan.entity import ImprovementPlan

class IRepository(ABC):
    @abstractmethod
    def get_by_id_external_inventory(self, id_external_inventory) -> ImprovementPlan:
        """Fetch the plan derived from one external GHG inventory.

        Raises:
            ValueError: no plan was derived from that inventory.
        """
        
    @abstractmethod
    def create(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        """Store a plan and return it carrying its assigned identifier."""

class IService(ABC):
    @abstractmethod
    def get_by_id_external_inventory(self, id_external_inventory) -> ImprovementPlan:
        """Retrieve the plan derived from one external GHG inventory."""

    @abstractmethod
    def create(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        """Persist a plan and return it carrying its assigned identifier."""