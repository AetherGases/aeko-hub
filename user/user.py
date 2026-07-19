from abc import ABC, abstractmethod
from user.entity import User

class IRepository(ABC):
    @abstractmethod
    def getUser(self, id_external_user) -> User:
        pass

class IService(ABC):
    @abstractmethod
    def getMongoUser(self, id_external_user) -> User:
        pass