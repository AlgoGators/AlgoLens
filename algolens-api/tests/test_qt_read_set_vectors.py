"""Literal A3 vectors shared byte-for-byte with the native desk validator."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import pytest
from algolens.infrastructure.portfolio.qt_read_set import canonical_internal_snapshot_bytes

VECTORS=Path(__file__).resolve().parents[2]/'contracts/qt-read-set-v1.json'


def test_literal_full_read_set_vectors_and_order_independence():
    for case in json.loads(VECTORS.read_text(encoding='utf-8'))['cases']:
        payload=case['payload']
        wire=canonical_internal_snapshot_bytes('qt-read-set/v1',payload)
        assert wire.decode() == case['canonical_utf8']
        assert len(wire) == case['byte_count']
        assert sha256(wire).hexdigest() == case['sha256']
        for value in payload.values():
            if isinstance(value,list): value.reverse()
        assert canonical_internal_snapshot_bytes('qt-read-set/v1',payload) == wire
        payload['saved_rows'][0]['quantity_exact']='7'
        assert canonical_internal_snapshot_bytes('qt-read-set/v1',payload) != wire
