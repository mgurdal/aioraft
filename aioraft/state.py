import logging
from abc import abstractmethod
from datetime import datetime
from typing import List, Optional

from aioraft.network import Server
from aioraft.packet import (
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


class State:
    term: int
    votedFor: int
    commitIndex: int
    lastApplied: int
    server: Server

    def on_request_vote(self, message: RequestVote) -> RequestVoteReply:
        current_term = self.server.storage.current_term

        if message.last_log_term != current_term:
            up_to_date = message.last_log_term > current_term
        else:
            up_to_date = message.last_log_index >= self.server.storage.current_index

        vote = RequestVoteReply(
            term=current_term,
            delivered_at=None,
            sent_at=datetime.now(),
            granted=up_to_date,
        )

        if vote.granted:
            self.server.storage.voted_for = message.candidate_id

        return vote

    @abstractmethod
    def on_append_entries(self, message: AppendEntries) -> AppendEntriesReply:
        raise NotImplementedError


class Leader(State):
    server: 'Server'
    heartbeat: Timer
    resignation_timer: Timer


    def __init__(self, server: 'Server'):
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
            if self.server.storage.match_index(target.id) > 0:
                prev_term = self.server.storage.match_term(target)
            else:
                prev_term = None

            e = AppendEntries(
                leader_id=self.server.id,
                term=self.server.storage.current_term,
                sent_at=datetime.now(),
                delivered_at=None,
                commit_index=self.server.storage.commit_index,
                entries=[], # todo: populate entries
                prev_index=self.server.storage.match_index(target.id) - 1,
                prev_term=prev_term,
            )

            self.server.storage.update_peer(target.id)
            # todo: send with grpc client
            response: AppendEntriesReply = self.server.send(e)
            responses.append(response)

        successful_responses = [r for r in responses if r.success]
        could_reach_to_majority = (
            len(successful_responses) >= len(self.server.storage.peers) // 2
        )
        if could_reach_to_majority:
            logging.debug(
                f"{self.server.id} maintained leadership {len(successful_responses)}/{len(self.server.peers)}"
            )
            self.resignation_timer.reset()

    def on_append_entries(self, message: AppendEntries) -> AppendEntriesReply:
        if message.term > self.server.storage.current_term:
            self.become_follower()

    def send_heartbeat(self):
        logging.debug(f"{self.server.id} sending heartbeats")
        self.append_entries()


class Candidate(State):

    server: 'Server'
    election_timer: Timer
    log: List[int]  # holds terms

    def __init__(self, server: 'Server'):
        self.server = server
        self.election_timer = Timer(ELECTION_INTERVAL, self.become_follower)

    def start(self):
        self.server.storage.current_term += 1
        self.server.storage.voted_for = self.server.id

        self.request_vote()
        self.election_timer.start()

    def stop(self):
        self.election_timer.stop()

    def become_follower(self):
        self.server.become(Follower)

    def request_vote(self):
        """Try to get votes from all peers"""
        responses: List[RequestVoteReply] = [
            # todo: send with grcp client
            self.server.send(
                RequestVote(
                    term=self.server.storage.current_term,
                    last_log_index=peer["match_index"],
                    last_log_term=peer["match_term"],
                    delivered_at=None,
                    sent_at=datetime.now(),
                    candidate_id=self.server.id
                )
            )
            for peer in self.server.storage.peers
        ]

        # become leader if granted by majority
        granted_votes = len([vote for vote in responses if vote.granted]) + 1
        granted_by_majority = granted_votes > len(self.server.storage.peers) // 2
        logging.debug(f"{self.server.id} got vote from {len(responses)} servers")
        if granted_by_majority:
            self.server.become(Leader)

    def on_append_entries(self, message: AppendEntries) -> AppendEntriesReply:
        self.become_follower()


class Follower(State):
    server: 'Server'
    election_timer: Timer
    election_due: int = 10
    voted_for: Optional["Server"] = None

    def __init__(self, server: 'Server'):
        self.server = server
        self.election_timer = Timer(ELECTION_INTERVAL, self.become_candidate)

    def start(self):
        logging.debug(f"Starting follower {self.server.id}")
        self.election_timer.start()

    def stop(self):
        self.election_timer.stop()

    def __str__(self):
        return (
            f"[{self.__class__}] {self.server.id}\n"
            f"Term: {self.server.storage.current_term} Commit Index: {self.server.storage.commit_index}"
        )

    def become_candidate(self):
        logging.debug(f"{self.server.id} starting an election")
        self.server.become(Candidate)

    def on_append_entries(self, message: AppendEntries) -> AppendEntriesReply:

        last_log_index = self.server.storage.current_index
        # reach to a prev log index and check terms
        # check previous index and term
        if message.prev_index > last_log_index or (
            message.prev_term and self.server.storage.term_at(message.prev_index) != message.prev_term
        ):
            r = AppendEntriesReply(
                success=False,
                term=message.term,
                delivered_at=None,
                sent_at=datetime.now(),
                match_index=message.commit_index,
            )
            return r

        # rewrite log if terms does not match
        next_index = message.prev_index + 1
        if next_index < last_log_index:
            if self.server.storage.term_at(next_index) != message.term or (last_log_index != message.prev_index):
                logging.debug(
                    f"{self.server.id} shrunk to {next_index}"
                )
                self.server.storage.cut_from(next_index)

        for entry in message.entries:
            self.server.storage.append(entry)

        self.server.storage.current_term = message.term

        if self.server.storage.commit_index < message.commit_index:
            self.server.storage.commit_index = min(self.server.storage.commit_index, message.commit_index)

        self.election_timer.reset()

        r = AppendEntriesReply(
            term=self.server.storage.current_term,
            success=True,
            match_index=self.server.storage.current_index,
            sent_at=datetime.now(),
            delivered_at=None,
        )
        return r
