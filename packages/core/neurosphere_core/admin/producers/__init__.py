"""Ingest producer administration (PRP-41): show-once secrets over the ``admin_config`` store."""

from neurosphere_core.admin.producers.secret import (
    SECRET_BYTES,
    IssuedSecret,
    issue_secret,
    secret_digest,
)
from neurosphere_core.admin.producers.service import (
    PRODUCER_KIND,
    ProducerAdmin,
    ProducerResult,
    registration_from_record,
)

__all__ = [
    "PRODUCER_KIND",
    "SECRET_BYTES",
    "IssuedSecret",
    "ProducerAdmin",
    "ProducerResult",
    "issue_secret",
    "registration_from_record",
    "secret_digest",
]
