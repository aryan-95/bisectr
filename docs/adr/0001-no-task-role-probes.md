# ADR 1: Probe tasks have no task role

PR code runs inside the app container and is untrusted. With no task role it has no AWS
credentials, so it cannot forge results. The runner prints one JSON line to its own log
stream and the CLI reads it.

Cost: results travel through CloudWatch Logs rather than being written directly to DynamoDB.
