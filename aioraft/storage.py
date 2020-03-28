
from dataclasses import dataclass
import aiosqlite


@dataclass
class Entry:
    index: int
    term: int
    command_name: str
    command: bytes
    voted_for: int
    commit_index: int
    last_applied: int


class Storage:
    def __init__(self, name):
        self.name = name

    @property
    def current_term(self) -> int:
        pass

    @property
    def voted_for(self) -> int:
        pass

    @property
    def commit_index(self) -> int:
        pass

    @property
    def last_applied(self) -> int:
        pass

    @property
    def next_index(self, target) -> int:
        pass

    @property
    def match_index(self, target) -> int:
        pass

    async def __aenter__(self):
        self.db = await aiosqlite.connect(self.name)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.db.close()

    async def get_all(self):
        for record in await self.db.execute_fetchall("select * from Log;"):
            yield Entry(*record)

    async def add_entry(self, entry: Entry):
        insert_sql = """INSERT INTO Log values(?, ?, ?, ?, ?, ?, ?);"""

        cursor = await self.db.execute(
            insert_sql,
            parameters=(
                entry.index,
                entry.term,
                entry.command_name,
                entry.command,
                entry.voted_for,
                entry.commit_index,
                entry.last_applied
            )
        )
        await cursor.close()

    async def update_log(self, log, key):
        update_sql = """UPDATE TABLE Log SET ?=?;"""
        cursor = await self.db.execute(update_sql, (key, getattr(log, key)))
        await cursor.close()

    async def init_db(self):
        index: int
        term: int
        command_name: str
        bytes_command: str
        current_term: int
        voted_for: int
        commit_index: int
        last_applied: int
        log_table = """
        CREATE TABLE IF NOT EXISTS Log (
            id integer PRIMARY KEY,
            term integer NOT NULL,
            command_name varchar,
            command BLOB,
            voted_for integer,
            commit_index integer,
            last_applied integer
        );
        """

        cursor = await self.db.execute(log_table)
        await cursor.close()
