"""Review policy routes, mounted at ``/api/v1/admin/platform/review-policy`` (PRP-44).

| Method | Path     | Notes                                                                    |
|--------|----------|--------------------------------------------------------------------------|
| GET    | ``""``   | the stored policy, or the built-in defaults (``ETag`` ``"defaults"``)   |
| PUT    | ``""``   | replace; ``If-Match`` required; returns the before and after diff        |

A stored policy applies when the API and the ``actions``, ``hitl_timers`` and ``evaluation``
worker roles next start (no hot reload). Maker-checker can never be loosened through this route.
A policy body is never logged or put in an audit record (only the version and change count).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from fastapi import APIRouter, Request, Response
from neurosphere_contracts.admin.v1.review_policy_document import ReviewPolicyDocument
from neurosphere_core.admin.platform import ReviewPolicyWrite

from neurosphere_api.admin.platform.deps import IfMatch, Platform, correlation, set_etag
from neurosphere_api.admin.platform.models import (
    ReviewPolicyView,
    ReviewPolicyWriteView,
    policy_view,
    policy_write_view,
)


def _info(write: ReviewPolicyWrite) -> tuple[str | None, dict[str, object]]:
    return write.stored.etag.root, {
        "version": write.stored.version.root,
        "policy_version": write.after.policy_version,
        "changes": len(write.changes),
    }


def build_router() -> APIRouter:
    router = APIRouter(tags=["admin-platform-review-policy"])

    @router.get("", response_model=ReviewPolicyView)
    async def get_review_policy(response: Response, platform: Platform) -> ReviewPolicyView:
        read = await platform.admin.review_policy.get(platform.customer_id)
        set_etag(response, read.etag)
        return policy_view(read)

    @router.put("", response_model=ReviewPolicyWriteView)
    async def put_review_policy(
        request: Request,
        response: Response,
        body: ReviewPolicyDocument,
        if_match: IfMatch,
        platform: Platform,
    ) -> ReviewPolicyWriteView:
        write = await platform.audit.run(
            correlation(request),
            "review_policy.replace",
            "review_policy",
            "review_policy",
            lambda: platform.admin.review_policy.replace(
                platform.customer_id, body, if_match=if_match, updated_by=platform.actor
            ),
            info=_info,
        )
        set_etag(response, write.stored.etag.root)
        return policy_write_view(write)

    return router
