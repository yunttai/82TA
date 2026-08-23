from __future__ import annotations

from typing import Protocol

from django.conf import settings

from .api_common import ApiProblem


class ConsentState(Protocol):
    accepted: bool
    document_version: str


def consent_types() -> frozenset[str]:
    return frozenset(settings.CONSENT_DOCUMENT_VERSIONS)


def current_document_version(consent_type: str) -> str:
    version = settings.CONSENT_DOCUMENT_VERSIONS.get(consent_type)
    if version is None:
        raise ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "Unknown consent type")
    return version


def validate_document_version(consent_type: str, supplied_version: str) -> None:
    if supplied_version != current_document_version(consent_type):
        raise ApiProblem(
            400,
            "CONSTRAINT_OUT_OF_RANGE",
            "Consent document version is not current",
            violations=(
                {
                    "field": "documentVersion",
                    "message": "must match the current server consent policy",
                },
            ),
        )


def is_current_accepted(consent_type: str, state: ConsentState | None) -> bool:
    return (
        state is not None
        and state.accepted
        and state.document_version == current_document_version(consent_type)
    )
