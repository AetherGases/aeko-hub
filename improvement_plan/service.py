from improvement_plan.entity import ImprovementPlan
from improvement_plan.improvement_plan import IService

class Service(IService):
    def __init__(self, repository):
        """Hold the repository every call below delegates its storage to."""
        self.repository = repository

    def get_by_id_external_inventory(self, id_external_inventory) -> ImprovementPlan:
        """Retrieve the plan derived from one external GHG inventory.

        Raises:
            ValueError: no plan was derived from that inventory.
        """
        return self.repository.get_by_id_external_inventory(id_external_inventory)

    def create(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        """Persist a plan and return it carrying its assigned identifier."""
        return self.repository.create(improvement_plan)