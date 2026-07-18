from datetime import datetime

class Input_report_analysis:
    id: str
    id_external_report: int
    gas: str
    emitted_tons: float
    observations: list
    created_at: datetime

    def __init__(self, id: str, id_external_report: int, gas: str, emitted_tons: float, observations: list, created_at: datetime):
        self.id = id
        self.id_external_report = id_external_report
        self.gas = gas
        self.emitted_tons = emitted_tons
        self.observations = observations
        self.created_at = created_at