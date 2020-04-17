import logging
from datetime import datetime
from typing import Union, Any

import grpc

from aioraft.packet import (
    AppendEntries,
    Message,
    RequestVote,
    AppendEntriesReply,
    RequestVoteReply,
)
from aioraft.state import Candidate, Follower, Leader
from aioraft.storage import Storage, Entry
from protos import raft_pb2_grpc, raft_pb2
from protos.raft_pb2_grpc import RaftServiceServicer

from protos.raft_pb2 import RequestVoteRequest, RequestVoteResponse
from protos.raft_pb2 import AppendEntriesRequest, AppendEntriesResponse, Entry


class Peer:
    addr: str
    # todo: use interface instead
    client: raft_pb2_grpc.RaftServiceStub
    storage: Storage

    def __init__(self, addr, storage):
        self.addr = addr
        self.storage = storage
        channel = grpc.insecure_channel(addr)
        self.client = raft_pb2_grpc.RaftServiceStub(channel)

    @property
    def match_index(self):
        return self.storage.match_index(self.addr)

    @property
    def match_term(self):
        return self.storage.match_term(self.addr)

    def SendAppendEntries(self, message: AppendEntries):
       
        req = raft_pb2.AppendEntriesRequest(
            term=message.term,
            leaderId=message.leader_id,
            prevLogIndex=message.prev_index,
            prevLogTerm=message.prev_term,
            entries=message.entries,
            leaderCommit=message.commit_index,
        )
        response: AppendEntriesResponse = self.client.AppendEntries(req)
        return AppendEntriesReply(
            term=response.term,
            sent_at=None,
            delivered_at=None,
            success=response.success,
            # todo: fill match_index
            match_index=self.match_index,
        )

    def SendRequestVote(self, message: RequestVote) -> RequestVoteReply:
        req = RequestVoteRequest(
            term=message.term,
            candidateId=message.candidate_id,
            lastLogIndex=message.last_log_index,
            lastLogTerm=message.last_log_term,
        )
        response: RequestVoteResponse = self.client.RequestVote(req)

        return RequestVoteReply(
            term=response.term,
            granted=response.voteGranted,
            sent_at=datetime.now(),
            delivered_at=None,
        )

    def __str__(self):
        return f"{self.addr}"

    def __hash__(self):
        return hash(self.addr)

    def __eq__(self, other: "Peer"):
        return self.addr == other


class Server(RaftServiceServicer):
    addr: str
    role: Union[Follower, Candidate, Leader]
    storage: Storage
    peers: set
    state_machine: Any
    client: raft_pb2_grpc.RaftServiceStub

    def __init__(self, addr, state_machine):
        self.addr = addr
        self.role = Follower(self)
        self.state_machine = state_machine
        self.peers = set()
        channel = grpc.insecure_channel(addr)
        self.client = raft_pb2_grpc.RaftServiceStub(channel)

    def set_storage(self, storage: Storage):
        self.storage = storage

    def become(self, state: Union[Follower, Leader, Candidate]):
        """
        Switches the server state to given state.
        """
        logging.info(f"Server {self.addr} became a {state} from {self.role.__class__}")
        self.stop()
        self.role = state(self)
        self.role.start()

    def register_command(self, command_name, value):
        """
        Registers the new client command to the storage.
        """
        self.storage.append(
            Entry(
                index=self.storage.current_index,
                term=self.storage.current_term,
                commandName=command_name,
                command=value.encode()
            )
        )

    def apply(self, entry: Entry):
        import json
        logging.critical(entry.command.decode())
        args, kwargs = json.loads(entry.command.decode())
        command_name = entry.command_name
        logging.debug(f"Applying command {command_name}({args},{kwargs})")
        getattr(self.state_machine, command_name)(*args, **kwargs)

    def start(self):
        self.role.start()

    def stop(self):
        self.role.stop()

    def add_peer(self, *servers: str):
        for server in servers:
            self.peers.add(Peer(addr=server, storage=self.storage))

    async def validate_term(self, message: Message):
        """
        Step downs the follower if server receives 
        a message with a higher term
        """
        current_term = self.storage.current_term
        if current_term < message.term:
            self.storage.current_term = message.term
            if not isinstance(self, Follower):
                self.become(Follower)

        message.delivered_at = datetime.now()

    def AppendEntries(
        self, request: AppendEntriesRequest, context
    ) -> AppendEntriesResponse:
        """AppendEntries performs a single append entries RPC using network client
        and callbacks Role.on_append_entries with the response.
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
            delivered_at=None,
            leader_id=request.leaderId,
            sent_at=None,
        )
        try:
            response: AppendEntriesReply = self.role.on_append_entries(message)
            return AppendEntriesResponse(
                term=response.term,
                success=response.success,
                matchIndex=response.match_index,
            )
        except Exception as e:
            logging.exception(e)

    def RequestVote(self, request: RequestVoteRequest, context):
        """
        RequestVote asks to a Raft peer for a vote in an election
        and callbacks Role.on_request_vote with the response.
        """
        message = RequestVote(
            term=request.term,
            candidate_id=request.candidateId,
            last_log_index=request.lastLogIndex,
            last_log_term=request.lastLogTerm,
            sent_at=None,
            delivered_at=None,
        )
        vote: RequestVoteReply = self.role.on_request_vote(message)
        return RequestVoteResponse(term=vote.term, voteGranted=vote.granted)
