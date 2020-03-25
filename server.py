import asyncio

from aioraft import Server

if __name__ == '__main__':
    config = {}
    server1 = Server(addr="0.0.0.0:5432")
    server2 = Server(addr="0.0.0.0:5433")
    server3 = Server(addr="0.0.0.0:5434")

    server1.add_peer(server2, server3)
    server2.add_peer(server1, server3)
    server3.add_peer(server1, server2)

    server1.start()
    server2.start()
    server3.start()

    l = asyncio.get_event_loop()
    l.run_forever()
