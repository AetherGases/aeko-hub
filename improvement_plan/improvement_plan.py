"""The improvement plan: the document this API stores, and the flow that
produces it.

The report flow used to be a package of its own (`inventory_analysis`), which
split one story in two: an analysis exists to produce a plan, and the plan is
the only thing it leaves behind. Both live here now — the SDK access included —
so the collection and what writes to it are read together.

Two repositories, because there are two transports: `database/` speaks Mongo
and holds the plans, while `integration/` speaks HTTP and reads the inventory
itself, which belongs to the `ms-inventory` microservice.
"""

from abc import ABC, abstractmethod

from improvement_plan.entity import ImprovementPlan
from user.user import IService as IUserService

# How many of a unit's previous plans travel into the analysis as context.
# Two, because a plan is judged against what was already tried: the last one
# and the one before it, in that order.
PREVIOUS_PLANS_FOR_CONTEXT = 2


class MalformedPlanError(Exception):
    """Raised when the analysis came back without a plan to store.

    The report flow passes neither reviewer of the chat flow, but the
    `Coordenador de Melhoria Continua` still has to write the plan under its
    three headings, and four rewrites is as far as the SDK goes. It arrives as
    `MalformedAgentOutputError` and is translated by `cmd/api/main.py`, the one
    file that may know that name.

    The sibling of `session.session.GuardrailRejectedError`: a run that was
    made and paid for, leaving nothing this API can persist.
    """

class IRepository(ABC):
    @abstractmethod
    def get_by_id_external_inventory(self, id_external_inventory) -> ImprovementPlan:
        pass

    @abstractmethod
    def get_last_by_id_external_unit(self, id_external_unit, limit) -> list[ImprovementPlan]:
        pass

    @abstractmethod
    def create(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        pass

class IInventoryRepository(ABC):
    """The inventory the analysis reads, owned by another microservice.

    It answers with the spreadsheet already rendered as Markdown, which is the
    shape `AekoInventoryAnalyzer.analyze()` takes — no file, no bucket and no
    spreadsheet library on this side of the call.
    """

    @abstractmethod
    def get_inventory_markdown(self, id_external_inventory: int) -> str:
        pass

class IService(ABC):
    @abstractmethod
    def get_by_id_external_inventory(self, id_external_inventory) -> ImprovementPlan:
        pass

    @abstractmethod
    def get_last_by_id_external_unit(self, id_external_unit, limit) -> list[ImprovementPlan]:
        pass

    @abstractmethod
    def create(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
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
        pass
