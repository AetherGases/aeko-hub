from abc import ABC, abstractmethod
from typing import Any

from improvement_plan.improvement_plan import IService as IImprovementPlanService
from user.user import IService as IUserService

class IService(ABC):
    @abstractmethod
    def input_inventory(
        self,
        s3: str,
        id_user: str,
        id_external_inventory_4context: int | None,
        user_service: IUserService,
        improvement_plan_service: IImprovementPlanService,
    ) -> str:
        pass


class IRepository(ABC):
    @abstractmethod
    def get_excel_bytes(self, s3: str) -> bytes:
        pass

    @abstractmethod
    def get_external_inventory_context(self, id_external_inventory_4context: int) -> dict[str, Any]:
        pass