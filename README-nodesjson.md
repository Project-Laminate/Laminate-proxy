paste the following under `Laminate-proxy/data/storage/nodes.json`:

```
{
    "nodes": {
      "NAME": {
        "name": "name",
        "ip": "10.225.9.85",
        "port": 11116,
        "aet": "Paste-AET-Here",
        "enabled": true,
        "description": "description of node"
      }
    },
    "settings": {
      "polling_interval": 60,
      "max_retry_attempts": 3,
      "retry_delay": 5,
      "auto_forward_enabled": true
    }
  }
```

PS: make sure you create the required directory sturcure under the repository. 
