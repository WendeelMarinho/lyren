import pytest

from lyren_core.errors import ProviderError
from lyren_inference.ports import (
    ApiFormat,
    Availability,
    Capability,
    ChatRequest,
    ChatResponse,
    Message,
    ModelSpec,
    Role,
)
from lyren_inference.router import ProviderRouter

REQUEST = ChatRequest(messages=(Message(role=Role.USER, content="ping"),))


def spec(provider):
    return ModelSpec(
        id=f"{provider}/m",
        vendor="v",
        provider=provider,
        api_format=ApiFormat.GENERIC,
        pinned_version="1",
        capabilities=frozenset({Capability.CHAT}),
        availability=Availability.VERIFIED,
    )


class Named:
    def __init__(self, name):
        self.name = name
        self.calls = 0

    def chat(self, model_spec, request):
        self.calls += 1
        return ChatResponse(model_id=model_spec.id, text=self.name, finish_reason="stop")


def test_each_model_reaches_the_provider_that_serves_it():
    hosted, local = Named("hosted"), Named("local")
    router = ProviderRouter({"hosted": hosted, "local": local})

    assert router.chat(spec("hosted"), REQUEST).text == "hosted"
    assert router.chat(spec("local"), REQUEST).text == "local"
    assert (hosted.calls, local.calls) == (1, 1)


def test_an_unconfigured_provider_names_what_is_configured():
    router = ProviderRouter({"hosted": Named("hosted")})

    with pytest.raises(ProviderError, match="no provider is configured for local"):
        router.chat(spec("local"), REQUEST)


def test_serves_reports_whether_a_model_can_be_dispatched():
    router = ProviderRouter({"hosted": Named("hosted")})

    assert router.serves(spec("hosted")) is True
    assert router.serves(spec("local")) is False


def test_the_router_lists_its_providers():
    router = ProviderRouter({"hosted": Named("h"), "local": Named("l")})

    assert sorted(router.providers()) == ["hosted", "local"]
