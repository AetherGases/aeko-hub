from user.user import IService
from user.entity import User

class Service(IService):
    def __init__(self, repository):
        self.repository = repository

    def get_mongo_user(self, id_external_user) -> User:
        try:
            return self.repository.get_user(id_external_user)
        except ValueError as ve:
            raise ve
        except Exception as e:
            raise RuntimeError(f"Error retrieving user: {e}")