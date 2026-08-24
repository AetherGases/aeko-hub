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
        aeko_inventory_analyzer_factory,
        build_gas_reduction_context,
    ) -> str:
        """Run a GHG inventory through the AI and persist the plan it returns.

        Args:
            s3: Where the inventory file lives.
            id_user: Internal identifier of whoever submitted it.
            id_external_inventory_4context: Previous inventory to use as
                context. `None` for a company's first report.
            user_service: Records the resulting plan as a user memory.
            improvement_plan_service: Persists the plan itself.
            aeko_inventory_analyzer_factory: Builds an analyzer for this run.
            build_gas_reduction_context: Renders the previous report as the
                plain text `set_context()` expects.

        Returns:
            The improvement plan, as text.
        """


class IRepository(ABC):
    @abstractmethod
    def get_excel_bytes(self, s3: str) -> bytes:
        """Download the raw inventory workbook.

        Raises:
            RuntimeError: the object could not be fetched.
        """

    @abstractmethod
    def get_external_inventory_context(self, id_external_inventory_4context: int) -> dict[str, Any]:
        """Fetch a previous inventory's figures from the external API.

        Raises:
            RuntimeError: the request failed.
        """
