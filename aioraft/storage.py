
from dataclasses import dataclass
from typing import List


@dataclass
class Entry:
    term: int
    command_name: str
    command: bytes


class Storage:
    def __init__(self, config):

        self.disk = {
            "index": 0,
            "term": 0,
            "voted_for": None,
            "commit_index": None,
            "last_applied": None,
            "entries": [],
            "peers": {
                peer: {"match_index": 0, "match_term": 0}
                for peer in config.peers
            }
        }

    @property
    def current_term(self) -> int:
        return self.disk["term"]

    @property
    def current_index(self) -> int:
        return len(self.disk["entries"])

    @current_term.setter
    def current_term(self, term: int):
        self.disk["term"] = term

    @property
    def voted_for(self) -> int:
        return self.disk["voted_for"]

    @voted_for.setter
    def voted_for(self, server):
        self.disk["voted_for"] = server

    @property
    def commit_index(self) -> int:
        return self.disk["commit_index"]

    @commit_index.setter
    def commit_index(self, index):
        self.disk["commit_index"] = index

    @property
    def last_applied(self) -> int:
        return self.disk["last_applied"]

    @last_applied.setter
    def last_applied(self, index):
        self.disk["last_applied"] = index

    def next_index(self, target) -> int:
        try:
            return self.disk["peers"][target]["next_index"]
        except KeyError:
            return 1

    def match_index(self, target) -> int:
        try:
            return self.disk["peers"][target]["match_index"]
        except KeyError:
            return 0

    def match_term(self, target) -> int:
        return self.disk["peers"][target]["match_term"]

    def update_peer(self, target):
        self.disk["peers"][target]["match_index"] = self.current_index
        self.disk["peers"][target]["match_term"] = self.current_term

    def term_at(self, index):
        return self.disk["entries"][index]

    def cut_from(self, index):
        self.disk["entries"][:] = self.disk["entries"][index:]

    @property
    def peers(self):
        return self.disk["peers"]

    @property
    def entries(self) -> List[Entry]:
        return self.disk["entries"]

    def append(self, entry: Entry):
        self.disk["entries"].append(entry)
