"""In-memory stand-in for the real `aeko` package.

The SDK is an external dependency that is not installed in the test
environment. `conftest.py` registers this module under the name `aeko`
in `sys.modules` before any application module is imported, so production
code keeps its plain `from aeko import ...` at the entry point.

Every fake records the calls it receives so tests can assert that the API
wires the SDK correctly (configuration in the lifespan, per-request calls
in the services).
"""


class AekoMessageDTO:
    def __init__(self, input, output, llm="fake-llm", input_tokens=0, output_tokens=0):
        self.input = input
        self.output = output
        self.llm = llm
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class AekoGasReductionDTO:
    def __init__(self, **fields):
        self.fields = fields
        for key, value in fields.items():
            setattr(self, key, value)


class AekoInventoryImprovementPlanDTO:
    def __init__(
        self,
        id_external_inventory=1,
        defined_problem="high scope 1 emissions",
        method="PDCA",
        reasoning="boiler replacement cuts direct emissions",
    ):
        self.id_external_inventory = id_external_inventory
        self.defined_problem = defined_problem
        self.method = method
        self.reasoning = reasoning

    def __str__(self):
        return f"ImprovementPlan({self.defined_problem})"


class AekoMessenger:
    """Records configuration and per-request calls made by the API."""

    def __init__(self):
        self.config_calls = []
        self.tools = None
        self.alter_name = None
        self.prepared_with = None
        self.sent_inputs = []

    # --- configuration (called once, in the app lifespan) ---
    def config(self, models, api_keys):
        self.config_calls.append({"models": models, "api_keys": api_keys})

    def set_tools(self, **tools):
        self.tools = tools

    # --- per-request ---
    def set_alter_name(self, alter_name):
        self.alter_name = alter_name

    def prepare(self, id_user, id_session):
        self.prepared_with = (id_user, id_session)

    def send_message(self, input):
        self.sent_inputs.append(input)
        return AekoMessageDTO(input=input, output=f"echo: {input}")


class _AnalyzedInventory:
    def __init__(self, inventory_bytes):
        self.inventory_bytes = inventory_bytes

    def generate_improvement_plan(self):
        return AekoInventoryImprovementPlanDTO()


class AekoInventoryAnalyzer:
    """Records the context and payload it is handed."""

    def __init__(self):
        self.context = None
        self.analyzed_bytes = None

    def set_context(self, context):
        self.context = context

    def analyze(self, inventory_bytes):
        self.analyzed_bytes = inventory_bytes
        return _AnalyzedInventory(inventory_bytes)
