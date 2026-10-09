"""One cached gRPC channel per (process, address).

A channel is created on first use, never at import, so each gunicorn worker opens its own
after the fork. It is plaintext: the engine is reachable only on the private Docker network
`qt`. Every call on it carries the version header.

Options:
- keepalive pings every 5 min, and only while a call is in flight (the server's default
  minimum ping interval is 5 min, so this never trips its too-many-pings guard);
- reconnect backoff capped at 5 s, so a restarted engine is reachable again within seconds
  instead of gRPC's default 2 min.
"""

import os
import threading

import grpc

from algolens.infrastructure.rpc.version_header import VersionHeaderInterceptor

CHANNEL_OPTIONS = (
    ("grpc.keepalive_time_ms", 300_000),
    ("grpc.keepalive_timeout_ms", 20_000),
    ("grpc.keepalive_permit_without_calls", 0),
    ("grpc.initial_reconnect_backoff_ms", 1_000),
    ("grpc.max_reconnect_backoff_ms", 5_000),
)

_lock = threading.Lock()
_channels = {}


def get_channel(address):
    key = (os.getpid(), address)
    with _lock:
        channel = _channels.get(key)
        if channel is None:
            channel = grpc.intercept_channel(
                grpc.insecure_channel(address, options=CHANNEL_OPTIONS),
                VersionHeaderInterceptor(),
            )
            _channels[key] = channel
        return channel


def reset_channels():
    """Close every cached channel of this process (tests, shutdown)."""
    with _lock:
        channels = [c for (pid, _), c in _channels.items() if pid == os.getpid()]
        _channels.clear()
    for channel in channels:
        channel.close()
