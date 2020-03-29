import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Set, Union

from aioraft.packet import AppendEntries, Message, RequestVote, \
    AppendEntriesReply, RequestVoteReply
from aioraft.state import Candidate, Follower, Leader
from aioraft.storage import Storage
from protos.raft_pb2_grpc import RaftServiceServicer

from protos.raft_pb2 import RequestVoteRequest, RequestVoteResponse
from protos.raft_pb2 import AppendEntriesRequest, AppendEntriesResponse


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
            f"{self.server.id}"
            f"{self.match_index} {self.next_index} {self.vote_granted}"
            f"{self.rpc_due} {self.heartbeat_due}"
        )

    def __hash__(self):
        return hash(self.server.id)

    def __eq__(self, other: "Peer"):
        return self.server.id == other.server.id


class Server(RaftServiceServicer):
    id: uuid.uuid4
    log: dict  # (1, 1): []
    role: Union[Follower, Candidate, Leader]
    storage: Storage
    state_machine: object

    def __init__(self, id, state_machine):
        self.id = id
        self.role = Follower(self)
        self.peers = set()
        self.state_machine = state_machine

    def set_storage(self, storage: Storage):
        self.storage = storage

    def add_peer(self, *servers: int):
        for server in servers:
            self.peers.add(
                Peer(
                    server=server,
                    match_index=self.storage.match_index(server),
                    next_index=self.storage.next_index(server),
                )
            )

    def become(self, cls: Union["Follower", "Leader", "Candidate"]):
        print(f"Server {self.id} became a {cls} from {self.role.__class__}")
        self.stop()
        self.role = cls(self)
        self.role.start()

    def start(self):
        self.role.start()

    def stop(self):
        self.role.stop()

    async def validate_term(self, message: "Message"):
        current_term = self.storage.current_term
        if current_term < message.term:
            self.storage.current_term = message.term
            if not isinstance(self, Follower):
                self.become(Follower)

        message.delivered_at = datetime.now()

    def AppendEntries(self, request: AppendEntriesRequest,
                      context) -> AppendEntriesResponse:
        """AppendEntries performs a single append entries request / response.
        :param request: AppendEntriesRequest(
            term=1,
            leaderId=2,
            prevLogIndex=3,
            prevLogTerm=4,
            entries=[Entry(index, name, commandName, command)],
            leaderCommit=6,
        )
        """
        message = AppendEntries(
            term=request.term,
            prev_index=request.prevLogIndex,
            prev_term=request.prevLogTerm,
            entries=request.entries,
            commit_index=request.leaderCommit,
            delivered_at=datetime.now(),
            leader_id=request.leaderId,
            sent_at=None
        )
        try:
            response: AppendEntriesReply = self.role.on_append_entries(message)

            return AppendEntriesResponse(
                term=response.term,
                success=response.success
            )
        except Exception as e:
            logging.exception(e)

    def RequestVote(self, request: RequestVoteRequest, context):
        """RequestVote is the command used by a candidate to ask a Raft peer for a vote in an election.
        """
        message = RequestVote(
            term=request.term,
            candidate_id=request.candidateId,
            last_log_index=request.lastLogIndex,
            last_log_term=request.lastLogTerm,
            sent_at=None,
            delivered_at=datetime.now()
        )
        vote: RequestVoteReply = self.role.on_request_vote(message)
        return RequestVoteResponse(
            term=vote.term,
            voteGranted=vote.granted
        )
