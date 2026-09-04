"""Unit tests for the inventory analysis service.

Every collaborator is a local double: the S3/HTTP repository, the analyzer
factory the lifespan publishes, and the two services the plan is filed
through. What is under test is the protocol the SDK's report flow demands —
Markdown in, `id_external_inventory` and `id_request` named at the call site,
an `AekoAnalysisResponse` out — and what the API does with the result.
"""

import inspect
from io import BytesIO

import pytest
from openpyxl import Workbook

from improvement_plan.entity import ImprovementPlan
from inventory_analysis.inventory_analysis import IService
from inventory_analysis.service import Service
from shared.event_tracking import (
    bind_id_request,
    set_aeko_metrics_sink,
    unbind_id_request,
)
from user.entity import UserMemory

ID_USER = "u1"
ID_INVENTORY = 502


def workbook_bytes():
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Escopo 1"
    worksheet.append(["Fonte", "tCO2e"])
    worksheet.append(["Caldeira", 12400])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


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


class StubRepository:
    def __init__(self, payload=None, context=None, error=None):
        self.payload = payload if payload is not None else workbook_bytes()
        self.context = context if context is not None else {}
        self.error = error
        self.calls = []

    def get_excel_bytes(self, s3):
        self.calls.append(("get_excel_bytes", s3))
        if self.error is not None:
            raise self.error
        return self.payload

    def get_external_inventory_context(self, id_external_inventory_4context):
        self.calls.append(("get_external_inventory_context", id_external_inventory_4context))
        return self.context


class StubImprovementPlanService:
    def __init__(self):
        self.created = []

    def get_by_id_external_inventory(self, id_external_inventory):
        raise NotImplementedError

    def create(self, improvement_plan):
        self.created.append(improvement_plan)
        return improvement_plan


class StubUserService:
    def __init__(self):
        self.memories = []

    def get_mongo_user(self, id_external_user):
        raise NotImplementedError

    def get_user_memories(self, id_user):
        return self.memories

    def create_user_memory(self, user_memory):
        self.memories.append(user_memory)


def run(repository=None, analyzers=None, plans=None, users=None,
        id_external_inventory_4context=ID_INVENTORY, s3="bucket/inventory.xlsx"):
    service = Service(repository or StubRepository())
    return service.input_inventory(
        s3,
        ID_USER,
        id_external_inventory_4context,
        users or StubUserService(),
        plans or StubImprovementPlanService(),
        analyzers or StubAnalyzerFactory(),
    )


# ---------------------------------------------------------------------------
# Interface compatibility
# ---------------------------------------------------------------------------
def test_service_implements_the_service_interface():
    assert issubclass(Service, IService)
    assert Service.__abstractmethods__ == frozenset()


def test_input_inventory_signature_matches_the_interface():
    interface = inspect.signature(IService.input_inventory).parameters
    implementation = inspect.signature(Service.input_inventory).parameters

    assert list(interface) == list(implementation)
    assert "aeko_inventory_analyzer_factory" in interface
    # v1 built an `AekoGasReductionDTO`; v2's context is free-form text.
    assert "build_gas_reduction_context" not in interface


# ---------------------------------------------------------------------------
# What the analyzer is handed
# ---------------------------------------------------------------------------
def test_analyze_receives_the_inventory_as_markdown():
    analyzers = StubAnalyzerFactory()

    run(analyzers=analyzers)

    inventory, _, _ = analyzers.last.analyzed[0]
    assert isinstance(inventory, str)
    assert "| Caldeira | 12400 |" in inventory


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


def test_the_previous_report_is_set_as_free_form_text():
    analyzers = StubAnalyzerFactory()
    repository = StubRepository(context={"year": 2025, "total_tco2e": 12400})

    run(repository=repository, analyzers=analyzers)

    assert isinstance(analyzers.last.context, str)
    assert "year: 2025" in analyzers.last.context
    assert "total_tco2e: 12400" in analyzers.last.context


def test_no_context_is_set_when_there_is_no_previous_report():
    analyzers = StubAnalyzerFactory()

    run(repository=StubRepository(context={}), analyzers=analyzers)

    assert analyzers.last.context is None


def test_an_inventory_without_an_identifier_is_rejected():
    """v2 files the plan against the inventory, so the id cannot be missing."""
    with pytest.raises(ValueError, match="id_external_inventory"):
        run(id_external_inventory_4context=None)


# ---------------------------------------------------------------------------
# What the API does with the plan
# ---------------------------------------------------------------------------
def test_the_plan_is_persisted_field_by_field():
    plans = StubImprovementPlanService()

    run(plans=plans)

    plan = plans.created[0]
    assert isinstance(plan, ImprovementPlan)
    assert plan.id is None
    assert plan.id_external_inventory == ID_INVENTORY
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


def test_the_plan_is_returned_as_text():
    assert "high scope 1 emissions" in run()


def test_a_spreadsheet_that_cannot_be_read_is_rejected():
    with pytest.raises(ValueError, match="not a readable .xlsx"):
        run(repository=StubRepository(payload=b"not a workbook"))


def test_a_failing_analyzer_is_surfaced():
    with pytest.raises(RuntimeError, match="coordinator never produced the plan"):
        run(analyzers=StubAnalyzerFactory(error=RuntimeError("coordinator never produced the plan")))


# ---------------------------------------------------------------------------
# The analysis's own event tracking
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
        assert "high scope 1 emissions" in run()
    finally:
        set_aeko_metrics_sink(None)
