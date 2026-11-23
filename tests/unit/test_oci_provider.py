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
