import logging
import argparse

import aioraft

from aiohttp import web


logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.DEBUG
)


class Storage:
    disk = {}

    def put(self, key, value):
        self.disk[key] = value

    def get(self, key):
        return self.disk[key]



async def handle(request):
    data = await request.json()
    s = Storage()
    s.put("new", data)
    return web.Response()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Raft node arguments')

    parser.add_argument('addr', metavar='addr', type=str, help='node addr')
    parser.add_argument('peers', metavar='peers', type=str, nargs='+', help='peers')
    parser.add_argument('port', metavar='port', type=int, help='server port')

    args = parser.parse_args()
    
    config = aioraft.Config(
        addr=str(args.addr),  # [::]:50051
        peers=args.peers
    )
    consensus = aioraft.Cluster(config)
    consensus.register(Storage)
    consensus.start()

    
    app = web.Application()
    app.add_routes([web.post('/', handle),])
    web.run_app(app, port=args.port)
