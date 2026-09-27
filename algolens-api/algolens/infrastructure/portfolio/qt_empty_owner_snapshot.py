"""Staged v2 physical-snapshot seam, never a v1/readiness fallback.

The SQL loader must independently prove immutable publication/runtime authority
and audit/origin continuity before this seam. This result retains its v2 tag and
contains no availability/certification flag or fabricated system seed.
"""
from algolens.infrastructure.portfolio.qt_empty_owner_protocol import _need,validate_empty_model_owner_document
from algolens.infrastructure.portfolio.qt_empty_owner_producer import configuration_digest,configured_members

def resolve_empty_model_owner_snapshot(document, configuration_snapshot,
        system_rows, proposal_rows, qt_rows):
    doc=validate_empty_model_owner_document(document)
    _need(doc['configuration_digest']==configuration_digest(configuration_snapshot))
    _need(doc['configured_owner_names']==configured_members(configuration_snapshot))
    _need(type(system_rows) is list and system_rows==[])
    _need(type(proposal_rows) is list and type(qt_rows) is list)
    # Proposal physical rows carry the revision token, while action/origin belong
    # to the immutable manifest and are proved separately by the existing chain.
    expected=[{name:row[name] for name in ('key','quantity_exact','average_price_exact','position_revision')}
        for row in doc['proposal_components']]
    _need(proposal_rows==expected and qt_rows==doc['qt_components'])
    return doc
