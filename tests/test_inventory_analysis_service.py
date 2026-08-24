"""Unit tests for the inventory flow against the SDK.

This service is the only caller of `AekoInventoryAnalyzer`. It is not reachable
over HTTP yet — the Reports router is never registered (see `test_e2e.py`) — so
it is exercised directly here, with the SDK injected exactly as the entry point
injects it.
"""

import pytest

from inventory_analysis.service import Service
from tests import fake_aeko

INVENTORY_MARKDOWN = "| source | tCO2e |\n| --- | --- |\n| boiler | 4200 |"


class StubRepository:
    def __init__(self, inventory=INVENTORY_MARKDOWN, context=None):
        """Hold the inventory text and the context to hand back."""
        self.inventory = inventory
        self.context = context or {"total_tco2e": 12400}
        self.context_calls = []

    def get_excel_bytes(self, s3):
        """Return the inventory encoded, the way S3 would."""
        return self.inventory.encode("utf-8")

    def get_external_inventory_context(self, id_external_inventory_4context):
        """Record the request and return the previous report's figures."""
        self.context_calls.append(id_external_inventory_4context)
        return self.context


class StubImprovementPlanService:
    def __init__(self):
        """Start with nothing created."""
        self.created = []

    def get_by_id_external_inventory(self, id_external_inventory):
        """Unused by this flow."""
        raise NotImplementedError

    def create(self, improvement_plan):
        """Record the plan handed in and return it unchanged."""
        self.created.append(improvement_plan)
        return improvement_plan


class StubUserService:
    def __init__(self):
        """Start with no memories recorded."""
        self.memories = []

    def get_mongo_user(self, id_external_user):
        """Unused by this flow."""
        raise NotImplementedError

    def get_user_memories(self, id_user):
        """No memories exist in these tests."""
        return []

    def create_user_memory(self, user_memory):
        """Record one memory."""
        self.memories.append(user_memory)


def build_gas_reduction_context(data):
    """Flatten the previous report the way the entry point does."""
    return "\n".join(f"{key}: {value}" for key, value in data.items())


def run(service=None, repository=None, id_external_inventory_4context=None):
    """Drive one inventory through the service and return what it touched."""
    repository = repository or StubRepository()
    service = service or Service(repository)
    improvement_plan_service = StubImprovementPlanService()
    user_service = StubUserService()

    answer = service.input_inventory(
        "s3://bucket/inventory.xlsx",
        "u1",
        id_external_inventory_4context,
        user_service,
        improvement_plan_service,
        fake_aeko.AekoInventoryAnalyzer,
        build_gas_reduction_context,
    )
    return answer, improvement_plan_service, user_service, repository


@pytest.fixture(autouse=True)
def configured_sdk():
    """Configure the SDK fake, which every analyze call requires."""
    fake_aeko.Aeko.config("test-gemini-key")
    yield


def test_input_inventory_hands_the_analyzer_the_inventory_as_text():
    """The analyzer receives Markdown, not the raw bytes read from S3."""
    answer, _, _, _ = run()

    analyzer = fake_aeko.AekoInventoryAnalyzer.instances[-1]
    assert analyzer.analyzed_markdown == INVENTORY_MARKDOWN
    assert answer == f"plan for: {INVENTORY_MARKDOWN}"


def test_input_inventory_persists_the_plan_returned_by_the_sdk():
    """The SDK returns one block of text, so it fills all three plan fields."""
    answer, improvement_plan_service, _, _ = run(id_external_inventory_4context=9001)

    plan = improvement_plan_service.created[0]
    assert plan.id_external_inventory == 9001
    assert plan.defined_problem == answer
    assert plan.method == answer
    assert plan.reasoning == answer


def test_input_inventory_records_the_plan_as_a_user_memory():
    """The plan is also kept as durable context about the user."""
    answer, _, user_service, _ = run()

    memory = user_service.memories[0]
    assert memory.id_user == "u1"
    assert memory.field == "improvement_plan"
    assert memory.description == answer


def test_input_inventory_sets_the_previous_report_as_context():
    """A previous inventory is fetched and primed as plain text."""
    repository = StubRepository(context={"total_tco2e": 12400, "scope": 1})
    run(repository=repository, id_external_inventory_4context=9001)

    analyzer = fake_aeko.AekoInventoryAnalyzer.instances[-1]
    assert repository.context_calls == [9001]
    assert analyzer.context == "total_tco2e: 12400\nscope: 1"


def test_input_inventory_skips_the_context_when_there_is_no_previous_report():
    """A company's first report legitimately has none."""
    _, _, _, repository = run(id_external_inventory_4context=None)

    analyzer = fake_aeko.AekoInventoryAnalyzer.instances[-1]
    assert repository.context_calls == []
    assert analyzer.context is None


def test_input_inventory_builds_a_fresh_analyzer_per_call():
    """`set_context()` mutates the instance, so sharing one leaks context."""
    service = Service(StubRepository())
    run(service=service)
    run(service=service, id_external_inventory_4context=9001)

    instances = fake_aeko.AekoInventoryAnalyzer.instances
    assert len(instances) == 2
    assert instances[0].context is None
    assert instances[1].context is not None
