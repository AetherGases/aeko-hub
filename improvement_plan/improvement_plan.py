"""Define improvement-plan service and repository contracts.

Plans are stored in MongoDB; inventory content is retrieved through a separate
HTTP repository as Markdown for analysis.
"""

from abc import ABC, abstractmethod

from improvement_plan.entity import ImprovementPlan
from user.user import IService as IUserService


from improvement_plan.constants import (
    PREVIOUS_PLANS_FOR_CONTEXT,
)


class MalformedPlanError(Exception):
    """Raised when analysis produces no persistable improvement plan."""

class IRepository(ABC):
    @abstractmethod
    def get_by_id_external_inventory(self, id_external_inventory) -> ImprovementPlan:
        """Retrieve the improvement plan associated with an external inventory identifier."""
        pass

    @abstractmethod
    def get_last_by_id_external_unit(self, id_external_unit, limit) -> list[ImprovementPlan]:
        """Retrieve the latest plans for an external unit, up to the requested limit."""
        pass

    @abstractmethod
    def create(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        """Persist an improvement plan and return the stored entity."""
        pass

class IInventoryRepository(ABC):
    """Contract for retrieving inventory content as Markdown."""

    @abstractmethod
    def get_inventory_markdown(self, id_external_inventory: int) -> str:
        """Retrieve the inventory content as Markdown from the inventory service."""
        pass

class IService(ABC):
    @abstractmethod
    def get_by_id_external_inventory(self, id_external_inventory) -> ImprovementPlan:
        """Retrieve the improvement plan associated with an external inventory identifier."""
        pass

    @abstractmethod
    def get_last_by_id_external_unit(self, id_external_unit, limit) -> list[ImprovementPlan]:
        """Retrieve the latest plans for an external unit, up to the requested limit."""
        pass

    @abstractmethod
    def create(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        """Persist an improvement plan and return the stored entity."""
        pass

    @abstractmethod
    def input_inventory(
        self,
        id_external_inventory: int | None,
        id_external_unit: int | None,
        id_user: str,
        user_service: IUserService,
        aeko_inventory_analyzer_factory,
    ) -> ImprovementPlan:
        """Analyze an inventory with previous plans as context, then store its plan and user memory."""
        pass
