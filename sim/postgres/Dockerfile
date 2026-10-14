# postgres with libfaketime: every process reads the sim clock (sim/clock/faketime.rc).
ARG PG_IMAGE=postgres:16
FROM ${PG_IMAGE}
RUN apt-get update \
 && apt-get install -y --no-install-recommends libfaketime \
 && rm -rf /var/lib/apt/lists/* \
 && ls -l /usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1
