"""Unit tests for the improvement plan module.

Entity, queries, repository and service — including the report flow, which
used to live in `inventory_analysis` and now belongs here: the plan is what an
analysis produces, and grouping the two put the SDK access beside the
collection it writes to.

The inventory itself is read from the `ms-inventory` microservice through a
second repository, injected like the Mongo one and covered in
`tests/test_ms_inventory.py`. Every collaborator below is a local double: the
two repositories, the analyzer factory the lifespan publishes, and the user
service the plan is remembered through.
"""

import importlib.util
import inspect
from datetime import datetime

import pytest

from improvement_plan.database import query as q
from improvement_plan.database.repository import Repository, improvement_plan_from_data
from improvement_plan.entity import ImprovementPlan
from improvement_plan.improvement_plan import (
    IInventoryRepository,
    IRepository,
    IService,
    PREVIOUS_PLANS_FOR_CONTEXT,
)
from improvement_plan.service import Service
from shared.event_tracking import (
    bind_id_request,
    set_aeko_metrics_sink,
    unbind_id_request,
)
from tests.mongo_doubles import StubCollection, StubDatabase
from user.entity import UserMemory

UPDATED_AT = datetime(2026, 7, 26, 14, 30, 0)

ID_USER = "u1"
ID_INVENTORY = 502
ID_UNIT = 77

INVENTORY_MARKDOWN = "## Escopo 1\n\n| Fonte | tCO2e |\n| --- | --- |\n| Caldeira | 12400 |"

PLAN_DOCUMENT = {
    "_id": "65a8b3d6c0f8e1d7f4b2c020",
    "id_external_inventory": 1,
    "id_external_unit": ID_UNIT,
    "defined_problem": "high scope 1 emissions",
    "method": "PDCA",
    "reasoning": "boiler replacement cuts direct emissions",
    "updated_at": UPDATED_AT,
}


def previous_plan(id_external_inventory, defined_problem, method, reasoning, updated_at=UPDATED_AT):
    return ImprovementPlan(
        id=f"plan-{id_external_inventory}",
        id_external_inventory=id_external_inventory,
        id_external_unit=ID_UNIT,
        defined_problem=defined_problem,
        method=method,
        reasoning=reasoning,
        updated_at=updated_at,
    )


class StubPlanRepository:
    def __init__(self, result=None, previous=None):
        self.result = result
        self.previous = list(previous or [])
        self.calls = []

    def get_by_id_external_inventory(self, id_external_inventory):
        self.calls.append(("get", id_external_inventory))
        return self.result

    def get_last_by_id_external_unit(self, id_external_unit, limit):
        self.calls.append(("get_last", id_external_unit, limit))
        return self.previous[:limit]

    def create(self, improvement_plan):
        self.calls.append(("create", improvement_plan))
        if self.result is not None:
            return self.result
        improvement_plan.id = "created-plan"
        return improvement_plan


class StubInventoryRepository:
    def __init__(self, markdown=INVENTORY_MARKDOWN, error=None):
        self.markdown = markdown
        self.error = error
        self.calls = []

    def get_inventory_markdown(self, id_external_inventory):
        self.calls.append(id_external_inventory)
        if self.error is not None:
            raise self.error
        return self.markdown


class StubPlan:
    """Stands in for the `AekoImprovementPlan` the SDK returns."""

    def __init__(self, id_external_inventory=ID_INVENTORY):
        self.id = None
        self.id_external_inventory = id_external_inventory
        self.defined_problem = "high scope 1 emissions"
        self.method = "replace the boiler fleet"
        self.reasoning = "direct combustion dominates the inventory"


class StubMetrics:
    """Stands in for the `AekoMetrics` the SDK reports an analysis with."""

    def __init__(self, id_request="", error_description=None):
        self.id_request = id_request
        self.latency = 12
        self.error_description = error_description
        self.flow = "analytical"
        self.used_agents = []


class StubAnalysis:
    """Stands in for the `AekoAnalysisResponse` 3.x hands back."""

    def __init__(self, plan, aeko_metrics):
        self.plan = plan
        self.aeko_metrics = aeko_metrics


class StubAnalyzer:
    def __init__(self, plan=None, error=None):
        self.plan = plan or StubPlan()
        self.error = error
        # Deliberately `None` rather than "": a context that was never set and
        # a context set to nothing are different outcomes, and the flow now
        # demands the second one even for a unit with no history.
        self.context = None
        self.analyzed = []

    def set_context(self, context):
        self.context = context

    def analyze(self, inventory, *, id_external_inventory, id_request):
        self.analyzed.append((inventory, id_external_inventory, id_request))
        if self.error is not None:
            raise self.error
        return StubAnalysis(self.plan, StubMetrics(id_request=id_request))


class StubAnalyzerFactory:
    def __init__(self, plan=None, error=None):
        self.plan = plan
        self.error = error
        self.built = []

    def __call__(self):
        analyzer = StubAnalyzer(self.plan, self.error)
        self.built.append(analyzer)
        return analyzer

    @property
    def last(self):
        return self.built[-1]


class StubUserService:
    def __init__(self):
        self.memories = []

    def get_mongo_user(self, id_external_user):
        raise NotImplementedError

    def get_user_memories(self, id_user):
        return self.memories

    def create_user_memory(self, user_memory):
        self.memories.append(user_memory)


def build_repository(collection=None):
    collection = collection or StubCollection()
    return Repository(StubDatabase(improvement_plan=collection)), collection


def build_service(repository=None, inventories=None):
    return Service(repository or StubPlanRepository(), inventories or StubInventoryRepository())


def run(repository=None, inventories=None, analyzers=None, users=None,
        id_external_inventory=ID_INVENTORY, id_external_unit=ID_UNIT):
    service = build_service(repository, inventories)
    return service.input_inventory(
        id_external_inventory,
        id_external_unit,
        ID_USER,
        users or StubUserService(),
        analyzers or StubAnalyzerFactory(),
    )


# ---------------------------------------------------------------------------
# Entity
# ---------------------------------------------------------------------------
def test_entity_defaults_to_an_empty_plan():
    plan = ImprovementPlan()

    assert (plan.id, plan.id_external_inventory, plan.updated_at) == (None, None, None)
    assert plan.id_external_unit is None
    assert (plan.defined_problem, plan.method, plan.reasoning) == ("", "", "")


def test_entity_renders_every_field_as_text():
    plan = ImprovementPlan(
        id="p1",
        id_external_inventory=1,
        id_external_unit=ID_UNIT,
        defined_problem="problem",
        method="PDCA",
        reasoning="why",
    )

    rendered = str(plan)

    assert rendered.startswith("ImprovementPlan(")
    assert "id_external_inventory=1" in rendered
    assert f"id_external_unit={ID_UNIT}" in rendered
    assert "'problem'" in rendered


# ---------------------------------------------------------------------------
# Interface compatibility
# ---------------------------------------------------------------------------
def test_repository_and_service_implement_their_interfaces():
    assert issubclass(Repository, IRepository)
    assert issubclass(Service, IService)
    assert Repository.__abstractmethods__ == frozenset()
    assert Service.__abstractmethods__ == frozenset()


def test_input_inventory_signature_matches_the_interface():
    interface = inspect.signature(IService.input_inventory).parameters
    implementation = inspect.signature(Service.input_inventory).parameters

    assert list(interface) == list(implementation)
    assert "aeko_inventory_analyzer_factory" in interface
    # The S3 reference is gone: the inventory arrives as Markdown from the
    # ms-inventory microservice, keyed by the same external id the plan is
    # filed against.
    assert "s3" not in interface
    assert "id_external_inventory" in interface
    assert "id_external_unit" in interface


def test_the_flow_no_longer_lives_in_its_own_package():
    """`inventory_analysis` was grouped into this module — S3 and the
    spreadsheet conversion went with it."""
    assert importlib.util.find_spec("inventory_analysis") is None


def test_the_inventory_repository_is_an_interface_of_its_own():
    """Two transports, two repositories: `database/` speaks Mongo and
    `integration/` speaks HTTP."""
    assert "get_inventory_markdown" in IInventoryRepository.__abstractmethods__


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------
def test_get_by_id_external_inventory_returns_the_plan():
    repository, _ = build_repository(StubCollection(find_one_result=PLAN_DOCUMENT))

    plan = repository.get_by_id_external_inventory(1)

    assert isinstance(plan, ImprovementPlan)
    assert plan.id == "65a8b3d6c0f8e1d7f4b2c020"
    assert plan.method == "PDCA"
    assert plan.id_external_unit == ID_UNIT
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


def test_get_last_by_id_external_unit_returns_the_plans_the_database_answered():
    repository, _ = build_repository(StubCollection(find_result=[PLAN_DOCUMENT, PLAN_DOCUMENT]))

    plans = repository.get_last_by_id_external_unit(ID_UNIT, 2)

    assert [type(plan) for plan in plans] == [ImprovementPlan, ImprovementPlan]
    assert plans[0].id_external_unit == ID_UNIT


def test_get_last_by_id_external_unit_asks_for_the_newest_plans_of_that_unit():
    repository, collection = build_repository(StubCollection(find_result=[PLAN_DOCUMENT]))

    repository.get_last_by_id_external_unit(ID_UNIT, 2)

    assert collection.call_args("find")[0][0] == {"id_external_unit": ID_UNIT}
    assert collection.find_options[0] == {"sort": [("updated_at", -1)], "limit": 2}


def test_get_last_by_id_external_unit_returns_nothing_for_a_units_first_report():
    """A unit with no history is not an error — it is every unit's first run."""
    repository, _ = build_repository(StubCollection(find_result=[]))

    assert repository.get_last_by_id_external_unit(ID_UNIT, 2) == []


def test_get_last_by_id_external_unit_wraps_database_failures():
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.get_last_by_id_external_unit(ID_UNIT, 2)


def test_create_stores_the_plan_and_returns_it_with_an_identifier():
    repository, collection = build_repository(StubCollection(inserted_id="65a8b3d6c0f8e1d7f4b2c020"))
    plan = ImprovementPlan(
        id_external_inventory=1,
        id_external_unit=ID_UNIT,
        defined_problem="problem",
        method="PDCA",
        reasoning="why",
    )

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
    assert plan.id_external_unit is None
    assert plan.defined_problem == ""


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------
def test_get_by_id_external_inventory_query():
    assert q.get_by_id_external_inventory_query(7) == ({"id_external_inventory": 7}, {})


def test_get_last_by_id_external_unit_query_reads_the_newest_plans_of_the_unit():
    query, projection, sort, limit = q.get_last_by_id_external_unit_query(ID_UNIT, 2)

    assert query == {"id_external_unit": ID_UNIT}
    assert projection == {}
    assert sort == [("updated_at", -1)]
    assert limit == 2


def test_create_improvement_plan_query_maps_every_field():
    plan = ImprovementPlan(
        id="p1",
        id_external_inventory=1,
        id_external_unit=ID_UNIT,
        defined_problem="problem",
        method="PDCA",
        reasoning="why",
        updated_at=UPDATED_AT,
    )

    document = q.create_improvement_plan_query(plan)

    assert document == {
        "id_external_inventory": 1,
        "id_external_unit": ID_UNIT,
        "defined_problem": "problem",
        "method": "PDCA",
        "reasoning": "why",
        "updated_at": UPDATED_AT,
    }


def test_create_improvement_plan_query_stamps_a_missing_update_timestamp():
    """Every document in the collection carries `updated_at`; a plan built
    from the Aeko DTO has none, so the query has to stamp it."""
    document = q.create_improvement_plan_query(ImprovementPlan(id_external_inventory=1))

    assert isinstance(document["updated_at"], datetime)


def test_create_improvement_plan_query_keeps_the_external_identifiers_numbers():
    """`id_external_inventory` and `id_external_unit` reference Postgres,
    never a Mongo `_id`."""
    document = q.create_improvement_plan_query(
        ImprovementPlan(id_external_inventory=7, id_external_unit=ID_UNIT)
    )

    assert isinstance(document["id_external_inventory"], int)
    assert isinstance(document["id_external_unit"], int)


# ---------------------------------------------------------------------------
# Service — delegation
# ---------------------------------------------------------------------------
def test_service_get_delegates_to_the_repository():
    plan = ImprovementPlan(id="p1")
    repository = StubPlanRepository(result=plan)

    assert build_service(repository).get_by_id_external_inventory(1) is plan
    assert repository.calls == [("get", 1)]


def test_service_get_last_by_id_external_unit_delegates_to_the_repository():
    plans = [previous_plan(1, "problem", "PDCA", "why")]
    repository = StubPlanRepository(previous=plans)

    assert build_service(repository).get_last_by_id_external_unit(ID_UNIT, 2) == plans
    assert repository.calls == [("get_last", ID_UNIT, 2)]


def test_service_create_delegates_to_the_repository():
    plan = ImprovementPlan(id="p1")
    repository = StubPlanRepository(result=plan)

    assert build_service(repository).create(plan) is plan
    assert repository.calls == [("create", plan)]


# ---------------------------------------------------------------------------
# Service — what the analyzer is handed
# ---------------------------------------------------------------------------
def test_the_inventory_is_read_from_the_microservice_by_its_external_id():
    inventories = StubInventoryRepository()

    run(inventories=inventories)

    assert inventories.calls == [ID_INVENTORY]


def test_analyze_receives_the_inventory_as_markdown():
    analyzers = StubAnalyzerFactory()

    run(analyzers=analyzers)

    inventory, _, _ = analyzers.last.analyzed[0]
    assert inventory == INVENTORY_MARKDOWN


def test_analyze_receives_the_inventory_identifier():
    analyzers = StubAnalyzerFactory()

    run(analyzers=analyzers)

    _, id_external_inventory, _ = analyzers.last.analyzed[0]
    assert id_external_inventory == ID_INVENTORY


def test_every_report_gets_a_fresh_analyzer():
    """`set_context()` is instance state: a shared analyzer would leak it."""
    analyzers = StubAnalyzerFactory()

    run(analyzers=analyzers)
    run(analyzers=analyzers)

    assert len(analyzers.built) == 2


def test_the_units_previous_plans_are_asked_for_two_at_a_time():
    repository = StubPlanRepository()

    run(repository=repository)

    assert ("get_last", ID_UNIT, PREVIOUS_PLANS_FOR_CONTEXT) in repository.calls
    assert PREVIOUS_PLANS_FOR_CONTEXT == 2


def test_the_context_carries_the_content_of_the_last_two_plans():
    analyzers = StubAnalyzerFactory()
    repository = StubPlanRepository(
        previous=[
            previous_plan(9, "boiler still burning", "swap for heat pumps", "scope 1 dominates"),
            previous_plan(8, "diesel fleet", "electrify the fleet", "scope 1 second largest"),
        ]
    )

    run(repository=repository, analyzers=analyzers)

    context = analyzers.last.context
    assert isinstance(context, str)
    for text in (
        "boiler still burning",
        "swap for heat pumps",
        "scope 1 dominates",
        "diesel fleet",
        "electrify the fleet",
        "scope 1 second largest",
    ):
        assert text in context
    # Most recent first: it is the report this one builds on.
    assert context.index("boiler still burning") < context.index("diesel fleet")


def test_the_context_is_set_even_when_the_unit_has_no_previous_plan():
    """`set_context()` is always called: a first report sets an empty context
    rather than leaving the analyzer's own state untouched."""
    analyzers = StubAnalyzerFactory()

    run(repository=StubPlanRepository(previous=[]), analyzers=analyzers)

    assert analyzers.last.context == ""


def test_an_inventory_without_an_identifier_is_rejected():
    """The plan is filed against the inventory, so the id cannot be missing."""
    with pytest.raises(ValueError, match="id_external_inventory"):
        run(id_external_inventory=None)


def test_a_report_without_a_unit_is_rejected():
    """The unit is what the previous plans are found by, and what this plan is
    stored under for the next report."""
    with pytest.raises(ValueError, match="id_external_unit"):
        run(id_external_unit=None)


# ---------------------------------------------------------------------------
# Service — what the API does with the plan
# ---------------------------------------------------------------------------
def test_the_plan_is_persisted_field_by_field():
    repository = StubPlanRepository()

    run(repository=repository)

    (plan,) = [call[1] for call in repository.calls if call[0] == "create"]
    assert isinstance(plan, ImprovementPlan)
    assert plan.id_external_inventory == ID_INVENTORY
    assert plan.id_external_unit == ID_UNIT
    assert plan.defined_problem == "high scope 1 emissions"
    assert plan.method == "replace the boiler fleet"
    assert plan.reasoning == "direct combustion dominates the inventory"


def test_the_plan_is_remembered_for_the_user():
    users = StubUserService()

    run(users=users)

    memory = users.memories[0]
    assert isinstance(memory, UserMemory)
    assert memory.id_user == ID_USER
    assert memory.field == "improvement_plan"
    assert "high scope 1 emissions" in memory.description


def test_the_created_plan_is_returned():
    plan = run()

    assert isinstance(plan, ImprovementPlan)
    assert plan.id == "created-plan"
    assert plan.defined_problem == "high scope 1 emissions"


def test_an_inventory_the_microservice_cannot_deliver_is_surfaced():
    inventories = StubInventoryRepository(error=RuntimeError("ms-inventory answered 503"))

    with pytest.raises(RuntimeError, match="ms-inventory answered 503"):
        run(inventories=inventories)


def test_a_failing_analyzer_is_surfaced():
    with pytest.raises(RuntimeError, match="coordinator never produced the plan"):
        run(analyzers=StubAnalyzerFactory(error=RuntimeError("coordinator never produced the plan")))


# ---------------------------------------------------------------------------
# Service — the analysis's own event tracking
# ---------------------------------------------------------------------------
@pytest.fixture
def recorded_metrics():
    """Everything the service hands to the `aeko_metrics` sink, in order."""
    metrics = []
    set_aeko_metrics_sink(metrics.append)
    yield metrics
    set_aeko_metrics_sink(None)


def test_the_analyzer_is_handed_the_identifier_the_request_is_tracked_under():
    analyzers = StubAnalyzerFactory()
    token = bind_id_request("65a8b3d6c0f8e1d7f4b2c0aa")

    try:
        run(analyzers=analyzers)
    finally:
        unbind_id_request(token)

    assert analyzers.last.analyzed[0][2] == "65a8b3d6c0f8e1d7f4b2c0aa"


def test_an_analysis_records_what_it_cost(recorded_metrics):
    token = bind_id_request("65a8b3d6c0f8e1d7f4b2c0aa")

    try:
        run()
    finally:
        unbind_id_request(token)

    assert [metrics.id_request for metrics in recorded_metrics] == ["65a8b3d6c0f8e1d7f4b2c0aa"]
    assert recorded_metrics[0].flow == "analytical"


def test_an_analysis_that_raised_records_the_tracking_it_carried_out(recorded_metrics):
    """`analyze()` raises when the coordinator never writes the plan's sections,
    and the run it did make is the one worth having recorded."""
    error = RuntimeError("coordinator never produced the plan")
    error.aeko_metrics = StubMetrics(error_description="MalformedAgentOutputError: no sections")

    with pytest.raises(RuntimeError):
        run(analyzers=StubAnalyzerFactory(error=error))

    assert [metrics.error_description for metrics in recorded_metrics] == [
        "MalformedAgentOutputError: no sections"
    ]


def test_a_failure_carrying_no_tracking_records_nothing(recorded_metrics):
    with pytest.raises(RuntimeError):
        run(analyzers=StubAnalyzerFactory(error=RuntimeError("gemini down")))

    assert recorded_metrics == []


def test_a_recording_that_fails_never_takes_the_analysis_down():
    def explode(metrics):
        raise RuntimeError("mongo is down")

    set_aeko_metrics_sink(explode)

    try:
        assert run().defined_problem == "high scope 1 emissions"
    finally:
        set_aeko_metrics_sink(None)
