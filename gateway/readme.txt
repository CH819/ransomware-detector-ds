================================================================================
                    GATEWAY SERVICE - DETAILED DOCUMENTATION


ARCHITECTURE OVERVIEW
---------------------

The Gateway acts as the central message router and coordinator in a distributed
ransomware detection system. This Gateway does not make isolation decisions it only routes messages and coordinates workflows 
based on Detector analysis results.

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
┌─────────┐     file_info (Redis Stream)            │
│ Gateway │ ────────────────────────────────────────┘
│         │  (forwards same data including backup_version_id)
└────┬────┘                                        
     │                                              
STEP 3: DETECTOR → GATEWAY                          │
┌─────────┐     analysis_result (Redis Stream)      │
│Detector │ ────────────────────────────────────────┘
│         │  {
│         │    decision: "ISOLATE",
│         │    backup_id: "v3",           <-- BACKUP ID OF INFECTED FILE
│         │    risk_score: 8,
│         │    indicators: "..."
|────┬────┘  }

STEP 4A: IF "ISOLATE" → STOP BACKUP SERVICE
┌─────────┐     stop_backup (Redis Stream)    ┌───────────┐
│ Gateway │ ─────────────────────────────────>│   Backup  │
│         │                                   │  Service  │
└────┬────┘                                   └───────────┘
     │
STEP 4B: NOTIFY ADMIN (with backup_id)
     │  ┌─────────┐  admin_alert (Redis Stream)  ┌───────┐
     └─>│ Gateway │ ───────────────────────────> │ Admin │
        │         │ {                            │       │
        │         │   alert_type: "BACKUP_NEEDED",       │
        │         │   backup_id: "v3",           │       │
        │         │   message: "..."             │       │
        │         │ }                            └───────┘
        └─────────┘                                     │
                                                        │
STEP 5: ADMIN INITIATES BACKUP                          │
┌───────┐     "INITIATE_BACKUP" (Redis Stream)  ┌─────────┐
│ Admin │ ─────────────────────────────────────>│ Gateway │
│       │                                       │         │
└───────┘                                       └────┬────┘
                                                     │
STEP 6: GATEWAY → RECOVERY MANAGER                   │
┌─────────┐     recovery_request (Redis Stream)      │
│ Gateway │ ───────────────────────────────────────-─┘
│         │  {
│         │    command: "RECOVER",
│         │    backup_id: "v3",           <-- PASS THROUGH BACKUP ID
│         │    node_id: "client-1"
│         │  }
│         │  
│         │  NOTE: Recovery Manager decides which backup to use
│         │  (e.g., the one before backup_id "v3")
└─────────┘

STEP 7: RECOVERY MANAGER → GATEWAY
┌─────────┐     recovery_response (Redis Stream)
│Recovery │ ─────────────────────────────────┐
│ Manager │  {                               │
│         │    status: "SUCCESS",            │
│         │    restored_from_backup: "v2",   │
│         │    restored_files: [...]         │
│         │  }                               │
└─────────┘                                  │
                                             ▼
STEP 8: GATEWAY → CLIENT
┌─────────┐     recovery_info (Redis Stream)       ┌─────────┐
│ Gateway │ ──────────────────────────────────────>│ Client  │
│         │  {                                     │(Monitor)│
│         │    notification_type: "RECOVERY_INFO", │         │
│         │    restored_from_backup: "v2"          │         │
│         │  }                                     └─────────┘
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
   
   Gateway Action: Store event in local history, forward to Detector

2. BACKUP SERVICE → GATEWAY (STREAM: backup_data)
   ------------------------------------------------
   Source: Backup Service (continuously running backups)
   Purpose: Inform Gateway about available backups
   Trigger: Backup job completes
   
   Message Format:
   {
       "node_id": "client-1",
       "backup_id": "v20250112-100000",
       "timestamp": "2025-01-13T10:30:00Z",
       "file_count": 150,
       "size_bytes": 1073741824,
       "location": "s3://backups/client-1/v20250112-100000/"
   }
   
   Gateway Action: Store backup metadata (not used for decisions, just logging)

3. GATEWAY → DETECTOR (STREAM: detector_in)
   ------------------------------------------------
   Source: Gateway (forwarded from Monitor)
   Destination: Detector service
   Purpose: Request file analysis
   
   Message Format: (Same as file_info from Monitor, with Gateway timestamp added)

4. DETECTOR → GATEWAY (STREAM: detector_out)
   ------------------------------------------------
   Source: Detector service after analysis
   Purpose: Report analysis results and identify infected backup
   
   Message Format:
   {
       "detector_id": "detector-1",
       "node_id": "client-1",
       "file_path": "/home/user/document.doc",
       "decision": "ISOLATE",              // "ISOLATE" or "BACKUP"
       "risk_score": 8,
       "indicators": ["high_entropy", "suspicious_extension"],
       "backup_id": "v20250112-100000",    // <-- BACKUP ID OF INFECTED FILE
       "timestamp": "2025-01-13T10:30:01Z"
   }
   
   Gateway Action: 
   - Store backup_id temporarily
   - If "ISOLATE": 
     * Set node status to ISOLATED
     * Send stop_backup to Backup Service
     * Send BACKUP_NEEDED alert to Admin (include backup_id)
   - If "BACKUP":
     * Set node status to SUSPICIOUS
     * Send BACKUP_NEEDED alert to Admin (include backup_id)

5. GATEWAY → BACKUP SERVICE (STREAM: backup_control)
   ------------------------------------------------
   Source: Gateway (when ISOLATE decision received)
   Purpose: Stop backing up infected node to prevent backup contamination
   
   Message Format:
   {
       "command": "STOP_BACKUP",
       "node_id": "client-1",
       "reason": "infection_detected",
       "timestamp": "2025-01-13T10:30:02Z"
   }
   
   Backup Service Action: Pause all backup operations for this node

6. GATEWAY → ADMIN (STREAM: admin_alerts)
   ------------------------------------------------
   Source: Gateway (when backup is needed)
   Purpose: Notify administrator that manual intervention required
   
   Message Format:
   {
       "alert_type": "BACKUP_NEEDED",
       "node_id": "client-1",
       "file_path": "/home/user/document.doc",
       "threat_level": "HIGH",              // HIGH if ISOLATE, MEDIUM if BACKUP
       "risk_score": 8,
       "indicators": ["high_entropy", "suspicious_extension"],
       "backup_id": "v20250112-100000",     // <-- PASS THROUGH FROM DETECTOR
       "message": "Node client-1 requires backup. File: /home/user/document.doc, Backup: v20250112-100000",
       "timestamp": "2025-01-13T10:30:02Z",
       "action_required": "INITIATE_BACKUP"
   }
   
   Admin Action: Review alert, log into system, send INITIATE_BACKUP command

7. ADMIN → GATEWAY (STREAM: admin_commands)
   ------------------------------------------------
   Source: Admin interface (web UI or CLI)
   Purpose: Trigger recovery process
   
   Message Format:
   {
       "command": "INITIATE_BACKUP",
       "node_id": "client-1",
       "admin_id": "admin-1",
       "timestamp": "2025-01-13T10:35:00Z"
   }
   
   Gateway Action: Retrieve stored backup_id, forward to Recovery Manager

8. GATEWAY → RECOVERY MANAGER (STREAM: recovery_requests)
   ------------------------------------------------
   Source: Gateway (after admin initiates recovery)
   Purpose: Pass backup_id to Recovery Manager
   
   Message Format:
   {
       "command": "RECOVER",
       "node_id": "client-1",
       "backup_id": "v20250112-100000",     // (Gateway makes no decision)
       "timestamp": "2025-01-13T10:35:01Z"
   }
   
   Recovery Manager Action: 
   - Receives backup_id "v20250112-100000" (the infected backup)
   - Looks up backup history
   - Decides to restore from backup BEFORE this one (e.g., "v20250111-100000")
   - Performs recovery

9. RECOVERY MANAGER → GATEWAY (STREAM: recovery_responses)
   ------------------------------------------------
   Source: Recovery Manager after completing recovery
   Purpose: Report recovery status
   
   Message Format:
   {
       "node_id": "client-1",
       "status": "SUCCESS",
       "restored_from_backup": "v20250111-100000",  // Recovery Manager's decision
       "files_to_restore": [
           "document.doc",
           "spreadsheet.xlsx"
       ],
       "total_size": 52428800,
       "timestamp": "2025-01-13T10:35:05Z"
   }
   
   Gateway Action: Forward to Client

10. GATEWAY → CLIENT (STREAM: client_notify)
    ------------------------------------------------
    Source: Gateway (final step)
    Purpose: Deliver recovery completion to client
    
    Message Format:
    {
        "notification_type": "RECOVERY_COMPLETE",
        "node_id": "client-1",
        "status": "SUCCESS",
        "restored_from_backup": "v20250111-100000",
        "files_to_restore": [
            "document.doc",
            "spreadsheet.xlsx"
        ],
        "timestamp": "2025-01-13T10:35:06Z",
        "message": "Recovery completed for node client-1"
    }
    
    Client Action: Confirm recovery, resume normal operations

================================================================================

BACKUP ID FLOW - GATEWAY AS PASS-THROUGH
----------------------------------------

The Gateway does NOT make any decisions about which backup to use. It simply
passes the backup_id through the system:

┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
│ Monitor │───>│ Detector│───>│ Gateway │───>│  Admin  │───>│ Gateway │
│         │    │         │    │         │    │         │    │         │
│ backup  │    │ backup  │    │ backup  │    │ backup  │    │ backup  │
│  v3     │    │  v3     │    │  v3     │    │  v3     │    │  v3     │
└─────────┘    └─────────┘    └─────────┘    └─────────┘    └────┬────┘
                                                                  │
                                                                  ▼
                                                           ┌─────────────┐
                                                           │   Recovery  │
                                                           │   Manager   │
                                                           │             │
                                                           │  Receives:  │
                                                           │  backup v3  │
                                                           │             │
                                                           │  Decides:   │
                                                           │  use v2     │
                                                           │  (before v3)│
                                                           └─────────────┘

Gateway Responsibilities:
- RECEIVE backup_id from Detector
- STORE backup_id temporarily (until Admin initiates recovery)
- PASS backup_id to Admin (for information)
- PASS backup_id to Recovery Manager (when Admin confirms)

Gateway does NOT:
- Look up backup history
- Decide which backup to restore from
- Calculate "backup before" infected one
- Make any backup-related decisions

================================================================================

GATEWAY STATE MACHINE
---------------------

Node Status Transitions:

                   ┌─────────────┐
         ┌─────────│   HEALTHY   │◄─────────────────┐
         │         └──────┬──────┘                  │
         │                │ Monitor sends file      │
         │                │ event                   │
         │                ▼                         │
         │         ┌─────────────┐                  │
         │    ┌─── │  SUSPICIOUS │◄───────────── ┐  │
         │    │    └──────┬──────┘               │  │
         │    │           │ Detector says BACKUP │  │
         │    │           ▼                      │  │
         │    │    ┌─────────────┐   Admin       │  │
         │    └───►│   ISOLATED  │◄──initiates───┘  │
         │         └──────┬──────┘   backup         │
         │                │ Detector says ISOLATE   │
         │                ▼                         │
         │         ┌─────────────┐                  │
         └────────►│  RECOVERING │──────────────────┘
                   └─────────────┘   Recovery complete

================================================================================

REDIS STREAMS SUMMARY
---------------------

Input Streams (Gateway receives):
- file_info: From Monitor (file event)
- backup_data: From Backup Service (backup metadata for logging)
- detector_out: From Detector (analysis results + backup_id)
- admin_commands: From Admin (initiate recovery)
- recovery_responses: From Recovery Manager (recovery status)

Output Streams (Gateway sends):
- detector_in: To Detector (file events)
- backup_control: To Backup Service (stop backup commands)
- admin_alerts: To Admin (backup needed + backup_id)
- recovery_requests: To Recovery Manager (backup_id only)
- client_notify: To Client (recovery completion)

================================================================================

SCALABILITY FEATURES
--------------------

1. CONSUMER GROUPS
   - detector_out: Multiple Gateway instances share Detector results
   - admin_commands: Multiple Gateway instances share Admin commands
   - recovery_responses: Multiple Gateway instances share Recovery responses

2. STATE PERSISTENCE
   - node_status: Stored in Redis Hash for persistence
   - backup_id: Stored temporarily in local memory (node_backup_info)
   - pending_backups: Stored in local memory

3. HORIZONTAL SCALING
   - Multiple Gateway instances can run simultaneously
   - Consumer groups ensure no message is processed twice
   - Redis acts as central coordinator

================================================================================

ERROR HANDLING
--------------

1. Missing backup_id from Detector
   - Log error
   - Alert Admin that backup ID is missing
   - Cannot proceed with recovery

2. Admin initiates recovery but no backup_id stored
   - Return error: "no_backup_id"
   - Request Detector to re-analyze

3. Recovery Manager Failure
   - If recovery_responses not received:
   - Gateway retries request to Recovery Manager
   - After 3 retries, alerts Admin of recovery failure
