from abc import ABC, abstractmethod

from improvement_plan.entity import ImprovementPlan

class IRepository(ABC):
    @abstractmethod
    def get_by_id_external_inventory(self, id_external_inventory) -> ImprovementPlan:
        pass

    @abstractmethod
    def create(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        pass

class IService(ABC):
    @abstractmethod
    def get_by_id_external_inventory(self, id_external_inventory) -> ImprovementPlan:
        pass

    @abstractmethod
    def create(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        pass