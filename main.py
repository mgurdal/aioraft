import asyncio
import logging

from aioraft.network import Server

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.DEBUG
)

if __name__ == "__main__":
    config = {}
    servers = [Server(id=f"0.0.0.0:{port}") for port in range(5432, 5470)]

    for idx, server in enumerate(servers):
        peers = servers[:idx] + servers[idx + 1 :]
        server.add_peer(*peers)

    for server in servers:
        server.start()

    l = asyncio.get_event_loop()
    l.run_forever()
