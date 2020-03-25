from dataclasses import dataclass
from datetime import datetime
from typing import Set, Union

from aioraft.packets import AppendEntries, Message, RequestVote
from aioraft.roles import Candidate, Follower, Leader


@dataclass
class Peer:
    server: "Server"
    next_index: int
    match_index: int
    vote_granted: bool = False
    rpc_due: int = 10 / 1000
    heartbeat_due: int = 10 / 1000

    def __str__(self):
        return (
            f"{self.server.addr}"
            f"{self.match_index} {self.next_index} {self.vote_granted}"
            f"{self.rpc_due} {self.heartbeat_due}"
        )

    def __hash__(self):
        return hash(self.server.addr)

    def __eq__(self, other: "Peer"):
        return self.server.addr == other.server.addr


class Network:
    def __init__(self, server):
        self.server = server

    def send(self, message: Message) -> Message:
        for peer in self.server.peers:
            if message.receiver == peer.server.addr:
                response = peer.server.on_message(message)
                return response


class Server:
    addr: str
    peers: Set[Peer]
    log: dict  # (1, 1): []
    role: Union[Follower, Candidate, Leader]
    storage: dict
    net: Network

    def __init__(self, addr):
        self.storage = {}
        self.role = Follower(self)
        self.peers = set()
        self.addr = addr
        self.net = Network(self)
        self.storage = {"commit_index": 0}

    def add_peer(self, *servers: "Server"):
        for server in servers:
            self.peers.add(
                Peer(
                    server=server,
                    match_index=server.storage["commit_index"],
                    next_index=server.storage["commit_index"] + 1,
                )
            )

    def become(self, cls: Union["Follower", "Leader", "Candidate"]):
        print(f"Server {self.addr} became a {cls} from {self.role.__class__}")
        self.stop()
        self.role = cls(self)
        self.role.start()

    def start(self):
        self.role.start()

    def stop(self):
        self.role.stop()

    def send(self, message: "Message") -> "Message":
        return self.net.send(message)

    def on_message(self, message: "Message"):
        current_term = self.storage["term"]
        if current_term < message.term:
            self.storage["term"] = message.term
            if not isinstance(self, Follower):
                self.become(Follower)

        message.delivered_at = datetime.now()

        if isinstance(message, RequestVote):
            response = self.role.on_request_vote(message)
        elif isinstance(message, AppendEntries):
            response = self.role.on_append_entries(message)
        return response
