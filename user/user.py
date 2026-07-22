from abc import ABC, abstractmethod
from user.entity import User

class IRepository(ABC):
    @abstractmethod
    def get_user(self, id_external_user) -> User:
        pass

class IService(ABC):
    @abstractmethod
    def get_mongo_user(self, id_external_user) -> User:
        pass