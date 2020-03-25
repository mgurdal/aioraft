import logging
from abc import abstractmethod
from collections import defaultdict
from datetime import datetime
from typing import List, Optional
from xmlrpc.client import Server

from aioraft.packets import (
    AppendEntries,
    AppendEntriesReply,
    RequestVote,
    RequestVoteReply,
)
from aioraft.scheduler import Timer

# FOLLOWER is passive but expects regular heartbeats to not become a CANDIDATE
FOLLOWER = "follower"

# Sends RequestVote message to all other servers to leader election
# becomes a leader if gets vote from majority
CANDIDATE = "candidate"

# Send AppendEntry messages to the followers. AppendEntry messages contains the
# replicated logs. Message also can be empty just to send heartbeat
# to the followers in order to maintain the leadership
LEADER = "leader"

DEFAULT_TIMEOUT = 0.1  # seconds
ELECTION_INTERVAL = 2  # seconds


class Role:
    server: Server

    def on_request_vote(self, message: RequestVote) -> RequestVoteReply:
        current_term = self.server.storage["log"][self.server.addr][-1]
        if message.last_log_term != current_term:
            up_to_date = message.last_log_term > current_term
        else:
            up_to_date = message.last_log_index >= len(
                self.server.storage["log"][self.server.addr]
            )

        response = RequestVoteReply(
            term=current_term,
            sender=self.server.addr,
            receiver=message.sender,
            delivered_at=None,
            sent_at=datetime.now(),
            granted=up_to_date,
        )
        return response

    @abstractmethod
    def on_append_entries(self, message: AppendEntries) -> AppendEntriesReply:
        raise NotImplementedError


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

    def append_entries(self, target: "Follower" = None):
        broadcast = [peer.server for peer in self.server.peers]
        targets = [target.server] if target else broadcast

        responses = []
        for target in targets:
            if len(self.server.storage["log"][target.addr]) > 0:
                prev_term = self.server.storage["log"][target.addr][-1]
            else:
                prev_term = None
            e = AppendEntries(
                sender=self.server.addr,
                receiver=target.addr,
                term=self.server.storage["term"],
                sent_at=datetime.now(),
                delivered_at=None,
                commit_index=len(self.server.storage["log"]),
                entries=[],
                prev_index=len(self.server.storage["log"][target.addr]) - 1,
                prev_term=prev_term,
            )
            self.server.storage["log"][target.addr].append(self.server.storage["term"])
            response: AppendEntriesReply = self.server.send(e)
            responses.append(response)

        successful_responses = [r for r in responses if r.success]
        could_reach_to_majority = (
            len(successful_responses) >= len(self.server.peers) // 2
        )
        if could_reach_to_majority:
            logging.debug(
                f"{self.server.addr} maintained leadership {len(successful_responses)}/{len(self.server.peers)}"
            )
            self.resignation_timer.reset()

    def send_heartbeat(self):
        logging.debug(f"{self.server.addr} sending heartbeats")
        self.append_entries()


class Candidate(Role):

    server: Server
    election_timer: Timer
    log: List[int]  # holds terms

    def __init__(self, server: Server):
        self.server = server
        self.election_timer = Timer(ELECTION_INTERVAL, self.become_follower)

    def start(self):
        self.server.storage.update(
            {"term": self.server.storage["term"] + 1, "voted_for": self.server.addr}
        )
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
                    term=self.server.storage["term"],
                    last_log_index=len(self.server.storage["log"][peer.server.addr]),
                    last_log_term=self.server.storage["log"][peer.server.addr][-1],
                    delivered_at=None,
                    sent_at=datetime.now(),
                )
            )
            for peer in self.server.peers
        ]

        # become leader if granted by majority
        granted_votes = len([vote for vote in responses if vote.granted]) + 1
        granted_by_majority = granted_votes > len(self.server.peers) // 2
        logging.debug(f"{self.server.addr} got vote from {len(responses)} servers")
        if granted_by_majority:
            self.server.become(Leader)

    def on_append_entries(self, message: AppendEntries) -> AppendEntriesReply:
        self.become_follower()


class Follower(Role):
    server: Server
    election_timer: Timer
    election_due: int = 10
    voted_for: Optional["Server"] = None

    def __init__(self, server: Server):
        self.server = server
        self.election_timer = Timer(ELECTION_INTERVAL, self.become_candidate)

    def start(self):
        logging.debug(f"Starting follower {self.server.addr}")
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
        logging.debug(f"{self.server.addr} starting an election")
        self.server.become(Candidate)

    def init_storage(self):
        # todo: move to server
        self.server.storage.update(
            {"term": 0, "voted_for": None, "commit_index": 0, "log": defaultdict(list)}
        )
        self.server.storage["log"][self.server.addr].append(0)

        for peer in self.server.peers:
            self.server.storage["log"][peer.server.addr].append(0)

    def on_append_entries(self, message: AppendEntries) -> AppendEntriesReply:

        log = self.server.storage["log"][self.server.addr]

        last_log_index = len(log) - 1
        # reach to a prev log index and check terms
        # check previous index and term
        if message.prev_index > last_log_index or (
            message.prev_term and log[message.prev_index] != message.prev_term
        ):
            r = AppendEntriesReply(
                success=False,
                sender=self.server.addr,
                receiver=message.sender,
                term=message.term,
                delivered_at=None,
                sent_at=datetime.now(),
                match_index=message.commit_index,
            )
            return r

        # rewrite log if terms does not match
        next_index = message.prev_index + 1
        if next_index < last_log_index:
            if log[next_index] != message.term or (last_log_index != message.prev_index):
                logging.debug(
                    f"{self.server.addr} shrunk log from {len(log)} to {next_index}"
                )
                log[:] = log[next_index:]

        log.append(message.term)
        for entry in message.entries:
            log.append(entry)

        self.server.storage["term"] = message.term

        if self.server.storage["commit_index"] < message.commit_index:
            self.server.storage["commit_index"] = min(len(log)-1, message.commit_index)

        self.election_timer.reset()

        r = AppendEntriesReply(
            sender=self.server,
            receiver=message.sender,
            term=log[-1],
            success=True,
            match_index=len(log) - 1,
            sent_at=datetime.now(),
            delivered_at=None,
        )
        return r
