from abc import ABC, abstractmethod


class Broker(ABC):

    @property
    @abstractmethod
    def name(self):
        pass

    @abstractmethod
    def login(self, username, password):
        pass

    @abstractmethod
    def get_account(self):
        pass

    @abstractmethod
    def place_order(self, order):
        pass

    @abstractmethod
    def cancel_order(self, order_id):
        pass