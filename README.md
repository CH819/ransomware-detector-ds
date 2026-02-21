# ransomware-detector-ds

To run Docker Compose:

- Build the images for each service. You can use the commands:

```
docker build -t monitoring_agent ./monitoring_agent
docker build -t detection_engine ./detection_engine
docker build -t recovery_manager ./recovery_manager
docker build -t client ./client
docker build -t gateway ./gateway
```

- Then run

```
docker compose up
```

Or you can also run and build everything with one command:

```
docker compose up -d --build
```

Test is run with the sample files in `client/template_node_files`.
