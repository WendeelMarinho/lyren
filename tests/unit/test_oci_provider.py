from lyren_core.errors import ModelDisabledByQuotaError, ModelNotAvailableError, ProviderError
from lyren_inference.ports import ApiFormat, Availability, Capability, ModelSpec
from lyren_inference.providers.oci import OCIGenerativeAIProvider

SPEC = ModelSpec(
    id="openai.gpt-oss-120b",
    vendor="openai",
    provider="oci_generative_ai",
    api_format=ApiFormat.GENERIC,
    pinned_version="1.0.0",
    capabilities=frozenset({Capability.CHAT}),
    availability=Availability.UNVERIFIED,
)


class FakeServiceError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def test_404_becomes_model_not_available():
    error = OCIGenerativeAIProvider._translate(
        SPEC, FakeServiceError(404, "Entity with key openai.gpt-oss-120b not found")
    )

    assert isinstance(error, ModelNotAvailableError)


def test_zero_quota_429_is_distinguished_from_real_throttling():
    disabled = OCIGenerativeAIProvider._translate(
        SPEC,
        FakeServiceError(429, "Access to model x is disabled because tenancy limit y is set to 0."),
    )
    throttled = OCIGenerativeAIProvider._translate(SPEC, FakeServiceError(429, "Too many requests"))

    assert isinstance(disabled, ModelDisabledByQuotaError)
    assert isinstance(throttled, ProviderError)
    assert not isinstance(throttled, ModelDisabledByQuotaError)


def test_401_is_reported_as_a_credential_failure_not_a_model_failure():
    from lyren_core.errors import ProviderAuthError

    error = OCIGenerativeAIProvider._translate(
        SPEC,
        FakeServiceError(
            401, "The required information to complete authentication was not provided"
        ),
    )

    assert isinstance(error, ProviderAuthError)


class FakeEvent:
    def __init__(self, data):
        self.data = data


class FakeStream:
    def __init__(self, payloads):
        self._payloads = payloads

    def events(self):
        return (FakeEvent(p) for p in self._payloads)


class FakeRaw:
    def __init__(self, payloads):
        self.data = FakeStream(payloads)


def _chat_spec(api_format):

    return ModelSpec(
        id="m",
        vendor="v",
        provider="oci_generative_ai",
        api_format=api_format,
        pinned_version="1",
        capabilities=frozenset({Capability.CHAT}),
        availability=Availability.VERIFIED,
    )


def test_generic_stream_events_become_deltas_and_a_finish_reason():
    from lyren_inference.ports import ApiFormat

    payloads = [
        '{"index":0,"message":{"role":"ASSISTANT","content":[{"type":"TEXT","text":"po"}]}}',
        '{"index":0,"message":{"role":"ASSISTANT","content":[{"type":"TEXT","text":"ng"}]}}',
        '{"message":{"role":"ASSISTANT","content":[{"type":"TEXT","text":""}]},"finishReason":"stop"}',
        "[DONE]",
    ]

    chunks = list(
        OCIGenerativeAIProvider._iter_events(_chat_spec(ApiFormat.GENERIC), FakeRaw(payloads))
    )

    assert "".join(c.text for c in chunks) == "pong"
    assert [c.finish_reason for c in chunks if c.finish_reason] == ["stop"]


def test_the_cohere_summary_event_does_not_duplicate_the_answer():
    """Observed live: COHERE closes with an event whose `text` is the whole reply, not a delta."""
    from lyren_inference.ports import ApiFormat

    payloads = [
        '{"apiFormat":"COHERE","text":"Pong"}',
        '{"apiFormat":"COHERE","text":"."}',
        '{"apiFormat":"COHERE","text":"Pong.","chatHistory":[],"finishReason":"COMPLETE"}',
    ]

    chunks = list(
        OCIGenerativeAIProvider._iter_events(_chat_spec(ApiFormat.COHERE), FakeRaw(payloads))
    )

    assert "".join(c.text for c in chunks) == "Pong."
    assert [c.finish_reason for c in chunks if c.finish_reason] == ["COMPLETE"]


def test_a_cohere_stream_arriving_as_one_summary_event_keeps_its_text():
    from lyren_inference.ports import ApiFormat

    payloads = ['{"apiFormat":"COHERE","text":"Pong.","finishReason":"COMPLETE"}']

    chunks = list(
        OCIGenerativeAIProvider._iter_events(_chat_spec(ApiFormat.COHERE), FakeRaw(payloads))
    )

    assert "".join(c.text for c in chunks) == "Pong."


def test_an_unparseable_event_is_skipped_rather_than_guessed_at():
    from lyren_inference.ports import ApiFormat

    payloads = ["not json", '{"apiFormat":"COHERE","text":"ok"}']

    chunks = list(
        OCIGenerativeAIProvider._iter_events(_chat_spec(ApiFormat.COHERE), FakeRaw(payloads))
    )

    assert "".join(c.text for c in chunks) == "ok"
