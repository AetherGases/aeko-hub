from aeko_metrics.aeko_metrics import IService
from aeko_metrics.entity import Metric

class Service(IService):
    def __init__(self, repository):
        self.repository = repository

    def add_metric(self, metric: Metric) -> Metric:
        try:
            return self.repository.create_metric(metric)
        except Exception as e:
            raise RuntimeError(f"Error adding aeko metric: {e}")

    def get_all_metrics(self) -> list[Metric]:
        try:
            return self.repository.get_all_metrics()
        except Exception as e:
            raise RuntimeError(f"Error retrieving aeko metrics: {e}")
