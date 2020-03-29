from dataclasses import dataclass
from datetime import datetime


@dataclass
class Message:
    term: int
    delivered_at: datetime
    sent_at: datetime


@dataclass
class AppendEntries(Message):
    leader_id: int
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
    candidate_id: int
    last_log_index: int
    last_log_term: int


@dataclass
class RequestVoteReply(Message):
    granted: bool  # alters peer granted
