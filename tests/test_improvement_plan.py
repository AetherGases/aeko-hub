"""Unit tests for the improvement plan module (entity, queries, repository, service)."""

from datetime import datetime

import pytest

from improvement_plan.database import query as q
from improvement_plan.database.repository import Repository, improvement_plan_from_data
from improvement_plan.entity import ImprovementPlan
from improvement_plan.improvement_plan import IRepository, IService
from improvement_plan.service import Service
from tests.mongo_doubles import StubCollection, StubDatabase

UPDATED_AT = datetime(2026, 7, 26, 14, 30, 0)

PLAN_DOCUMENT = {
    "_id": "65a8b3d6c0f8e1d7f4b2c020",
    "id_external_inventory": 1,
    "defined_problem": "high scope 1 emissions",
    "method": "PDCA",
    "reasoning": "boiler replacement cuts direct emissions",
    "updated_at": UPDATED_AT,
}


class StubPlanRepository:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def get_by_id_external_inventory(self, id_external_inventory):
        self.calls.append(("get", id_external_inventory))
        return self.result

    def create(self, improvement_plan):
        self.calls.append(("create", improvement_plan))
        return self.result


def build_repository(collection=None):
    collection = collection or StubCollection()
    return Repository(StubDatabase(improvement_plan=collection)), collection


# ---------------------------------------------------------------------------
# Entity
# ---------------------------------------------------------------------------
def test_entity_defaults_to_an_empty_plan():
    plan = ImprovementPlan()

    assert (plan.id, plan.id_external_inventory, plan.updated_at) == (None, None, None)
    assert (plan.defined_problem, plan.method, plan.reasoning) == ("", "", "")


def test_entity_renders_every_field_as_text():
    plan = ImprovementPlan(id="p1", id_external_inventory=1, defined_problem="problem", method="PDCA", reasoning="why")

    rendered = str(plan)

    assert rendered.startswith("ImprovementPlan(")
    assert "id_external_inventory=1" in rendered
    assert "'problem'" in rendered


# ---------------------------------------------------------------------------
# Interface compatibility
# ---------------------------------------------------------------------------
def test_repository_and_service_implement_their_interfaces():
    assert issubclass(Repository, IRepository)
    assert issubclass(Service, IService)
    assert Repository.__abstractmethods__ == frozenset()
    assert Service.__abstractmethods__ == frozenset()


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------
def test_get_by_id_external_inventory_returns_the_plan():
    repository, _ = build_repository(StubCollection(find_one_result=PLAN_DOCUMENT))

    plan = repository.get_by_id_external_inventory(1)

    assert isinstance(plan, ImprovementPlan)
    assert plan.id == "65a8b3d6c0f8e1d7f4b2c020"
    assert plan.method == "PDCA"
    assert plan.updated_at == UPDATED_AT


def test_get_by_id_external_inventory_queries_by_the_external_inventory():
    repository, collection = build_repository(StubCollection(find_one_result=PLAN_DOCUMENT))

    repository.get_by_id_external_inventory(1)

    assert collection.call_args("find_one")[0][0] == {"id_external_inventory": 1}


def test_get_by_id_external_inventory_raises_value_error_when_not_found():
    repository, _ = build_repository(StubCollection(find_one_result=None))

    with pytest.raises(ValueError, match="not found"):
        repository.get_by_id_external_inventory(1)


def test_get_by_id_external_inventory_wraps_database_failures():
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.get_by_id_external_inventory(1)


def test_create_stores_the_plan_and_returns_it_with_an_identifier():
    repository, collection = build_repository(StubCollection(inserted_id="65a8b3d6c0f8e1d7f4b2c020"))
    plan = ImprovementPlan(id_external_inventory=1, defined_problem="problem", method="PDCA", reasoning="why")

    created = repository.create(plan)

    assert created is plan
    assert created.id == "65a8b3d6c0f8e1d7f4b2c020"
    assert collection.call_args("insert_one")[0][0]["method"] == "PDCA"


def test_create_wraps_database_failures():
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.create(ImprovementPlan())


def test_improvement_plan_from_data_handles_a_document_without_an_identifier():
    plan = improvement_plan_from_data({"id_external_inventory": 2})

    assert plan.id is None
    assert plan.defined_problem == ""


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------
def test_get_by_id_external_inventory_query():
    assert q.get_by_id_external_inventory_query(7) == ({"id_external_inventory": 7}, {})


def test_create_improvement_plan_query_maps_every_field():
    plan = ImprovementPlan(
        id="p1", id_external_inventory=1, defined_problem="problem", method="PDCA", reasoning="why", updated_at=UPDATED_AT
    )

    document = q.create_improvement_plan_query(plan)

    assert document == {
        "id_external_inventory": 1,
        "defined_problem": "problem",
        "method": "PDCA",
        "reasoning": "why",
        "updated_at": UPDATED_AT,
    }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
def test_service_get_delegates_to_the_repository():
    plan = ImprovementPlan(id="p1")
    repository = StubPlanRepository(result=plan)

    assert Service(repository).get_by_id_external_inventory(1) is plan
    assert repository.calls == [("get", 1)]


def test_service_create_delegates_to_the_repository():
    plan = ImprovementPlan(id="p1")
    repository = StubPlanRepository(result=plan)

    assert Service(repository).create(plan) is plan
    assert repository.calls == [("create", plan)]
