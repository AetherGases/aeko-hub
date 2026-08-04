from improvement_plan.entity import ImprovementPlan
from improvement_plan.improvement_plan import IService

class Service(IService):
    def __init__(self, repository):
        self.repository = repository

    def get_by_id_external_inventory(self, id_external_inventory) -> ImprovementPlan:
        return self.repository.get_by_id_external_inventory(id_external_inventory)

    def create(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        return self.repository.create(improvement_plan)