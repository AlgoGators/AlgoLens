"""The shared gRPC client layer: settings, cached channels, the version header, errors."""

import importlib.util
from concurrent import futures
from pathlib import Path

import grpc
import pytest
from google.protobuf import wrappers_pb2

from algogators.versions import API_VERSIONS
from algolens.infrastructure.rpc import (
    HEADER,
    describe_rpc_error,
    get_channel,
    header_value,
    is_version_mismatch,
    load_rpc_settings,
    reset_channels,
    status_name,
)
from algolens.infrastructure.rpc.channels import CHANNEL_OPTIONS

API_ROOT = Path(__file__).resolve().parents[1]


def test_address_prefers_engine_rpc_addr_then_desk_agent_addr():
    assert load_rpc_settings({}).engine_addr == "engine-rpc:50051"
    assert load_rpc_settings({"DESK_AGENT_ADDR": " desk-agent:50051 "}).engine_addr == (
        "desk-agent:50051"
    )
    both = {"ENGINE_RPC_ADDR": "engine-rpc:6000", "DESK_AGENT_ADDR": "desk-agent:50051"}
    assert load_rpc_settings(both).engine_addr == "engine-rpc:6000"


def test_timeout_default_and_override():
    assert load_rpc_settings({}).timeout_seconds == 3.0
    assert load_rpc_settings({"ENGINE_RPC_TIMEOUT_SECONDS": "1.5"}).timeout_seconds == 1.5
    assert load_rpc_settings({"ENGINE_RPC_TIMEOUT_SECONDS": "junk"}).timeout_seconds == 3.0
    assert load_rpc_settings({"ENGINE_RPC_TIMEOUT_SECONDS": "-1"}).timeout_seconds == 3.0


def test_header_value_lists_every_vendored_api():
    assert header_value({"desk": "1.2.3", "common": "1.0.0"}) == "common=1.0.0,desk=1.2.3"
    assert header_value() == ",".join(f"{a}={API_VERSIONS[a]}" for a in sorted(API_VERSIONS))


def test_versions_match_the_vendored_proto_headers():
    """algogators/versions.py is what the .proto headers say (CI also regenerates it)."""
    spec = importlib.util.spec_from_file_location(
        "gen_versions", API_ROOT / "scripts" / "gen_versions.py"
    )
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    protos = sorted((API_ROOT / "proto" / "algogators").glob("*.proto"))
    assert protos, "no vendored protos"
    assert dict(gen.parse(p) for p in protos) == API_VERSIONS


def test_one_cached_channel_per_address():
    try:
        a = get_channel("127.0.0.1:1")
        assert get_channel("127.0.0.1:1") is a
        assert get_channel("127.0.0.1:2") is not a
    finally:
        reset_channels()
    assert get_channel("127.0.0.1:1") is not a
    reset_channels()


def test_keepalive_is_sane():
    options = dict(CHANNEL_OPTIONS)
    # Never more often than the server's default minimum ping interval (5 min).
    assert options["grpc.keepalive_time_ms"] >= 300_000
    assert options["grpc.keepalive_permit_without_calls"] == 0
    assert options["grpc.max_reconnect_backoff_ms"] <= 10_000


def _echo_server(seen):
    def echo(request, context):
        seen.append(dict(context.invocation_metadata()).get(HEADER))
        if request.value == "refuse":
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, "API version mismatch")
        return request

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    server.add_generic_rpc_handlers(
        (
            grpc.method_handlers_generic_handler(
                "algogators.echo.EchoService",
                {
                    "Echo": grpc.unary_unary_rpc_method_handler(
                        echo,
                        request_deserializer=wrappers_pb2.StringValue.FromString,
                        response_serializer=wrappers_pb2.StringValue.SerializeToString,
                    )
                },
            ),
        )
    )
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    return server, f"127.0.0.1:{port}"


def test_every_call_carries_the_header_and_errors_map():
    seen = []
    server, address = _echo_server(seen)
    try:
        call = get_channel(address).unary_unary(
            "/algogators.echo.EchoService/Echo",
            request_serializer=wrappers_pb2.StringValue.SerializeToString,
            response_deserializer=wrappers_pb2.StringValue.FromString,
        )
        assert call(wrappers_pb2.StringValue(value="hi"), timeout=5).value == "hi"
        # A caller's own header for the same key is replaced, not duplicated.
        call(wrappers_pb2.StringValue(value="hi"), timeout=5, metadata=((HEADER, "desk=9.9.9"),))
        assert seen == [header_value(), header_value()]

        with pytest.raises(grpc.RpcError) as err:
            call(wrappers_pb2.StringValue(value="refuse"), timeout=5)
        assert status_name(err.value) == "FAILED_PRECONDITION"
        assert is_version_mismatch(err.value)
        assert describe_rpc_error(err.value) == "FAILED_PRECONDITION: API version mismatch"
    finally:
        server.stop(None)
        reset_channels()


def test_status_name_of_a_non_grpc_error():
    assert status_name(RuntimeError("x")) == "UNKNOWN"
