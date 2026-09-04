from abc import ABC, abstractmethod

from hub_metrics.entity import Metric

class IRepository(ABC):
    @abstractmethod
    def create_metric(self, metric: Metric) -> Metric:
        pass

    @abstractmethod
    def get_all_metrics(self) -> list[Metric]:
        pass

class IService(ABC):
    @abstractmethod
    def add_metric(self, metric: Metric) -> Metric:
        pass

    @abstractmethod
    def get_all_metrics(self) -> list[Metric]:
        pass
