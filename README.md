# Aioraft

Asynchronous Consensus Framework 

### Usage

```python
import aioraft


class Storage:
    disk = {}

    def put(self, key, value):
        self.disk[key] = value
    
    def get(self, key):
        return self.disk[key] 

config = {
    "peers": ["0.0.0.0:6543", "0.0.0.0:6544"]
}

consensus = aioraft.Cluster(config)
consensus.register(Storage)

```

