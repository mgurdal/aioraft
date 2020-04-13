import logging
import argparse

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
    parser = argparse.ArgumentParser(description='Raft node arguments')
    parser.add_argument('addr', metavar='addr', type=str, help='node addr')
    parser.add_argument('peers', metavar='peers', type=str, nargs='+', help='peers')

    args = parser.parse_args()
    
    config = aioraft.Config(
        addr=str(args.addr),  # [::]:50051
        peers=args.peers
    )
    consensus = aioraft.Cluster(config)
    consensus.register(Storage)
    consensus.start()
