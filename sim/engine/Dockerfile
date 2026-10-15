# The trade-ngin image (engine-rpc entrypoint) with libfaketime added, so the gRPC server, the
# catch-up scheduler and every engine run it spawns (flock + the C++ binary) read the sim clock.
#
# libfaketime is built from source: Ubuntu 24.04's package (0.9.10-2.1) fails Python's
# time.sleep() with EINVAL under a clock offset (its clock_nanosleep shifts absolute monotonic
# deadlines), which kills every engine run the desk service starts. The commit below is the one
# Debian trixie packages (0.9.10+2024-06-05+gba9ed5b2), which postgres and the backend use.
#
# /app/config is built here from the image's own config_template (so portfolio.json and
# risk.json always match the engine version), with the database block pointed at the sim
# postgres and every portfolio's email.json pointed at Mailpit (sim_config.py).
ARG ENGINE_IMAGE=trade-ngin:sim

FROM ubuntu:24.04 AS libfaketime
ARG LIBFAKETIME_COMMIT=ba9ed5b2
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates gcc git libc6-dev make \
 && git clone https://github.com/wolfcw/libfaketime.git /src \
 && cd /src && git checkout "$LIBFAKETIME_COMMIT" \
 && make -C src libfaketime.so.1 \
 && install -D -m 0644 src/libfaketime.so.1 /out/libfaketime.so.1

FROM ${ENGINE_IMAGE}
COPY --from=libfaketime /out/libfaketime.so.1 /usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1
COPY sim_config.py /tmp/sim_config.py
RUN rm -rf /app/config && cp -r /app/config_template /app/config \
 && python3 /tmp/sim_config.py /app/config && rm /tmp/sim_config.py
