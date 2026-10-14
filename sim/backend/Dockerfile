# The AlgoLens backend image built from the checked-out branch (algolens-api/Dockerfile, tagged
# algolens-sim/backend-base:local by `simctl build`), with libfaketime added for the sim clock.
ARG BASE_IMAGE=algolens-sim/backend-base:local
FROM ${BASE_IMAGE}
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends libfaketime \
 && rm -rf /var/lib/apt/lists/* \
 && ls -l /usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1
USER appuser
