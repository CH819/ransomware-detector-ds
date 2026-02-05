# ransomware-detector-ds

To run docker-compose:

* Build the images for each service. You can use the commands:

```
cd monitoring_agent
docker build . -t monitoring_agent

cd ../detection_engine
docker build . -t detection_engine

cd ../recovery_manager
docker build . -t monitoring_agent
```

* Then run

```
docker-compose up
```

Test is run with the sample files in `utils/test_files`.
