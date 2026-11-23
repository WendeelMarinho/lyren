from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from lyren_core.errors import (
    ConfigError,
    ModelDisabledByQuotaError,
    ModelNotAvailableError,
    ProviderAuthError,
    ProviderError,
)
from lyren_core.settings import OCIAuthMode, Settings
from lyren_inference.ports import (
    ApiFormat,
    ChatChunk,
    ChatRequest,
    ChatResponse,
    EmbedRequest,
    EmbedResponse,
    Message,
    ModelSpec,
    Role,
    Usage,
)

_GENERIC_ROLES = {Role.SYSTEM: "SYSTEM", Role.USER: "USER", Role.ASSISTANT: "ASSISTANT"}
_COHERE_ROLES = {Role.USER: "USER", Role.ASSISTANT: "CHATBOT", Role.SYSTEM: "SYSTEM"}


def _build_signer_and_config(settings: Settings) -> tuple[dict[str, Any], Any]:
    import oci

    if settings.oci_auth_mode is OCIAuthMode.INSTANCE_PRINCIPAL:
        return {"region": settings.oci_region}, (
            oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        )

    config = oci.config.from_file(profile_name=settings.oci_config_profile)

    if settings.oci_auth_mode is OCIAuthMode.API_KEY:
        return config, None

    token_file = config.get("security_token_file")
    if not token_file:
        raise ConfigError(
            f"profile {settings.oci_config_profile} has no security_token_file; "
            "re-authenticate or switch LYREN_OCI_AUTH_MODE to api_key"
        )
    token = Path(token_file).expanduser().read_text(encoding="utf-8").strip()
    private_key = oci.signer.load_private_key_from_file(config["key_file"])
    return config, oci.auth.signers.SecurityTokenSigner(token, private_key)


class OCIGenerativeAIProvider:
    """On-demand chat against OCI Generative AI.

    Every call bills, so construction requires an explicitly enabled configuration rather than
    falling back to a default profile.
    """

    name = "oci_generative_ai"

    def __init__(self, settings: Settings) -> None:
        if not settings.oci_ready:
            raise ConfigError("OCI provider needs LYREN_OCI_ENABLED and LYREN_OCI_COMPARTMENT_ID")
        self._settings = settings
        self._compartment_id: str = settings.oci_compartment_id or ""
        self._client: Any | None = None

    def _ensure_client(self) -> Any:
        if self._client is None:
            import oci

            config, signer = _build_signer_and_config(self._settings)
            kwargs: dict[str, Any] = {
                "config": config,
                "timeout": self._settings.request_timeout_seconds,
            }
            if signer is not None:
                kwargs["signer"] = signer
            self._client = oci.generative_ai_inference.GenerativeAiInferenceClient(**kwargs)
        return self._client

    def chat(self, spec: ModelSpec, request: ChatRequest) -> ChatResponse:
        import oci
        from oci.generative_ai_inference import models as genai

        client = self._ensure_client()
        chat_request = (
            self._cohere_request(genai, request)
            if spec.api_format is ApiFormat.COHERE
            else self._generic_request(genai, request)
        )
        details = genai.ChatDetails(
            compartment_id=self._compartment_id,
            serving_mode=genai.OnDemandServingMode(model_id=spec.id),
            chat_request=chat_request,
        )

        try:
            raw = client.chat(details)
        except oci.exceptions.ServiceError as exc:
            raise self._translate(spec, exc) from exc

        return self._to_response(spec, raw.data.chat_response)

    @staticmethod
    def _generic_request(genai: Any, request: ChatRequest) -> Any:
        messages = []
        for message in request.messages:
            role = _GENERIC_ROLES.get(message.role)
            if role is None:
                raise ProviderError(f"role {message.role} is not supported by the GENERIC format")
            messages.append(
                genai.Message(role=role, content=[genai.TextContent(text=message.content)])
            )
        return genai.GenericChatRequest(
            api_format="GENERIC",
            messages=messages,
            max_tokens=request.max_output_tokens,
            temperature=request.temperature,
            stop=list(request.stop) or None,
        )

    @staticmethod
    def _cohere_request(genai: Any, request: ChatRequest) -> Any:
        turns = list(request.messages)
        if not turns or turns[-1].role is not Role.USER:
            raise ProviderError("the COHERE format requires the last message to come from the user")

        preamble = "\n\n".join(m.content for m in turns if m.role is Role.SYSTEM) or None
        history: list[Any] = []
        for message in turns[:-1]:
            if message.role is Role.SYSTEM:
                continue
            role = _COHERE_ROLES.get(message.role)
            if role is None:
                raise ProviderError(f"role {message.role} is not supported by the COHERE format")
            history.append(genai.CohereMessage(role=role, message=message.content))

        return genai.CohereChatRequest(
            api_format="COHERE",
            message=turns[-1].content,
            chat_history=history or None,
            preamble_override=preamble,
            max_tokens=request.max_output_tokens,
            temperature=request.temperature,
            stop_sequences=list(request.stop) or None,
        )

    def stream_chat(self, spec: ModelSpec, request: ChatRequest) -> Iterator[ChatChunk]:
        import oci
        from oci.generative_ai_inference import models as genai

        client = self._ensure_client()
        chat_request = (
            self._cohere_request(genai, request)
            if spec.api_format is ApiFormat.COHERE
            else self._generic_request(genai, request)
        )
        chat_request.is_stream = True
        details = genai.ChatDetails(
            compartment_id=self._compartment_id,
            serving_mode=genai.OnDemandServingMode(model_id=spec.id),
            chat_request=chat_request,
        )

        try:
            raw = client.chat(details)
        except oci.exceptions.ServiceError as exc:
            raise self._translate(spec, exc) from exc

        yield from self._iter_events(spec, raw)

    @staticmethod
    def _iter_events(spec: ModelSpec, raw: Any) -> Iterator[ChatChunk]:
        """Turns provider events into deltas.

        Stateful on purpose. The COHERE format ends with a summary event whose `text` is the whole
        answer rather than a delta, so concatenating every `text` would duplicate the reply. The
        summary's text is dropped once any delta has been emitted, and kept when none has — which
        covers a stream short enough to arrive as one event.
        """
        emitted_text = False
        for event in raw.data.events():
            payload = getattr(event, "data", None)
            if not payload:
                continue
            if payload.strip() == "[DONE]":
                return
            try:
                body = json.loads(payload)
            except json.JSONDecodeError:
                continue

            suppress = (
                spec.api_format is ApiFormat.COHERE and _is_summary_event(body) and emitted_text
            )
            chunk = _chunk_from_event(spec, body, suppress_text=suppress)
            if chunk is None:
                continue
            if chunk.text:
                emitted_text = True
            yield chunk

    def embed(self, spec: ModelSpec, request: EmbedRequest) -> EmbedResponse:
        import oci
        from oci.generative_ai_inference import models as genai

        if not request.inputs:
            raise ProviderError("an embedding request needs at least one input")

        client = self._ensure_client()
        details = genai.EmbedTextDetails(
            compartment_id=self._compartment_id,
            serving_mode=genai.OnDemandServingMode(model_id=spec.id),
            inputs=list(request.inputs),
            input_type=str(request.input_type),
            truncate="END",
        )

        try:
            raw = client.embed_text(details)
        except oci.exceptions.ServiceError as exc:
            raise self._translate(spec, exc) from exc

        vectors = tuple(tuple(float(v) for v in row) for row in (raw.data.embeddings or ()))
        if len(vectors) != len(request.inputs):
            raise ProviderError(
                f"{spec.id} returned {len(vectors)} vectors for {len(request.inputs)} inputs"
            )
        return EmbedResponse(model_id=spec.id, vectors=vectors)

    @staticmethod
    def _translate(spec: ModelSpec, exc: Any) -> Exception:
        message = str(getattr(exc, "message", "") or "")
        status = int(getattr(exc, "status", 0) or 0)
        if status in {401, 403} and "set to 0" not in message:
            return ProviderAuthError(
                "OCI rejected our credentials; the session token has probably expired",
                detail=message,
            )
        if status == 404:
            return ModelNotAvailableError(
                f"{spec.id} is not served on demand in this tenancy", detail=message
            )
        if status == 429 and "set to 0" in message:
            return ModelDisabledByQuotaError(
                f"{spec.id} is disabled by a zero tenancy quota", detail=message
            )
        return ProviderError(f"OCI Generative AI rejected the call to {spec.id}", detail=message)

    @staticmethod
    def _to_response(spec: ModelSpec, payload: Any) -> ChatResponse:
        if spec.api_format is ApiFormat.COHERE:
            text = getattr(payload, "text", "") or ""
            finish_reason = getattr(payload, "finish_reason", None) or "stop"
        else:
            choices = getattr(payload, "choices", None) or []
            if not choices:
                raise ProviderError(f"{spec.id} returned no choices")
            first = choices[0]
            parts = getattr(first.message, "content", None) or []
            text = "".join(getattr(part, "text", "") or "" for part in parts)
            finish_reason = getattr(first, "finish_reason", None) or "stop"

        raw_usage = getattr(payload, "usage", None)
        return ChatResponse(
            model_id=spec.id,
            text=text,
            finish_reason=str(finish_reason),
            usage=Usage(
                prompt_tokens=getattr(raw_usage, "prompt_tokens", None),
                completion_tokens=getattr(raw_usage, "completion_tokens", None),
            ),
        )


def _is_summary_event(body: dict[str, Any]) -> bool:
    return "finishReason" in body or "chatHistory" in body


def _chunk_from_event(
    spec: ModelSpec, body: dict[str, Any], *, suppress_text: bool = False
) -> ChatChunk | None:
    """Extracts a delta from one stream event.

    The event shape differs between the COHERE and GENERIC formats and is not fully documented, so
    the known shapes are tried in order and an unrecognised event is skipped rather than guessed at.

    Observed on 2026-11-24 in sa-saopaulo-1: GENERIC emits deltas under
    `message.content[].text`, closing with an empty-text event carrying `finishReason` and then a
    `[DONE]` sentinel. COHERE emits deltas under `text` and closes with a summary event whose
    `text` is the **complete** answer. Neither reports `usage` on a stream.
    """
    finish_reason = body.get("finishReason") or body.get("finish_reason")
    raw_usage = body.get("usage")
    usage = (
        Usage(
            prompt_tokens=raw_usage.get("promptTokens") or raw_usage.get("prompt_tokens"),
            completion_tokens=raw_usage.get("completionTokens")
            or raw_usage.get("completion_tokens"),
        )
        if isinstance(raw_usage, dict)
        else None
    )

    text = ""
    if spec.api_format is ApiFormat.COHERE:
        text = "" if suppress_text else str(body.get("text") or "")
    else:
        message_body = body.get("message") or {}
        parts = message_body.get("content") or []
        text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
        if not text:
            for choice in body.get("choices") or []:
                delta = choice.get("delta") or choice.get("message") or {}
                content = delta.get("content")
                if isinstance(content, str):
                    text += content
                elif isinstance(content, list):
                    text += "".join(
                        str(p.get("text") or "") for p in content if isinstance(p, dict)
                    )
                finish_reason = finish_reason or choice.get("finishReason")

    if not text and finish_reason is None and usage is None:
        return None
    return ChatChunk(text=text, finish_reason=finish_reason, usage=usage)


def message(role: Role, content: str) -> Message:
    return Message(role=role, content=content)
