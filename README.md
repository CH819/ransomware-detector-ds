# ransomware-detector-ds

Prerequisites:
- Docker
- Docker Compose
- Python 3.12

### Docker Compose

Rename the .env.template file as .env or copy it into a new file.

Build the images for each service. You can use the commands:

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

Or you can also run and build everything with one command:

```
docker compose up -d --build
```

### Dashboard

After `dashboard` container is running, open `http://localhost:5173` in your browser.

Sign up admin user and login with your entered credentials. There is no email verification (yet).

Run test scripts and click recovery button in the table.

### Test

Test is run with the sample files in `client/template_node_files`.

```
# If you run the project in Docker, you need to fix permissions for the nodes/ folder
sudo chown -R $USER:$USER ./nodes

python3 scripts/ransomware_simulator.py
```

To decrypt encrypted files, run:

```
python3 scripts/decryptor.py
```
