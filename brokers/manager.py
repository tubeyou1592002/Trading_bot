from .agaah import AgaahBroker


class BrokerManager:

    def __init__(self):
        self.brokers = {
            "آگاه": AgaahBroker(),
        }

    def names(self):
        return list(self.brokers.keys())

    def get(self, name):
        if name not in self.brokers:
            raise ValueError(
                f"Unknown broker: {name}"
            )

        return self.brokers[name]