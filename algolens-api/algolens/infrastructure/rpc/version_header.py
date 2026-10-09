"""The x-algogators-api-version header, added to every call by a client interceptor.

The value lists every API AlgoLens vendors, e.g. "common=1.0.0,desk=1.0.0". The versions come
from algogators/versions.py, which scripts/gen_proto.sh generates from the "Version:" line of
each vendored .proto, so they cannot drift from the contract. The engine refuses a call whose
major version differs from its own (FAILED_PRECONDITION) and accepts any minor/patch.
"""

import collections

import grpc

HEADER = "x-algogators-api-version"


def header_value(versions=None):
    if versions is None:
        from algogators.versions import API_VERSIONS

        versions = API_VERSIONS
    return ",".join(f"{api}={versions[api]}" for api in sorted(versions))


class _CallDetails(
    collections.namedtuple(
        "_CallDetails",
        ("method", "timeout", "metadata", "credentials", "wait_for_ready", "compression"),
    ),
    grpc.ClientCallDetails,
):
    pass


class VersionHeaderInterceptor(
    grpc.UnaryUnaryClientInterceptor,
    grpc.UnaryStreamClientInterceptor,
    grpc.StreamUnaryClientInterceptor,
    grpc.StreamStreamClientInterceptor,
):
    def __init__(self, value=None):
        self.value = value if value is not None else header_value()

    def _details(self, details):
        metadata = [(k, v) for k, v in (details.metadata or ()) if k != HEADER]
        metadata.append((HEADER, self.value))
        return _CallDetails(
            details.method,
            details.timeout,
            metadata,
            details.credentials,
            getattr(details, "wait_for_ready", None),
            getattr(details, "compression", None),
        )

    def intercept_unary_unary(self, continuation, details, request):
        return continuation(self._details(details), request)

    def intercept_unary_stream(self, continuation, details, request):
        return continuation(self._details(details), request)

    def intercept_stream_unary(self, continuation, details, request_iterator):
        return continuation(self._details(details), request_iterator)

    def intercept_stream_stream(self, continuation, details, request_iterator):
        return continuation(self._details(details), request_iterator)
