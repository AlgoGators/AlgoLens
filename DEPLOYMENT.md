# AlgoLens Deployment Guide

AlgoLens deploys as Docker containers to the trade-ngin box on a push to `prod`. The old EC2 host
only terminates TLS and proxies to it.

See [deployment/DEPLOYMENT.md](deployment/DEPLOYMENT.md) for the topology,
host bootstrap, cutover and rollback.
