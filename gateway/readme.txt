================================================================================
                    GATEWAY SERVICE - DETAILED DOCUMENTATION


ARCHITECTURE OVERVIEW
---------------------

The Gateway acts as the central message router, state manager, and coordinator 
in a distributed ransomware detection system. The Gateway makes all isolation 
and recovery decisions based on Detector analysis results.

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

COMMUNICATION FLOW DIAGRAM
--------------------------

STEP 0: GATEWAY LEADER ELECTION
┌─────────┐     Redis SET NX EX       ┌─────────┐
│Gateway A│ ─────────────────────────>│  Redis  │
│(startup)│  SET gateway:leader       │         │
│         │  gateway-A EX 10          │         │
│         │                           │         │
│  WINS!  │ ◄─────────────────────────│  OK     │
│(Active) │                           │         │
└─────────┘                           └────┬────┘
                                           │
┌─────────┐     Redis SET NX EX            │
│Gateway B│ ──────────────────────────────>│
│(startup)│  SET gateway:leader            │
│         │  gateway-B EX 10               │
│         │                                │
│  LOSES  │ ◄──────────────────────────────│
│(Passive)│  (key already exists)          │
│  Waits  │                                │
└─────────┘                                │
     │                                     │
     │         Key expires after 10s       │
     │ ◄───────────────────────────────────┘
     │
     ▼
┌─────────┐     Redis SET NX EX
│Gateway B│ ─────────────────────────> 
│(retry)  │  SET gateway:leader
│         │  gateway-B EX 10
│         │
│  WINS!  │ ◄─────────────────────────
│(Active) │  (becomes new leader)
└─────────┘


STEP 1: MONITOR → GATEWAY
┌─────────┐     file_info (Redis Stream)       ┌─────────┐
│ Monitor │ ─────────────────────────────────> │ Gateway │
│ (Client)│  {                                 │         │
│         │    node_id: "client-1",            │         │
│         │    file_path: "/doc.doc",          │         │
│         │    backup_version_id: "v3",   <--  │         │
│         │    entropy: 7.9                    │         │
│         │  }                                 │         │
└─────────┘                                    └────┬────┘
                                                    │
STEP 2: GATEWAY → DETECTOR                          │
┌─────────┐     detector_in (Redis Stream)          │
│ Gateway │ ────────────────────────────────────────┘
│         │  (forwards same data)
│         │  
└────┬────┘                                        
     │                                              
STEP 3: DETECTOR → GATEWAY                          │
┌─────────┐     detector_out (Redis Stream)         │
│Detector │ ────────────────────────────────────────┘
│         │  {
│         │    decision: "ISOLATE",          
│         │    infected_backup_id: "v3",      
│         │    risk_score: 8,
│         │    indicators: "high_entropy,suspicious_extension",
│         │    node_id: "client-1",
│         │    file_path: "/home/user/document.doc"
│         │  }
└────┬────┘  

STEP 4A: IF "ISOLATE" → STOP BACKUP SERVICE
┌─────────┐     backup_control (Redis Stream) ┌───────────┐
│ Gateway │ ─────────────────────────────────>│   Backup  │
│         │  {                                │  Service  │
│         │    command: "STOP_BACKUP",        │           │
│         │    node_id: "client-1"            │           │
│         │  }                                └───────────┘
└────┬────┘                                   
     │
STEP 4B: NOTIFY ADMIN (with infected_backup_id)
     │  ┌─────────┐  admin_alerts (Redis Stream)  ┌───────┐
     └─>│ Gateway │ ────────────────────────────> │ Admin │
        │         │ {                             │       │
        │         │   alert_type: "BACKUP_NEEDED, │       │
        │         │   threat_level: "HIGH",       │       │
        │         │   node_id: "client-1",        │       │
        │         │   file_path: "/doc.doc",      │       │
        │         │   risk_score: 8               │       │
        │         │ }                             └───────┘
        └─────────┘                                     
                                                         │
STEP 5: ADMIN INITIATES BACKUP                           │
┌───────┐     admin_commands (Redis Stream)      ┌─────────┐
│ Admin │ ──────────────────────────────────────>│ Gateway │
│       │  {                                     │         │
│       │    command: "INITIATE_BACKUP",         │         │
│       │    node_id: "client-1"                 │         │
│       │  }                                     └────┬────┘
└───────┘                                             │
                                                      │
STEP 6: GATEWAY → RECOVERY MANAGER                    │
┌─────────┐     recovery_requests (Redis Stream)      │
│ Gateway │ ──────────────────────────────────────────┘
│         │  {
│         │    command: "RECOVER",
│         │    node_id: "client-1",
│         │    timestamp: "2025-01-13T10:35:01Z"
│         │  }
│         │  
└─────────┘

STEP 7: RECOVERY MANAGER → GATEWAY
┌─────────┐     recovery_responses (Redis Stream)
│Recovery │ ─────────────────────────────────┐
│ Manager │  {                               │
│         │    node_id: "client-1",          │
│         │    backup_location: "s3://...",  │
│         │    files_to_restore: [...]       │
│         │  }                               │
└─────────┘                                  │
                                             ▼
STEP 8: GATEWAY → CLIENT
┌─────────┐     client_notify (Redis Stream)       ┌─────────┐
│ Gateway │ ──────────────────────────────────────>│ Client  │
│         │  {                                     │(Monitor)│
│         │    notification_type: "RECOVERY_INFO", │         │
│         │    node_id: "client-1",                │         │
│         │    backup_location: "s3://...",        │         │
│         │    files_to_restore: [...]             │         │
│         │  }                                     └─────────┘
└─────────┘
     │
     ▼
STEP 9: GATEWAY RESETS NODE TO HEALTHY
┌─────────┐
│ Gateway │  reset_node(node_id, "recovery_complete")
│         │  → Sets node_status to HEALTHY
│         │  → Clears node_backup_info
│         │  → Removes from pending_backups
└─────────┘

================================================================================

DETAILED COMMUNICATION DESCRIPTION
----------------------------------

1. MONITOR → GATEWAY (STREAM: file_info)
   ------------------------------------------------
   Source: Monitor service running on client machine
   Purpose: Send file system events for analysis
   Trigger: File created/modified on client
   
   Message Format:
   {
       "node_id": "client-1",
       "file_path": "/home/user/document.doc",
       "event_type": "FILE_MODIFIED",
       "entropy": 7.9,
       "process_name": "chrome",
       "timestamp": "2025-01-13T10:30:00Z",
       "backup_version_id": "v20250112-100000"
   }
   
   Gateway Action: 
   - Check node_status (drop if not HEALTHY)
   - Store in node_events (last 100 per node)
   - Forward to Detector via detector_in

2. GATEWAY → DETECTOR (STREAM: detector_in)
   ------------------------------------------------
   Source: Gateway (forwarded from Monitor)
   Destination: Detector service
   Purpose: Request file analysis
   
   Message Format: 
   {
       "timestamp": "2025-01-13T10:30:00Z",    // Gateway adds this
       "node_id": "client-1",
       "file_path": "/home/user/document.doc",
       "event_type": "FILE_MODIFIED",
       "entropy": 7.9,
       "process_name": "chrome",
       "backup_version_id": "v20250112-100000"
   }

3. DETECTOR → GATEWAY (STREAM: detector_out)
   ------------------------------------------------
   Source: Detector service after analysis
   Purpose: Report analysis results and identify infected backup
   
   Message Format:
   {
       "detector_id": "detector-1",
       "node_id": "client-1",
       "file_path": "/home/user/document.doc",
       "decision": "ISOLATE",                    // "ISOLATE", "BACKUP", or "SAFE"
       "risk_score": 8,
       "indicators": "high_entropy,suspicious_extension",
       "infected_backup_id": "v20250112-100000", 
       "timestamp": "2025-01-13T10:30:01Z"
   }
   
   Gateway Action: 
   - If node no longer HEALTHY (race condition): ignore result
   - If "ISOLATE": 
     * Set node_status to ISOLATED
     * Add to pending_backups
     * Send STOP_BACKUP to Backup Service
     * Send BACKUP_NEEDED alert to Admin
   - If "BACKUP":
     * Set node_status to SUSPICIOUS
     * Add to pending_backups
     * Send BACKUP_NEEDED alert to Admin
   - If "SAFE": no action (node remains HEALTHY)

4. GATEWAY → BACKUP SERVICE (STREAM: backup_control)
   ------------------------------------------------
   Source: Gateway (when ISOLATE decision received)
   Purpose: Stop backing up infected node to prevent backup contamination
   
   Message Format:
   {
       "command": "STOP_BACKUP",
       "node_id": "client-1",
       "timestamp": "2025-01-13T10:30:02Z"
   }
   
   Backup Service Action: Pause all backup operations for this node

5. GATEWAY → ADMIN (STREAM: admin_alerts)
   ------------------------------------------------
   Source: Gateway (when backup is needed)
   Purpose: Notify administrator that manual intervention required
   
   Message Format:
   {
       "alert_type": "BACKUP_NEEDED",
       "node_id": "client-1",
       "file_path": "/home/user/document.doc",
       "threat_level": "HIGH",                   // "HIGH" if ISOLATE, "MEDIUM" if BACKUP
       "risk_score": 8,
       "timestamp": "2025-01-13T10:30:02Z"
   }
   
   Admin Action: Review alert, log into system, send INITIATE_BACKUP command

6. ADMIN → GATEWAY (STREAM: admin_commands)
   ------------------------------------------------
   Source: Admin interface (web UI or CLI)
   Purpose: Trigger recovery process
   
   Message Format:
   {
       "command": "INITIATE_BACKUP",
       "node_id": "client-1",
       "timestamp": "2025-01-13T10:35:00Z"
   }
   
   Gateway Action: 
   - Verify node_id is in pending_backups
   - Retrieve infected_backup_id from node_backup_info
   - Set node_status to RECOVERING
   - Forward to Recovery Manager via recovery_requests

7. GATEWAY → RECOVERY MANAGER (STREAM: recovery_requests)
   ------------------------------------------------
   Source: Gateway (after admin initiates recovery)
   Purpose: Pass infected_backup_id to Recovery Manager
   
   Message Format:
   {
       "command": "RECOVER",
       "node_id": "client-1",
       "infected_backup_id": "v20250112-100000",  // <-- RETRIEVED FROM node_backup_info
       "timestamp": "2025-01-13T10:35:01Z"
   }
   
   Recovery Manager Action: 
   - Receives infected_backup_id "v20250112-100000" (the infected backup)
   - Looks up backup history
   - Decides to restore from backup BEFORE this one (e.g., "v20250111-100000")
   - Performs recovery
   - Responds via recovery_responses

8. RECOVERY MANAGER → GATEWAY (STREAM: recovery_responses)
   ------------------------------------------------
   Source: Recovery Manager after completing recovery
   Purpose: Report recovery status
   
   Message Format:
   {
       "node_id": "client-1",
       "backup_location": "s3://backups/client-1/v20250111-100000/",
       "files_to_restore": [
           "document.doc",
           "spreadsheet.xlsx"
       ],
       "timestamp": "2025-01-13T10:35:05Z"
   }
   
   Gateway Action: 
   - Forward to Client via client_notify
   - Reset node to HEALTHY (clear node_backup_info, pending_backups)

9. GATEWAY → CLIENT (STREAM: client_notify)
   ------------------------------------------------
   Source: Gateway (final step)
   Purpose: Deliver recovery completion to client
   
   Message Format:
   {
       "notification_type": "RECOVERY_INFO",
       "node_id": "client-1",
       "backup_location": "s3://backups/client-1/v20250111-100000/",
       "files_to_restore": [
           "document.doc",
           "spreadsheet.xlsx"
       ],
       "timestamp": "2025-01-13T10:35:06Z"
   }
   
   Client Action: Confirm recovery, resume normal operations

10. GATEWAY INTERNAL: RESET NODE
    ------------------------------------------------
    After sending recovery info to client, Gateway automatically resets node:
    
    - Set node_status[node_id] = NodeStatus.HEALTHY
    - Remove node_id from pending_backups
    - Delete node_backup_info[node_id]
    - Log: "Node {node_id} reset to HEALTHY (recovery_complete)"

================================================================================

GATEWAY INTERNAL STATE MANAGEMENT
---------------------------------

The Gateway maintains state in Redis for shared access across active-passive instances:

1. gateway:leader (string with TTL)
   - Value: "gateway-A" or "gateway-B"
   - Auto-expires after 10 seconds if not renewed
   
2. gateway:node_status (hash)
   - Key: node_id, Value: HEALTHY|SUSPICIOUS|ISOLATED|RECOVERING
   
3. gateway:pending_backups (set)
   - node_ids waiting for admin to initiate backup
   
4. gateway:node_backup_info (hash)
   - Key: node_id, Value: {"infected_backup_id": str}
   
5. gateway:events:{node_id} (list, trimmed to 100)
   - Last 100 events per node for debugging

Local cache (cleared on failover):
- _local_node_status_cache: temporary read cache
- _cache_lock: thread safety for cache access

================================================================================

GATEWAY STATE MACHINE
---------------------

Node Status Transitions:

                         ┌─────────────┐
            ┌─────────── │   HEALTHY   │◄────────────────────────┐
            │            └──────┬──────┘                         │
            │                   │ Monitor sends file             │
            │                   │ Gateway filters (is_healthy?)  │
            │                   ▼                                │
            │            ┌─────────────┐                         │
            │       ┌─── │  SUSPICIOUS │◄─────────────────────┐  │
            │       │    └──────┬──────┘                      │  │
            │       │           │ Detector says BACKUP        │  │
            │       │           ▼                             │  │
            │       │    ┌─────────────┐   Admin INITIATE     │  │
            │       └───►│   ISOLATED  │◄──BACKUP command─────┘  │
            │            └──────┬──────┘   (recovery starts)     │
            │                   │ Detector says ISOLATE          │
            │                   ▼                                │
            │            ┌─────────────┐                         │
            └───────────►│  RECOVERING │─────────────────────────┘
                         └──────┬──────┘   Recovery Manager responds
                                │
                                ▼
                         ┌─────────────┐
                         │   HEALTHY   │ (automatic reset after
                         │   (reset)   │  client notification)
                         └─────────────┘


================================================================================

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


