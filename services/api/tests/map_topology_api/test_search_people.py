"""People are matched and shown only by pseudonym (PRP-74 item 2)."""

import asyncio

from map_api_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    FINANCE,
    agent_doc,
    make_api,
    person_doc,
)
from topology_helpers import get_search  # pyright: ignore[reportMissingImports]

# The person's stored identity string contains a real-name-like token. It must never be
# searchable and never appear in a response.
_REAL = "janedoe"
_PERSON = f"{_REAL}smithaccount01"


def test_person_is_not_found_by_real_name_and_name_is_absent_from_every_response() -> None:
    api = make_api()
    api.seed(person_doc(_PERSON, FINANCE), agent_doc("support", FINANCE))
    for params in ({"q": _REAL}, {"q": _PERSON}, {"q": _REAL.upper()}, {"q": ""}, {"q": "support"}):
        response = get_search(api, ALICE, FINANCE, **params)
        assert response.status_code == 200
        assert _REAL not in response.text.lower()
    assert get_search(api, ALICE, FINANCE, q=_REAL).json()["matches"] == []
    assert get_search(api, ALICE, FINANCE, q=_REAL).json()["counts"]["by_kind"] == {}


def test_person_is_found_by_pseudonym_and_only_shown_as_it() -> None:
    api = make_api()
    api.seed(person_doc(_PERSON, FINANCE), agent_doc("support", FINANCE))
    scope = asyncio.run(api.scope_of(ALICE))
    pseudonym = api.h.app.state.map_pseudonymizer.pseudonym(
        scope.customer_id, f"commercial:contoso:entra:person:psn_{_PERSON}"
    )
    response = get_search(api, ALICE, FINANCE, q=pseudonym.upper())
    body = response.json()
    assert [m["node"]["kind"] for m in body["matches"]] == ["person"]
    node = body["matches"][0]["node"]
    assert node["id"] == pseudonym
    assert node["label"] == pseudonym
    assert body["matches"][0]["cluster_id"] == "kind:person"
    assert _REAL not in response.text.lower()
    assert "psn_" not in response.text


def test_person_filter_by_node_type() -> None:
    api = make_api()
    api.seed(person_doc(_PERSON, FINANCE), agent_doc("support", FINANCE))
    body = get_search(api, ALICE, FINANCE, node_type="person").json()
    assert body["counts"]["by_kind"] == {"person": 1}
    assert _REAL not in str(body).lower()
