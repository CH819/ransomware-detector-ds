# ransomware-detector-ds

Distributed ransomware detection system that monitors files in real-time and coordinates recovery based on the risk detected.

### Prerequisites:
- Docker
- Docker Compose
- Python 3.12

Further details on requirements below.

### Structure of the project

Each service has its own folder, and the system as a whole is set-up and run through a docker compose. The main services include:

* `client`: monitoring of file activity + back-up service for saving and recovering snapshots.
* `gateway`: communication between client and application services.
* `detection_engine`: detection of ransomware attacks.
* `recovery_manager`: identification of clean snapshots after an attack is detected.
* `dashboard`: review of node status and management of recovery action.

The `scripts` folder contains miscellaneous scripts used to simulate ransomware attacks, decrypt files and process data for testing results.

The `utils` folder contains data and script for detection using machine learning models, but this feature is not yet fully implemented in the system.

## To run the system:

### Docker Compose

Rename the `.env.template` file as `.env` or copy it into a new file with name `.env`.

Build the images for each service. You can run and build everything with one command:

```
docker compose up -d --build
```

Or to build all images individually, you can also use the commands:

```
docker build -t monitoring_agent ./monitoring_agent
docker build -t detection_engine ./detection_engine
docker build -t recovery_manager ./recovery_manager
docker build -t client ./client
docker build -t gateway ./gateway
```

Then run

```
docker compose up
```

### Dashboard

After `dashboard` container is running, open `http://localhost:5173` in your browser.

If you don't have an account, sign up by clicking "Sign up" and using an email and password (for example name@gmail.com). If you already have an account, log in with your entered credentials. There is no email verification (yet).

After login, you will see a list of the nodes and their status: Healthy for clean nodes, Suspicious for nodes with suspicious activity, and Isolated for nodes considered to be high risk.

When a node is in Suspicious or Isolated state, recovery can be executed by clicking on the recovery button in the relevant node. For the nodes to get to this state, a test must be run, which will be described in the next section.

### Test

Test is run with the sample files in `client/template_node_files`. Each client node will have a copy of these files. Before running the test, wait for 10 seconds so at least a couple snapshots of the system are saved. You will also need to install the dependencies listed in the `requirements.txt` file as

```
pip install -r scripts/requirements.txt
```

To test the system, execute the following commands:

```
# If you run the project in Docker, you need to fix permissions for the nodes/ folder
sudo chown -R $USER:$USER ./nodes

python3 scripts/ransomware_simulator.py
```

This will encrypt the files the the nodes folder and trigger an Isolated state in all the nodes. You can then run recovery as described in the previous section, by clicking Recover in the dashboard. If recovery is successful, all files should be restored by the latest snapshot.

To decrypt encrypted files, run:

```
python3 scripts/decryptor.py
```
