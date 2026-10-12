import io
import json
import logging

from neurosphere_core.observability import REDACTED, get_logger, redact_text

FAKE_BEARER = "fake-bearer-token-0000"
FAKE_SIG = "fakeSigValue0000"
FAKE_KEY = "fakeAccountKey0000"
FAKE_SAK = "fakeSharedAccessKey0000"
FAKE_PW = "fakePassw0rd0000"
SECRETS = (FAKE_BEARER, FAKE_SIG, FAKE_KEY, FAKE_SAK, FAKE_PW)


def _logger(name: str) -> tuple[logging.Logger, io.StringIO]:
    buf = io.StringIO()
    return get_logger(name, stream=buf), buf


def test_message_text_is_redacted() -> None:
    log, buf = _logger("t.msg")
    log.info(
        "call Bearer %s url https://x.blob/c?sv=1&sig=%s&se=2 "
        "cs=AccountName=a;AccountKey=%s;EndpointSuffix=x;SharedAccessKey=%s;Password=%s",
        FAKE_BEARER,
        FAKE_SIG,
        FAKE_KEY,
        FAKE_SAK,
        FAKE_PW,
    )
    out = buf.getvalue()
    for s in SECRETS:
        assert s not in out
    assert out.count(REDACTED) >= 5
    assert json.loads(out)["level"] == "INFO"


def test_authorization_header_and_named_fields() -> None:
    log, buf = _logger("t.fields")
    log.info(
        "hdr Authorization: Basic fakebasic0000",
        extra={
            "headers": {"Authorization": "Bearer " + FAKE_BEARER, "x-ok": "visible"},
            "prompt": "tell me fake-prompt-0000",
            "response": "fake-response-0000",
            "password": FAKE_PW,
            "nested": [{"Password": FAKE_PW}],
        },
    )
    out = buf.getvalue()
    for s in (*SECRETS, "fakebasic0000", "fake-prompt-0000", "fake-response-0000"):
        assert s not in out
    assert "visible" in out


def test_args_dict_and_positional_are_redacted() -> None:
    log, buf = _logger("t.args")
    log.warning("token %s", f"Bearer {FAKE_BEARER}")
    log.warning("data %(d)s", {"d": {"password": FAKE_PW}})
    assert FAKE_BEARER not in buf.getvalue()
    assert FAKE_PW not in buf.getvalue()


def test_exception_text_is_redacted() -> None:
    log, buf = _logger("t.exc")
    try:
        raise ValueError(f"bad sig={FAKE_SIG}")
    except ValueError:
        log.exception("failed")
    assert FAKE_SIG not in buf.getvalue()


def test_unredacted_logger_still_scrubbed_by_formatter() -> None:
    buf = io.StringIO()
    log = get_logger("t.noredact", stream=buf, redact=False)
    log.info("Bearer %s", FAKE_BEARER)
    assert FAKE_BEARER not in buf.getvalue()


def test_redact_text_is_idempotent_and_keeps_plain_text() -> None:
    once = redact_text("hello sig=" + FAKE_SIG)
    assert redact_text(once) == once
    assert redact_text("plain message") == "plain message"
