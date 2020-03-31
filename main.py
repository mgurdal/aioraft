import logging
import aioraft


logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.DEBUG
)

class Storage:
    disk = {}

    def put(self, key, value):
        self.disk[key] = value

    def get(self, key):
        return self.disk[key]


if __name__ == "__main__":
    config = aioraft.Config(
        addr="[::]:50051",
        peers=["0.0.0.0:6543", "0.0.0.0:6544"]
    )
    consensus = aioraft.Cluster(config)
    consensus.register(Storage)
    consensus.start()
