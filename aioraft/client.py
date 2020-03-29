import functools
from concurrent import futures
from dataclasses import dataclass

from aioraft.storage import Storage
from protos import raft_pb2_grpc

import grpc

from aioraft.network import Server


def track(command):
    """Tracks given command and replicates in cluster"""
    print("Tracking", command)

    @functools.wraps(command)
    def wrapper(*args, **kwargs):
        print("Replicating", command, "with", args, kwargs)
        # Replicate state machine
        return command(*args, **kwargs)
    return wrapper


@dataclass
class Config:
    addr: str
    peers: []


class Cluster:
    server: Server
    config: Config
    _grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))

    def __init__(self, config: Config):
        self.config = config

    def register(self, state_machine):

        for k, v in vars(state_machine).items():
            if callable(v):
                setattr(state_machine, k, track(v))

        server = Server(id=self.config.addr, state_machine=state_machine)

        self.server = server

    def start(self):
        with Storage(self.config) as storage:
            self.server.set_storage(storage)
            raft_pb2_grpc.add_RaftServiceServicer_to_server(
                self.server, self._grpc_server
            )
            self._grpc_server.add_insecure_port(self.config.addr)
            print("Starting at", self.config.addr)

            self._grpc_server.start()
            self._grpc_server.wait_for_termination()
