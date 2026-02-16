================================================================================
                    GATEWAY SERVICE - DETAILED DOCUMENTATION


ARCHITECTURE OVERVIEW
---------------------

The Gateway acts as the central message router, state manager, and coordinator 
in a distributed ransomware detection system. The Gateway makes all isolation 
and recovery decisions based on Detector analysis results.

Key Responsibilities:
- Filter: Drop events from nodes already being processed (SUSPICIOUS/ISOLATED/RECOVERING)
- Route: Forward healthy node events to Detector
- Decide: Set node status (HEALTHY → SUSPICIOUS/ISOLATED → RECOVERING → HEALTHY)
- Coordinate: Manage backup stop, admin alerts, and recovery workflows
- Store: Maintain infected_backup_id for recovery

================================================================================

COMMUNICATION FLOW DIAGRAM
--------------------------

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
│         │    decision: "ISOLATE",           // or "BACKUP" or "SAFE"
│         │    infected_backup_id: "v3",      // <-- BACKUP ID OF INFECTED FILE
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
        │         │   infected_backup_id: "v3",   │       │
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
│         │    infected_backup_id: "v3",      // <-- RETRIEVED FROM STORAGE
│         │    timestamp: "2025-01-13T10:35:01Z"
│         │  }
│         │  
│         │  NOTE: Gateway retrieves infected_backup_id from node_backup_info
│         │  and passes it to Recovery Manager. Recovery Manager decides 
│         │  which backup to restore from (e.g., the one before "v3").
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
       "infected_backup_id": "v20250112-100000", // <-- BACKUP ID OF INFECTED FILE
       "timestamp": "2025-01-13T10:30:01Z"
   }
   
   Gateway Action: 
   - If node no longer HEALTHY (race condition): ignore result
   - If "ISOLATE": 
     * Set node_status to ISOLATED
     * Store infected_backup_id in node_backup_info
     * Add to pending_backups
     * Send STOP_BACKUP to Backup Service
     * Send BACKUP_NEEDED alert to Admin
   - If "BACKUP":
     * Set node_status to SUSPICIOUS
     * Store infected_backup_id in node_backup_info
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
       "infected_backup_id": "v20250112-100000", // <-- FROM DETECTOR, STORED IN GATEWAY
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
    - Log: "🔄 Node {node_id} reset to HEALTHY (recovery_complete)"

================================================================================

GATEWAY INTERNAL STATE MANAGEMENT
---------------------------------

The Gateway maintains the following in-memory state (lost on restart):

1. node_status: Dict[str, NodeStatus]
   - Key: node_id
   - Value: HEALTHY | SUSPICIOUS | ISOLATED | RECOVERING
   
2. node_events: Dict[str, List[Dict]]
   - Key: node_id
   - Value: Last 100 events for debugging/audit
   
3. pending_backups: Set[str]
   - node_ids waiting for admin to initiate backup
   
4. node_backup_info: Dict[str, Dict]
   - Key: node_id
   - Value: {"infected_backup_id": str}
   - Purpose: Store backup_id when Detector reports ISOLATE/BACKUP
   - Retrieved when Admin initiates recovery
   - Cleared when node reset to HEALTHY

================================================================================

INFECTED_BACKUP_ID FLOW - GATEWAY AS STORAGE & PASS-THROUGH
-----------------------------------------------------------

The Gateway does NOT decide which backup to restore from. It only:
1. RECEIVES infected_backup_id from Detector
2. STORES it in node_backup_info[node_id]
3. PASSES it to Admin (for information)
4. RETRIEVES and PASSES it to Recovery Manager (when Admin confirms)

┌─────────┐    ┌─────────┐    ┌─────────────────┐    ┌─────────┐    ┌─────────┐
│ Monitor │───>│ Detector│───>│     Gateway     │───>│  Admin  │───>│ Gateway │
│         │    │         │    │                 │    │         │    │         │
│ backup  │    │infected_│    │infected_backup_ │    │infected_│    │infected_│
│  v3     │    │backup_id│    │id stored in:    │    │backup_id│    │backup_id│
│         │    │  v3     │    │node_backup_info │    │displayed│    │retrieved│
└─────────┘    └─────────┘    └─────────────────┘    └─────────┘    └────┬────┘
                                   │                                      │
                                   │  node_status: ISOLATED/SUSPICIOUS    │
                                   │  pending_backups: {node_id}          │
                                   │  node_backup_info: {node_id: {       │
                                   │    infected_backup_id: "v3"}}        │
                                   │                                      ▼
                                   │                            ┌─────────────┐
                                   │                            │   Recovery  │
                                   │                            │   Manager   │
                                   │                            │             │
                                   │                            │  Receives:  │
                                   │                            │infected_    │
                                   │                            │backup_id v3 │
                                   │                            │             │
                                   │                            │  Decides:   │
                                   │                            │  use v2     │
                                   │                            │  (before v3)│
                                   │                            └─────────────┘
                                   ▼
                            ┌─────────────┐
                            │  On reset:  │
                            │  - status:  │
                            │    HEALTHY  │
                            │  - pending: │
                            │    removed  │
                            │  - backup:  │
                            │    cleared  │
                            └─────────────┘

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

State Transition Table:

| From       | Event                    | To         | Action                          |
|------------|--------------------------|------------|---------------------------------|
| HEALTHY    | Detector: ISOLATE        | ISOLATED   | Stop backup, alert admin, store |
|            |                          |            | infected_backup_id              |
| HEALTHY    | Detector: BACKUP         | SUSPICIOUS | Alert admin, store              |
|            |                          |            | infected_backup_id              |
| HEALTHY    | Detector: SAFE           | HEALTHY    | No action                       |
| SUSPICIOUS | Admin: INITIATE_BACKUP   | RECOVERING | Forward to Recovery Manager     |
| ISOLATED   | Admin: INITIATE_BACKUP   | RECOVERING | Forward to Recovery Manager     |
| RECOVERING | Recovery: response       | HEALTHY    | Notify client, clear state      |
| *          | Monitor: file event      | *          | Drop if not HEALTHY             |

================================================================================

REDIS STREAMS SUMMARY
---------------------

Input Streams (Gateway receives):
- file_info: From Monitor (file event)
- detector_out: From Detector (analysis results + infected_backup_id)
- admin_commands: From Admin (initiate recovery)
- recovery_responses: From Recovery Manager (recovery status)

Output Streams (Gateway sends):
- detector_in: To Detector (file events)
- backup_control: To Backup Service (stop backup commands)
- admin_alerts: To Admin (backup needed + infected_backup_id)
- recovery_requests: To Recovery Manager (infected_backup_id)
- client_notify: To Client (recovery completion)

Consumer Groups (for horizontal scaling):
- gateway_detector_cg on detector_out
- gateway_admin_cg on admin_commands  
- gateway_recovery_cg on recovery_responses

================================================================================

SCALABILITY FEATURES
--------------------

1. CONSUMER GROUPS
   - Multiple Gateway instances can share Detector results
   - Multiple Gateway instances can share Admin commands
   - Multiple Gateway instances can share Recovery responses
   - Redis ensures each message processed exactly once

2. STATE IS IN-MEMORY
   - node_status, node_events, pending_backups, node_backup_info
   - Lost on Gateway restart (nodes revert to HEALTHY)
   - For production: persist to Redis or database

3. FILTERING AT GATEWAY
   - Events from non-HEALTHY nodes dropped immediately
   - Reduces load on Detector
   - Prevents duplicate processing

================================================================================

ERROR HANDLING
--------------

1. Race Condition: Detector result arrives after node already processed
   - Gateway checks is_node_healthy() before processing
   - If not healthy, logs warning and ignores result

2. Admin initiates backup but no infected_backup_id stored
   - node_backup_info.get() returns None
   - Recovery Manager receives null backup_id
   - Should validate and return error to Admin

3. Recovery Manager fails to respond
   - Node remains in RECOVERING state
   - Admin can send RESET command to force back to HEALTHY
   - Or implement timeout and retry logic

4. Gateway restarts
   - All node states lost (revert to HEALTHY)
   - pending_backups cleared
   - node_backup_info cleared
   - Admin may need to re-initiate pending recoveries

================================================================================

                    ┌─────────────┐
                    │   Monitor   │
                    │   (x N)     │
                    └──────┬──────┘
                           │
                           ▼
              ┌────────────────────────┐
              │  Stream: file_info     │
              └───────────┬────────────┘
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
        ┌─────────┐ ┌─────────┐ ┌─────────┐
        │Gateway 1│ │Gateway 2│ │Gateway 3│  ← Consumer group: gateway_cg
        │(active) │ │(active) │ │(active) │
        └────┬────┘ └────┬────┘ └────┬────┘
             └───────────┼───────────┘
                         ▼
              ┌────────────────────────┐
              │  Stream: detector_in   │
              └───────────┬────────────┘
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
        ┌─────────┐ ┌─────────┐ ┌─────────┐
        │Detector1│ │Detector2│ │Detector3│  ← Consumer group: detectors_cg
        │(active) │ │(active) │ │(active) │
        └────┬────┘ └────┬────┘ └────┬────┘
             └───────────┼───────────┘
                         ▼
              ┌────────────────────────┐
              │  Stream: detector_out  │
              └────────────────────────┘