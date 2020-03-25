from dataclasses import dataclass
from datetime import datetime


@dataclass
class Message:
    sender: "Server"
    receiver: "Server"
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
