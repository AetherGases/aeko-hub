from abc import ABC, abstractmethod
from improvement_plan.entity import ImprovementPlan
from user.user import IService as IUserService

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
    def input_report(
        self,
        s3: str,
        id_user: str,
        id_inventory: int | None,
        user_service: IUserService,
        id_department: int | None,
        id_external_user_owner: int | None,
        id_external_user_validator: int | None,
        id_external_input_report: int | None,
    ) -> str:
        pass