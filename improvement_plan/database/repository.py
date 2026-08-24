from improvement_plan.database import query as q
from improvement_plan.entity import ImprovementPlan
from improvement_plan.improvement_plan import IRepository


class Repository(IRepository):
	def __init__(self, db):
		"""Hold the Mongo database handle every query below runs against."""
		self.db = db

	def get_by_id_external_inventory(self, id_external_inventory) -> ImprovementPlan:
		"""Fetch the plan derived from one external GHG inventory.

		Raises:
			ValueError: no plan was derived from that inventory.
			RuntimeError: the lookup itself failed.
		"""
		try:
			query, projection = q.get_by_id_external_inventory_query(id_external_inventory)
			improvement_plan_data = self.db["improvement_plan"].find_one(query, projection)
			if not improvement_plan_data:
				raise ValueError(f"Improvement plan with id_external_inventory {id_external_inventory} not found.")
			return improvement_plan_from_data(improvement_plan_data)
		except ValueError as e:
			raise e
		except Exception as e:
			raise RuntimeError(f"Error fetching improvement plan from database: {e}")

	def create(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
		"""Store a plan, stamping the identifier Mongo assigned onto it.

		Raises:
			RuntimeError: the write failed.
		"""
		try:
			improvement_plan_data = q.create_improvement_plan_query(improvement_plan)
			result = self.db["improvement_plan"].insert_one(improvement_plan_data)
			improvement_plan.id = str(result.inserted_id)
			return improvement_plan
		except Exception as e:
			raise RuntimeError(f"Error creating improvement plan in database: {e}")


def improvement_plan_from_data(data: dict) -> ImprovementPlan:
	"""Build an `ImprovementPlan` from its stored document."""
	return ImprovementPlan(
		id=str(data.get("_id")) if data.get("_id") is not None else None,
		id_external_inventory=data.get("id_external_inventory"),
		defined_problem=data.get("defined_problem", ""),
		method=data.get("method", ""),
		reasoning=data.get("reasoning", ""),
		updated_at=data.get("updated_at"),
	)
