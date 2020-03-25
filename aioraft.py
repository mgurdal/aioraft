"""
Raft design
"""

import asyncio
import random
from abc import abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Union, Set

# FOLLOWER is passive but expects regular heartbeats to not become a CANDIDATE
FOLLOWER = 'follower'

# Sends RequestVote message to all other servers to leader election
# becomes a leader if gets vote from majority
CANDIDATE = 'candidate'

# Send AppendEntry messages to the followers. AppendEntry messages contains the
# replicated logs. Message also can be empty just to send heartbeat
# to the followers in order to maintain the leadership
LEADER = 'leader'

DEFAULT_TIMEOUT = 3
ELECTION_INTERVAL = 10

STORAGE = {}


def next_timeout(initial_timeout=DEFAULT_TIMEOUT) -> int:
    return random.randrange(initial_timeout, 2 * initial_timeout)


class Network:

    def __init__(self, server):
        self.server = server

    def send(self, message: 'Message') -> 'Message':
        for peer in self.server.peers:
            if message.receiver == peer.server.addr:
                response = peer.server.on_message(message)
                return response


class Timer:
    def __init__(self, interval, callback):
        self.interval = interval
        self.callback = callback
        self.loop = asyncio.get_event_loop()
        self.scheduler_task = self.loop.call_later(
            self.interval, self._run
        )
        self.is_active = False

    def start(self):
        self.is_active = True

    def _run(self):
        if self.is_active:
            self.callback()
            self.scheduler_task = self.loop.call_later(
                self.interval, self._run
            )

    def stop(self):
        self.is_active = False
        self.scheduler_task.cancel()

    def reset(self):
        self.stop()
        self.start()


@dataclass
class Peer:
    server: 'Server'
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

    def __eq__(self, other: 'Peer'):
        return self.server.addr == other.server.addr


class Server:
    addr: str
    peers: Set[Peer]
    log: dict  # (1, 1): []
    role: Union['Follower', 'Leader', 'Candidate']
    storage: dict
    net: Network

    def __init__(self, addr):
        self.storage = {}
        self.role = Follower(self)
        self.peers = set()
        self.addr = addr
        self.net = Network(self)
        self.storage = {
            "commit_index": 0
        }

    def add_peer(self, *servers: 'Server'):
        for server in servers:
            self.peers.add(Peer(
                server=server,
                match_index=server.storage['commit_index'],
                next_index=server.storage['commit_index']+1,
            ))

    def become(self, cls: Union['Follower', 'Leader', 'Candidate']):
        print(f"Server {self.addr} became a {cls} from {self.role.__class__}")
        self.stop()
        self.role = cls(self)
        self.role.start()

    def start(self):
        self.role.start()

    def stop(self):
        self.role.stop()

    def send(self, message: 'Message') -> 'Message':
        return self.net.send(message)

    def on_message(self, message: 'Message'):
        current_term = self.storage['term']
        if current_term < message.term:
            self.storage['term'] = message.term
            if not isinstance(self, Follower):
                self.become(Follower)

        message.delivered_at = datetime.now()

        if isinstance(message, RequestVote):
            response = self.role.on_request_vote(message)
        elif isinstance(message, AppendEntries):
            response = self.role.on_append_entries(message)
        return response


@dataclass
class Role:
    def on_request_vote(self, message: 'RequestVote') -> 'RequestVoteReply':
        current_term = self.server.storage['log'][self.server.addr][-1]
        if message.last_log_term != current_term:
            up_to_date = message.last_log_term > current_term
        else:
            up_to_date = message.last_log_index >= len(self.server.storage['log'][self.server.addr])

        response = RequestVoteReply(
            term=current_term,
            sender=self.server.addr,
            receiver=message.sender,
            delivered_at=None,
            sent_at=datetime.now(),
            granted=up_to_date
        )
        return response

    @abstractmethod
    def on_append_entries(self, message: 'AppendEntries') -> 'AppendEntriesReply':
        raise NotImplementedError


@dataclass
class Leader(Role):
    server: Server
    heartbeat: Timer
    resignation_timer: Timer

    def __init__(self, server: Server):
        self.server = server
        self.heartbeat = Timer(DEFAULT_TIMEOUT, self.send_heartbeat)
        self.resignation_timer = Timer(ELECTION_INTERVAL, self.become_follower)

    def become_follower(self):
        self.server.become(Follower)

    def start(self):
        self.send_heartbeat()
        self.heartbeat.start()
        self.resignation_timer.start()

    def stop(self):
        self.heartbeat.stop()
        self.resignation_timer.stop()

    def append_entries(self, target: 'Follower'=None):
        broadcast = [peer.server for peer in self.server.peers]
        targets = [target.server] if target else broadcast

        responses = []
        for target in targets:
            if len(self.server.storage['log'][target.addr]) > 0:
                prev_term = self.server.storage['log'][target.addr][-1]
            else:
                prev_term = None
            e = AppendEntries(
                sender=self.server.addr,
                receiver=target.addr,
                term=self.server.storage['term'],
                sent_at=datetime.now(),
                delivered_at=None,
                commit_index=len(self.server.storage['log']),
                entries=[],
                prev_index=len(self.server.storage['log'][target.addr]) - 1,
                prev_term=prev_term
            )
            self.server.storage['log'][target.addr].append(self.server.storage['term'])
            response: AppendEntriesReply = self.server.send(e)
            responses.append(response)

        successful_responses = [r for r in responses if r.success]
        could_reach_to_majority = len(successful_responses) >= len(self.server.peers) // 2
        if could_reach_to_majority:
            print(f"{self.server.addr} maintained leadership")
            self.resignation_timer.reset()

    def send_heartbeat(self):
        print(f"{self.server.addr} sending heartbeats")
        self.append_entries()


@dataclass
class Candidate(Role):

    server: Server
    election_timer: Timer
    log: List[int]  # holds terms

    def __init__(self, server: Server):
        self.server = server
        self.election_timer = Timer(ELECTION_INTERVAL, self.become_follower)

    def start(self):
        self.server.storage.update({
            'term': self.server.storage['term'] + 1,
            'voted_for': self.server.addr
        })
        self.request_vote()
        self.election_timer.start()

    def stop(self):
        self.election_timer.stop()

    def become_follower(self):
        self.server.become(Follower)

    def request_vote(self):
        """Try to get votes from all peers"""
        responses: List[RequestVoteReply] = [
            self.server.send(
                RequestVote(
                    sender=self.server.addr,
                    receiver=peer.server.addr,
                    term=self.server.storage['term'],
                    last_log_index=len(self.server.storage['log'][peer.server.addr]),
                    last_log_term=self.server.storage['log'][peer.server.addr][-1],
                    delivered_at=None,
                    sent_at=datetime.now()
                )
            ) for peer in self.server.peers
        ]

        # become leader if granted by majority
        granted_votes = len([vote for vote in responses if vote.granted])+1
        granted_by_majority = granted_votes > len(self.server.peers) // 2
        print(f"{self.server.addr} got vote from {len(responses)} servers")
        if granted_by_majority:
            self.server.become(Leader)

    def on_append_entries(self,
                          message: 'AppendEntries') -> 'AppendEntriesReply':
        self.become_follower()


class Follower(Role):
    server: Server
    election_timer: Timer
    election_due: int = 10
    voted_for: Optional['Server'] = None

    def __init__(self, server: Server):
        self.server = server
        self.election_timer = Timer(ELECTION_INTERVAL, self.become_candidate)

    def start(self):
        print(f"Starting follower {self.server.addr}")
        self.init_storage()
        self.election_timer.start()

    def stop(self):
        self.election_timer.stop()

    def __str__(self):
        return (
            f"[{self.__class__}] {self.server.addr}\n"
            f"Term: {self.server.storage['term']} Commit Index: {self.server.storage['commit_index']}"
        )

    def become_candidate(self):
        print(f"{self.server.addr} starting an election")
        self.server.become(Candidate)

    def init_storage(self):
        # todo: move to server
        self.server.storage.update({
            "term": 0,
            "voted_for": None,
            "commit_index": 0,
            "log": defaultdict(list)
        })
        self.server.storage['log'][self.server.addr].append(0)

        for peer in self.server.peers:
            self.server.storage['log'][peer.server.addr].append(0)

    def on_append_entries(self, message: 'AppendEntries') -> 'AppendEntriesReply':

        log = self.server.storage['log'][self.server.addr]

        # reach to a prev log index and check terms
        prev_term = log[message.prev_index]

        # check previous index and term
        print(message.prev_index, len(log), message.term, message.prev_term and log[message.prev_index])
        if message.prev_index > len(log)-1 or (message.prev_term and log[message.prev_index] != message.prev_term):
            r = AppendEntriesReply(
                success=False,
                sender=self.server.addr,
                receiver=message.sender,
                term=message.term,
                delivered_at=None,
                sent_at=datetime.now(),
                match_index=message.commit_index
            )
            print(r)
            return r

        # rewrite log if terms does not match
        next_index = message.prev_index + 1
        if next_index < len(log)-1:
            if log[next_index] != message.term or (len(log)-1 != message.prev_index):
                print(f"{self.server.addr} shrunk log from {len(log)} to {next_index}")
                log[:] = log[next_index:]

        log.append(message.term)
        for entry in message.entries:
            log.append(entry)

        self.server.storage["term"] = message.term

        if self.server.storage['commit_index'] < message.commit_index:
            self.server.storage['commit_index'] = min(len(log), message.commit_index)

        self.election_timer.stop()
        r = AppendEntriesReply(
                sender=self.server,
                receiver=message.sender,
                term=log[-1],
                success=True,
                match_index=len(log)-1,
                sent_at=datetime.now(),
                delivered_at=None
            )
        print(r)
        return r

@dataclass
class Message:
    sender: Server
    receiver: Server
    term: int
    delivered_at: datetime
    sent_at: datetime

@dataclass
class AppendEntries(Message):
    prev_index: int
    prev_term: int
    commit_index: int
    entries: []


@dataclass
class AppendEntriesReply(Message):
    success: bool
    match_index: int


@dataclass
class RequestVote(Message):
    last_log_index: int
    last_log_term: int


@dataclass
class RequestVoteReply(Message):
    granted: bool  # alters peer granted
