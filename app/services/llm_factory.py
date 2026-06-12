from __future__ import annotations
import os
from typing import Any, Optional
from langchain_openai import ChatOpenAI, AzureChatOpenAI
from app.core.config import settings

def _normalize_provider(provider: str | None) -> str:
    return (provider or "").lower().strip().replace("_", "-")


def _clean_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(kwargs)
    cleaned.pop("role", None)
    cleaned.pop("trace_id", None)
    cleaned.pop("provider", None)
    return cleaned


def make_oss120b_llm(
    temperature: float = 0,
    role: str = "general",
    **kwargs: Any,
):
    clean_kwargs = _clean_kwargs(kwargs)

    return ChatOpenAI(
        model=settings.oss120b_model,
        api_key=settings.oss120b_api_key or "not-required",
        base_url=settings.oss120b_base_url,
        temperature=temperature,
        timeout=settings.llm_timeout_seconds,
        max_retries=0,
        **clean_kwargs,
    )


def make_azure_gpt4o_llm(
    temperature: float = 0,
    role: str = "general",
    **kwargs: Any,
):
    clean_kwargs = _clean_kwargs(kwargs)

    return AzureChatOpenAI(
        azure_deployment=settings.azure_openai_chat_deployment,
        api_key=settings.azure_openai_api_key,
        azure_endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
        temperature=temperature,
        timeout=120,
        max_retries=1,
        **clean_kwargs,
    )


def _build_provider_llm(
    provider: str,
    temperature: float,
    role: str,
    **kwargs: Any,
):
    if provider in {"oss", "oss120b", "oss120b-http", "gpt-oss", "gpt-oss-120b"}:
        return make_oss120b_llm(temperature=temperature, role=role, **kwargs)
    if provider in {"azure", "azure-openai", "gpt4o", "gpt-4o"}:
        return make_azure_gpt4o_llm(temperature=temperature, role=role, **kwargs)
    return make_azure_gpt4o_llm(temperature=temperature, role=role, **kwargs)


def _resolve_provider(role: str, force_provider: Optional[str]) -> str:
    explicit = _normalize_provider(force_provider)
    if explicit:
        return explicit
    if role in {"sql_toolkit", "sql_agent", "nl2sql"}:
        return _normalize_provider(settings.llm_sql_provider)
    return _normalize_provider(settings.llm_general_provider)


# Exception classes that justify trying the fallback provider. We intentionally
# limit to network/availability failures so that genuine bugs (bad prompts,
# JSON decode errors thrown by callers) still surface fast.
def _connection_exceptions() -> tuple[type, ...]:
    excs: list[type] = []
    try:
        import httpx  # type: ignore
        excs.extend([httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError])
    except Exception:
        pass
    try:
        import openai  # type: ignore
        for name in ("APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError"):
            cls = getattr(openai, name, None)
            if cls is not None:
                excs.append(cls)
    except Exception:
        pass
    return tuple(excs) if excs else (Exception,)


def make_chat_llm(
    temperature: float = 0,
    role: str = "general",
    force_provider: Optional[str] = None,
    with_fallback: bool = True,
    **kwargs: Any,
):
    """Build a chat LLM, with automatic fallback on network errors.

    When ``with_fallback`` is true (default) and ``LLM_FALLBACK_PROVIDER`` is
    configured to a different provider than the primary, the returned runnable
    transparently retries against the fallback on connection/timeout/rate-limit
    errors. This protects callers like the Data Products scanner that previously
    surfaced raw "Connection error" messages when the primary endpoint was
    unreachable.
    """
    provider = _resolve_provider(role, force_provider)
    primary = _build_provider_llm(provider, temperature, role, **kwargs)

    if not with_fallback:
        return primary

    fb_provider = _normalize_provider(settings.llm_fallback_provider)
    if not fb_provider or fb_provider == provider:
        return primary
    try:
        fallback = _build_provider_llm(fb_provider, temperature, role, **kwargs)
    except Exception:
        return primary  # fallback misconfigured — keep primary alone
    try:
        return primary.with_fallbacks(
            [fallback],
            exceptions_to_handle=_connection_exceptions(),
        )
    except Exception:
        # If the runtime does not support with_fallbacks for this LLM type,
        # caller still gets the primary — degraded but functional.
        return primary


def make_sql_llm(temperature: float = 0, **kwargs: Any):
    """
    LLM principal para NL2SQL.
    Default desejado: GPT-OSS-120B.

    Returns a *raw* LLM (not wrapped in with_fallbacks) so the caller can
    use ``.bind_tools(...)``; the fallback chain for SQL is constructed
    afterwards by ``bind_tools_with_fallback``.
    """

    return make_chat_llm(
        temperature=temperature,
        role="sql_toolkit",
        force_provider=settings.llm_sql_provider,
        with_fallback=False,
        **kwargs,
    )


def make_sql_fallback_llm(temperature: float = 0, **kwargs: Any):
    """
    Fallback operacional para NL2SQL.
    Default recomendado: Azure GPT-4o. Returned raw for the same
    bind_tools reason as ``make_sql_llm``.
    """

    return make_chat_llm(
        temperature=temperature,
        role="sql_toolkit.fallback",
        force_provider=settings.llm_fallback_provider,
        with_fallback=False,
        **kwargs,
    )


def make_general_llm(temperature: float = 0, **kwargs: Any):
    return make_chat_llm(
        temperature=temperature,
        role="general",
        force_provider=settings.llm_general_provider,
        **kwargs,
    )


def bind_tools_with_fallback(llm, tools, fallback_llm=None):
    """
    Vincula as tools ao LLM principal e, quando há um provedor de fallback
    DISTINTO configurado (LLM_FALLBACK_PROVIDER), encadeia um fallback que é
    acionado em falhas de timeout/conexão/disponibilidade do principal.

    Objetivo:
    - GPT-OSS-120B como principal.
    - Azure GPT-4o como fallback (failover em timeout do oss120b).

    Resiliente: se o fallback estiver ausente/mal configurado, o agente segue
    funcionando só com o principal (não quebra o build do agente).
    """
    # Constrói o fallback de forma defensiva — um provedor mal configurado
    # (ex.: Azure sem credenciais) NÃO pode derrubar a construção do agente.
    if fallback_llm is None:
        try:
            fallback_llm = make_sql_fallback_llm(temperature=0)
        except Exception:
            fallback_llm = None

    try:
        primary_with_tools = llm.bind_tools(tools)
    except Exception:
        # Principal falhou no bind — usa o fallback se houver, senão propaga.
        if fallback_llm is None:
            raise
        return fallback_llm.bind_tools(tools)

    if fallback_llm is None:
        return primary_with_tools

    try:
        fallback_with_tools = fallback_llm.bind_tools(tools)
        # Failover apenas em timeout/conexão/rate-limit/5xx — erros genuínos
        # (ex.: SQL inválido) continuam a aflorar em vez de mascarar com retry.
        return primary_with_tools.with_fallbacks(
            [fallback_with_tools],
            exceptions_to_handle=_connection_exceptions(),
        )
    except Exception:
        return primary_with_tools
