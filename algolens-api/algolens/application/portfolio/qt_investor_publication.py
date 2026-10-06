"""Explicit release of a proven processed QT book, without delivery."""
from copy import deepcopy
from dataclasses import dataclass
import re
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError


@dataclass(frozen=True)
class QtPublishRequest:
    expected_selected_book_digest: str

    @classmethod
    def from_wire(cls, value):
        if (type(value) is not dict or set(value) != {'action', 'expected_selected_book_digest'}
                or value['action'] != 'publish_qt_snapshot'
                or type(value['expected_selected_book_digest']) is not str
                or not re.fullmatch('[0-9a-f]{64}', value['expected_selected_book_digest'])):
            raise QtWorkflowError('invalid_qt_payload')
        return cls(value['expected_selected_book_digest'])


class QtPublicationView:
    def __init__(self, payload):
        self.payload = deepcopy(payload)

    def to_wire(self):
        return deepcopy(self.payload)


class QtInvestorPublicationService:
    def __init__(self, reader, repository):
        self.reader, self.repository = reader, repository

    def publish(self, decision_id, actor_id, request):
        action = self.repository.release_action(actor_id, request.expected_selected_book_digest)
        return self.reader.with_processed_snapshot(decision_id, actor_id, action)

    def get_public(self, book_id, source_day):
        return QtPublicationView(self.repository.get_public(book_id, source_day))
