================================================================================
                    GATEWAY SERVICE - DETAILED DOCUMENTATION


ARCHITECTURE OVERVIEW
---------------------

Central coordinator for distributed ransomware detection with active-passive leader election.

Key Responsibilities:
- Elect: Active-passive leader election via Redis SET NX EX
- Filter: Drop events from nodes already being processed (only active gateway processes)
- Route: Forward healthy node events to Detector
- Decide: Set node status in Redis (shared state)
- Coordinate: Manage backup stop, admin alerts, and recovery workflows
- Failover: Automatic takeover within 10 seconds if active gateway fails

================================================================================
LEADER ELECTION MECHANISM
-------------------------

Redis SET NX EX Command:
- SET: Create or update a key
- NX (Not eXists): Only succeed if key doesn't exist
- EX (EXpire): Auto-delete key after N seconds

Gateway Implementation:
┌─────────────────────────────────────────────────────────┐
│  Startup                                                │
│    └─> Try SET gateway:leader <my_id> NX EX 10          │
│         ├─> Success: Become ACTIVE, start renew loop    │
│         └─> Fail: Become PASSIVE, start watch loop      │
│                                                         │
│  ACTIVE Loop (every 3s):                                │
│    ├─> Check if still leader (GET gateway:leader)       │
│    ├─> If yes: EXPIRE gateway:leader 10 (renew)         │
│    └─> If no: Transition to PASSIVE                     │
│                                                         │
│  PASSIVE Loop (every 3s):                               │
│    ├─> Try SET gateway:leader <my_id> NX EX 10          │
│    ├─> If success: Transition to ACTIVE                 │
│    └─> If fail: Remain PASSIVE                          │
│                                                         │
│  Shutdown:                                              │
│    └─> If ACTIVE: DEL gateway:leader (voluntary)        │
└─────────────────────────────────────────────────────────┘

Failover Scenarios:
1. Graceful shutdown: Active deletes key, passive takes over immediately
2. Crash: Key expires after 10s, passive takes over
3. Network partition: Split-brain prevented by Redis atomicity
================================================================================

COMMUNICATION FLOW 
--------------------------

  Direction                  | Method                        | Purpose                         |
| -------------------------- | ----------------------------- | ------------------------------- |
| Monitor → Gateway          | Redis Stream `file_info`      | File events                     |
| Gateway → Detector         | Redis Stream `detector_in`    | Analysis requests               |
| Detector → Gateway         | Redis Stream `detector_out`   | Decisions (ISOLATE/BACKUP/SAFE) |
| Gateway → Client           | HTTP POST `:7000/isolate`     | Isolate infected node           |
| Gateway → Admin            | Redis Stream `admin_alerts`   | Threat notifications            |
| Admin → Gateway            | Redis Stream `admin_commands` | Recovery triggers               |
| Gateway → Recovery Manager | HTTP POST `:6000/recover`     | Initiate recovery               |
| Gateway → Client           | HTTP POST `:7000/restore`     | Restore clean snapshot          |
| Monitor → Gateway          | Redis Stream `ping`           | Heartbeats                      |

================================================================================

STATE MANAGEMENT (Redis)

| Key                           | Type             | Description                                          |
| ----------------------------- | ---------------- | ---------------------------------------------------- |
| `gateway:leader`              | String (TTL 10s) | Active gateway ID                                    |
| `gateway:node_status`         | Hash             | node\_id → HEALTHY\|SUSPICIOUS\|ISOLATED\|RECOVERING |
| `gateway:pending_backups`     | Set              | Nodes awaiting recovery                              |
| `gateway:infection_timestamp` | Hash             | node\_id → infection time                            |
| `gateway:events:{node_id}`    | List (trimmed)   | Last 100 events per node                             |
| `gateway:status_history`      | Stream           | Status change audit log                              |

================================================================================

DECISION HANDLING
-----------------

| Detector Decision | Gateway Action                                              |
|-------------------|-------------------------------------------------------------|
| ISOLATE           | Set ISOLATED, HTTP POST isolate to client, alert admin HIGH |
| BACKUP            | Set SUSPICIOUS, alert admin MEDIUM                          |
| SAFE              | No action (node remains HEALTHY)                            |

==================================================================================

Node STATE MACHINE
---------------------

Node Status Transitions:

                         ┌─────────────┐
            ┌─────────── │   HEALTHY   │◄────────────────────────┐
            │            └──────┬──────┘                         │
            │                   │                                │
            │    ┌──────────────┼──────────────┐                 │
            │    │              │              │                 │
            │    ▼              ▼              │                 │
            │ ┌────────┐   ┌──────────┐        │                 │
            │ │BACKUP  │   │ ISOLATE  │        │                 │
            │ │(Susp.) │   │(Isolate) │        │                 │
            │ └───┬────┘   └────┬─────┘        │                 │
            │     │             │              │                 │
            │     ▼             ▼              │                 │
            │ ┌──────────┐ ┌──────────┐        │                 │
            └►│SUSPICIOUS│ │ ISOLATED │        │                 │
              └───┬──────┘ └────┬─────┘        │                 │
                  │             │              │                 │
                  │   Admin: INITIATE_BACKUP   │                 │
                  │             │              │                 │
                  │             ▼              │                 │
                  │      ┌──────────┐          │                 │
                  └─────►│RECOVERING│──────────┘                 │
                         └──────────┘   (auto reset after restore)


Transitions:
- HEALTHY → SUSPICIOUS: Detector returns BACKUP
- HEALTHY → ISOLATED: Detector returns ISOLATE  
- ISOLATED → RECOVERING: Admin sends INITIATE_BACKUP
- RECOVERING → HEALTHY: Recovery complete (auto)
- SUSPICIOUS → RECOVERING: Admin sends INITIATE_BACKUP
================================================================================

RECOVERY FLOW
-------------

1. Admin sends INITIATE_BACKUP via admin_commands stream
2. Gateway verifies node is in pending_backups set
3. Gateway sets node status to RECOVERING
4. Gateway HTTP POST to Recovery Manager (:6000/recover)
   - Sends node_id and infection_timestamp
5. Recovery Manager returns clean snapshot_id
6. Gateway HTTP POST to Client (:7000/restore)
   - Sends node_id and snapshot_id
7. Gateway resets node to HEALTHY
   - Clears pending_backups, infection_timestamp
   - Logs recovery completion

SCALABILITY FEATURES
--------------------

1. ACTIVE-PASSIVE LEADER ELECTION
   - Only one gateway processes events at any time
   - Passive gateway monitors leader key and auto-failover
   - 10-second max downtime during failover
   - Leader renews lock every 3 seconds

2. REDIS-BACKED STATE
   - All node states persisted in Redis (survives gateway restart)
   - Shared access between active and passive instances
   - Atomic operations ensure consistency

3. CONSUMER GROUPS (within active gateway)
   - Multiple threads can share Detector results
   - Multiple threads can share Admin commands
   - Redis ensures each message processed exactly once

4. FILTERING AT GATEWAY
   - Only active gateway processes events
   - Events from non-HEALTHY nodes dropped immediately
   - Reduces load on Detector
   - Prevents duplicate processing


