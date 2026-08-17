from __future__ import annotations

import hashlib
import importlib
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable

from openai import RateLimitError as OpenAIRateLimitError

logger = logging.getLogger(__name__)

INPUT_BLOCK_MESSAGE = (
    "I'm sorry, but I can't process that request because it may violate the chatbot's "
    "safety guidelines. Please ask a respectful HR or onboarding question without "
    "sharing sensitive personal information."
)
OUTPUT_BLOCK_MESSAGE = (
    "I'm sorry, but I can't display the generated answer because it did not meet the "
    "chatbot's safety guidelines. Please contact HR for help with this question."
)
RATE_LIMIT_MESSAGE = (
    "The HR onboarding assistant is temporarily rate limited by OpenAI. "
    "Please wait a minute and try again."
)

GUARDRAILS_ENABLED = os.getenv("HR_ONBOARDING_GUARDRAILS_ENABLED", "true").lower() not in {
    "0",
    "false",
    "no",
}
GUARDRAILS_DEVICE = os.getenv("HR_ONBOARDING_GUARDRAILS_DEVICE", "cpu")
GUARDRAILS_JAILBREAK_THRESHOLD = float(os.getenv("HR_ONBOARDING_GUARDRAILS_JAILBREAK_THRESHOLD", "0.85"))
GUARDRAILS_POLITENESS_MODEL = os.getenv("HR_ONBOARDING_GUARDRAILS_POLITENESS_MODEL", "gpt-3.5-turbo")
GUARDRAILS_TOXIC_LLM_MODEL = os.getenv("HR_ONBOARDING_GUARDRAILS_TOXIC_LLM_MODEL", "gpt-3.5-turbo")

_VALIDATOR_PACKAGE_IMPORTS = {
    "LlamaGuard7B": ("guardrails_grhub_llamaguard_7b", "guardrails_ai.llamaguard_7b"),
    "DetectPII": ("guardrails_grhub_detect_pii", "guardrails_ai.detect_pii"),
    "NSFWText": ("guardrails_grhub_nsfw_text", "guardrails_ai.nsfw_text"),
    "ProfanityFree": ("guardrails_grhub_profanity_free", "guardrails_ai.profanity_free"),
    "ToxicLanguage": ("guardrails_grhub_toxic_language", "guardrails_ai.toxic_language"),
    "DetectJailbreak": ("guardrails_grhub_detect_jailbreak", "guardrails_ai.detect_jailbreak"),
    "PolitenessCheck": ("guardrails_grhub_politeness_check", "guardrails_ai.politeness_check"),
    "ToxicLanguageLLM": ("guardrails_grhub_toxic_language_llm", "guardrails_ai.toxic_language_llm"),
    "UnusualPrompt": ("guardrails_grhub_unusual_prompt", "guardrails_ai.unusual_prompt"),
    "GroundedAIHallucination": ("guardrails_grhub_grounded_ai_hallucination", "guardrails_ai.grounded_ai_hallucination"),
}


class HrOnboardingGuardrailsBlocked(ValueError):
    def __init__(self, message: str, *, user_message: str):
        super().__init__(message)
        self.user_message = user_message


class HrOnboardingRateLimited(RuntimeError):
    def __init__(self, message: str = "openai_rate_limited", *, user_message: str = RATE_LIMIT_MESSAGE):
        super().__init__(message)
        self.user_message = user_message


@dataclass(frozen=True)
class _GuardrailCheck:
    name: str
    guard: Any


@dataclass(frozen=True)
class _GuardrailsRuntime:
    input_checks: tuple[_GuardrailCheck, ...]
    output_checks: tuple[_GuardrailCheck, ...]
    grounded_checks: tuple[_GuardrailCheck, ...]
    input_validators: tuple[str, ...]
    output_validators: tuple[str, ...]
    grounded_validators: tuple[str, ...]


_ACTIVE_VALIDATOR_NAMES = (
    "ProfanityFree",
    "DetectPII",
    "UnusualPrompt",
    "LlamaGuard7B",
)

_VALIDATOR_BLOCK_MESSAGES = {
    "input": {
        "ProfanityFree": "I understand you may be frustrated, but I can't respond to messages containing profanity. Please rephrase your HR question in professional language so I can help.",
        "AbusiveLanguage": "I understand what you're trying to express, but I can't assist with abusive or disrespectful language. Please rephrase your request professionally so I can help with your HR or onboarding question.",
        "DetectPII": "For your privacy and security, please remove sensitive personal information, such as phone numbers, SSNs, or payment details, before asking your HR question.",
        "UnusualPrompt": "I'm sorry, but I can't follow requests that try to override the chatbot's safety instructions. Please ask a regular HR or onboarding question and I'll be happy to help.",
        "LlamaGuard7B": "I'm sorry, but I can't help with requests that may be unsafe or outside HR onboarding support. Please rephrase your question in a safe and professional way.",
    },
    "output": {
        "ProfanityFree": "I'm sorry, but I can't show the generated answer because the wording did not meet the chatbot's professionalism standards. Please contact HR for help with this question.",
        "DetectPII": "I'm sorry, but I can't show the generated answer because it may include sensitive personal information. Please contact HR for help with this question.",
        "LlamaGuard7B": "I'm sorry, but I can't show the generated answer because it did not meet the chatbot's safety guidelines. Please contact HR for help with this question.",
    },
    "grounded_output": {
        "GroundedAIHallucination": "I'm sorry, but I couldn't fully verify the generated answer against the uploaded HR documents. Please contact HR for confirmation.",
    },
}

_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE_PATTERN = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}")
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_PROFANITY_PATTERN = re.compile(
    r"\b(fuck|fucking|shit|bullshit|bitch|bastard|asshole|dick|cunt)\b",
    re.I,
)
_ABUSIVE_DIRECT_PATTERN = re.compile(
    r"\b(you\s+(are|re|'re)\s+)?(idiot|stupid|moron|loser|worthless|dumb|shut\s+up)\b",
    re.I,
)
_ABUSIVE_REQUEST_PATTERN = re.compile(
    r"(\b(write|say|generate|give|list|tell)\b.{0,40}\b(abusive|insulting|vulgar|offensive|derogatory|belittling|rude)\b|\b(abusive|insulting|vulgar|offensive|derogatory|belittling|rude)\s+(words|language|terms|messages?|sentences?)\b)",
    re.I,
)
_WORKPLACE_POLICY_CONTEXT_PATTERN = re.compile(
    r"\b(policy|policies|workplace|employee|hr|harassment|complaint|report|training|conduct|disciplinary)\b",
    re.I,
)
_SAFE_HR_POLICY_QUESTION_PATTERN = re.compile(
    r"\b(policy|policies|benefits?|enroll(?:ment)?|onboarding|handbook|workplace|conduct|leave|pto|holiday|"
    r"medical|dental|insurance|payroll|training|compliance|probation|attendance|reimbursement|"
    r"contact|contacts|email|phone|company|hr\s+contact|support|new\s+hires?|complete|first|important)\b",
    re.I,
)
_SUSPICIOUS_INPUT_PATTERN = re.compile(
    r"\b("
    r"ignore|override|bypass|jailbreak|developer\s+message|system\s+prompt|hidden\s+instructions?|"
    r"reveal|print|show|exfiltrate|disable\s+(guardrails?|safety)|act\s+as|pretend\s+to\s+be|"
    r"do\s+anything\s+now|dan\s+mode|prompt\s+injection"
    r")\b",
    re.I,
)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_openai_rate_limit_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, OpenAIRateLimitError):
            return True
        if getattr(current, "status_code", None) == 429:
            return True
        message = str(current).lower()
        if "rate limit" in message or "rate_limit" in message or "status code: 429" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


def _fast_input_block_message(text: str) -> str | None:
    if (
        _EMAIL_PATTERN.search(text)
        or _PHONE_PATTERN.search(text)
        or _SSN_PATTERN.search(text)
        or _CREDIT_CARD_PATTERN.search(text)
    ):
        return _VALIDATOR_BLOCK_MESSAGES["input"]["DetectPII"]
    if _PROFANITY_PATTERN.search(text):
        return _VALIDATOR_BLOCK_MESSAGES["input"]["ProfanityFree"]
    if _ABUSIVE_DIRECT_PATTERN.search(text) or (
        _ABUSIVE_REQUEST_PATTERN.search(text)
        and not _WORKPLACE_POLICY_CONTEXT_PATTERN.search(text)
    ):
        return _VALIDATOR_BLOCK_MESSAGES["input"]["AbusiveLanguage"]
    return None


def _is_fast_safe_hr_question(text: str) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized or len(normalized) > 500:
        return False
    if _fast_input_block_message(normalized) is not None:
        return False
    if _SUSPICIOUS_INPUT_PATTERN.search(normalized):
        return False
    return bool(_SAFE_HR_POLICY_QUESTION_PATTERN.search(normalized))


def _fast_output_block_message(text: str, *, reference: str | None = None) -> str | None:
    if _SSN_PATTERN.search(text) or _CREDIT_CARD_PATTERN.search(text):
        return _VALIDATOR_BLOCK_MESSAGES["output"]["DetectPII"]
    if _PROFANITY_PATTERN.search(text):
        return _VALIDATOR_BLOCK_MESSAGES["output"]["ProfanityFree"]
    if _ABUSIVE_DIRECT_PATTERN.search(text) or (
        _ABUSIVE_REQUEST_PATTERN.search(text)
        and not _WORKPLACE_POLICY_CONTEXT_PATTERN.search(text)
    ):
        return OUTPUT_BLOCK_MESSAGE

    # Company contact details from HR policy excerpts are allowed when the
    # generated answer repeats them exactly from the retrieved reference text.
    if reference is not None:
        for pattern in (_EMAIL_PATTERN, _PHONE_PATTERN):
            for match in pattern.findall(text):
                value = match if isinstance(match, str) else "".join(match)
                if value and value not in reference:
                    return _VALIDATOR_BLOCK_MESSAGES["output"]["DetectPII"]
    elif _EMAIL_PATTERN.search(text) or _PHONE_PATTERN.search(text):
        return _VALIDATOR_BLOCK_MESSAGES["output"]["DetectPII"]

    return None


def _is_safe_grounded_policy_exchange(*, question: str, answer: str, reference: str | None) -> bool:
    if not reference or not _SAFE_HR_POLICY_QUESTION_PATTERN.search(question):
        return False
    return _fast_input_block_message(question) is None and _fast_output_block_message(answer, reference=reference) is None


def _load_guardrails() -> tuple[type[Any], dict[str, type[Any]]] | None:
    try:
        guardrails = importlib.import_module("guardrails")
    except Exception as exc:
        logger.warning("John Guardrails AI is unavailable: %s", exc)
        return None

    guard_class = getattr(guardrails, "Guard", None)
    if guard_class is None:
        logger.warning("John Guardrails AI loaded without Guard class.")
        return None

    validator_names = _ACTIVE_VALIDATOR_NAMES
    validators: dict[str, type[Any]] = {}
    try:
        hub = importlib.import_module("guardrails.hub")
    except Exception:
        hub = None

    for name in validator_names:
        hub_validator = getattr(hub, name, None) if hub is not None else None
        if hub_validator is not None:
            validators[name] = hub_validator
            continue
        module_names = _VALIDATOR_PACKAGE_IMPORTS.get(name, ())
        if not module_names:
            continue
        for module_name in module_names:
            try:
                module = importlib.import_module(module_name)
                package_validator = getattr(module, name, None)
                if package_validator is not None:
                    validators[name] = package_validator
                    break
            except ModuleNotFoundError:
                logger.debug("John Guardrails package import missing: validator=%s module=%s", name, module_name)
            except Exception as exc:
                logger.warning("John Guardrails package import failed: validator=%s module=%s error=%s", name, module_name, exc)

    missing = sorted(set(validator_names) - set(validators))
    if missing:
        logger.warning("John Guardrails validators missing from runtime: %s", ", ".join(missing))
    return guard_class, validators


def _llama_guard_validator(cls: type[Any]) -> Any:
    policies = [
        getattr(cls, "POLICY__NO_VIOLENCE_HATE", None),
        getattr(cls, "POLICY__NO_SEXUAL_CONTENT", None),
        getattr(cls, "POLICY__NO_CRIMINAL_PLANNING", None),
        getattr(cls, "POLICY__NO_GUNS_AND_ILLEGAL_WEAPONS", None),
        getattr(cls, "POLICY__NO_ILLEGAL_DRUGS", None),
        getattr(cls, "POLICY__NO_ENOURAGE_SELF_HARM", None),
    ]
    selected_policies = [policy for policy in policies if policy]
    kwargs: dict[str, Any] = {"on_fail": "exception"}
    if selected_policies:
        kwargs["policies"] = selected_policies
    return cls(**kwargs)


def _grounded_validator(cls: type[Any]) -> Any:
    try:
        return cls(quant=True, on_fail="exception")
    except TypeError:
        return cls(quant=True)


def _append_validator(
    validators: list[tuple[str, Any]],
    names: list[str],
    available: dict[str, type[Any]],
    name: str,
    factory: Callable[[type[Any]], Any],
) -> None:
    cls = available.get(name)
    if cls is None:
        return
    try:
        validators.append((name, factory(cls)))
        names.append(name)
    except Exception as exc:
        logger.warning("John Guardrails validator init failed: validator=%s error=%s", name, exc)


def _build_guard(guard_class: type[Any], validator: Any) -> Any:
    guard = guard_class()
    use_many = getattr(guard, "use_many", None)
    if use_many is not None:
        return use_many(validator)
    return guard.use(validator)


def _build_checks(guard_class: type[Any], validators: list[tuple[str, Any]]) -> tuple[_GuardrailCheck, ...]:
    checks: list[_GuardrailCheck] = []
    for name, validator in validators:
        try:
            checks.append(_GuardrailCheck(name=name, guard=_build_guard(guard_class, validator)))
        except Exception as exc:
            logger.warning("John Guardrails guard build failed: validator=%s error=%s", name, exc)
    return tuple(checks)


@lru_cache(maxsize=1)
def _runtime() -> _GuardrailsRuntime:
    if not GUARDRAILS_ENABLED:
        return _GuardrailsRuntime((), (), (), (), (), ())

    loaded = _load_guardrails()
    if loaded is None:
        return _GuardrailsRuntime((), (), (), (), (), ())

    guard_class, available = loaded

    input_validators: list[tuple[str, Any]] = []
    input_names: list[str] = []
    _append_validator(input_validators, input_names, available, "ProfanityFree", lambda cls: cls(on_fail="exception"))
    _append_validator(
        input_validators,
        input_names,
        available,
        "DetectPII",
        lambda cls: cls(pii_entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN", "CREDIT_CARD"], on_fail="exception"),
    )
    _append_validator(input_validators, input_names, available, "UnusualPrompt", lambda cls: cls(on_fail="exception"))

    output_validators: list[tuple[str, Any]] = []
    output_names: list[str] = []
    _append_validator(output_validators, output_names, available, "ProfanityFree", lambda cls: cls(on_fail="exception"))
    _append_validator(
        output_validators,
        output_names,
        available,
        "DetectPII",
        lambda cls: cls(pii_entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN", "CREDIT_CARD"], on_fail="exception"),
    )
    _append_validator(output_validators, output_names, available, "LlamaGuard7B", _llama_guard_validator)

    grounded_validators: list[tuple[str, Any]] = []
    grounded_names: list[str] = []
    _append_validator(grounded_validators, grounded_names, available, "GroundedAIHallucination", _grounded_validator)

    runtime = _GuardrailsRuntime(
        input_checks=_build_checks(guard_class, input_validators),
        output_checks=_build_checks(guard_class, output_validators),
        grounded_checks=_build_checks(guard_class, grounded_validators),
        input_validators=tuple(input_names),
        output_validators=tuple(output_names),
        grounded_validators=tuple(grounded_names),
    )
    logger.info(
        "John Guardrails AI initialized: input=%s output=%s grounded=%s",
        ",".join(runtime.input_validators) or "none",
        ",".join(runtime.output_validators) or "none",
        ",".join(runtime.grounded_validators) or "none",
    )
    return runtime


def _validate(
    *,
    checks: tuple[_GuardrailCheck, ...],
    text: str,
    phase: str,
    source: str,
    user_message: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    if not checks:
        logger.info("John Guardrails %s skipped: no guard configured source=%s", phase, source)
        return
    text_hash = _hash_text(text)
    for check in checks:
        try:
            outcome = check.guard.validate(text, metadata=metadata or {})
            if getattr(outcome, "validation_passed", True) is False:
                raise ValueError("validation_passed=false")
        except Exception as exc:
            if is_openai_rate_limit_error(exc):
                logger.warning(
                    "John Guardrails %s rate limited: source=%s validator=%s text_hash=%s error=%s",
                    phase,
                    source,
                    check.name,
                    text_hash,
                    exc,
                )
                raise HrOnboardingRateLimited(str(exc)) from exc

            block_message = _VALIDATOR_BLOCK_MESSAGES.get(phase, {}).get(check.name, user_message)
            logger.warning(
                "John Guardrails %s blocked: source=%s validator=%s text_hash=%s error=%s",
                phase,
                source,
                check.name,
                text_hash,
                exc,
            )
            raise HrOnboardingGuardrailsBlocked(str(exc), user_message=block_message) from exc
    logger.info(
        "John Guardrails %s passed: source=%s validators=%s text_hash=%s",
        phase,
        source,
        ",".join(check.name for check in checks),
        text_hash,
    )


def validate_onboarding_user_input(text: str, *, source: str = "chat") -> None:
    if GUARDRAILS_ENABLED:
        fast_block_message = _fast_input_block_message(text)
        if fast_block_message:
            logger.warning(
                "John Guardrails input blocked: source=%s validator=fast_local text_hash=%s",
                source,
                _hash_text(text),
            )
            raise HrOnboardingGuardrailsBlocked("fast_local_input_block", user_message=fast_block_message)
        if _is_fast_safe_hr_question(text):
            logger.info(
                "John Guardrails input passed: source=%s validators=fast_local_safe_hr text_hash=%s",
                source,
                _hash_text(text),
            )
            return

    runtime = _runtime()
    _validate(
        checks=runtime.input_checks,
        text=text,
        phase="input",
        source=source,
        user_message=INPUT_BLOCK_MESSAGE,
    )


def validate_onboarding_assistant_output(
    text: str,
    *,
    question: str,
    reference: str | None = None,
    source: str = "chat",
) -> None:
    runtime = _runtime()
    fast_block_message = _fast_output_block_message(text, reference=reference)
    if fast_block_message:
        logger.warning(
            "John Guardrails output blocked: source=%s validator=fast_local text_hash=%s",
            source,
            _hash_text(text),
        )
        raise HrOnboardingGuardrailsBlocked("fast_local_output_block", user_message=fast_block_message)

    output_checks = runtime.output_checks
    if _is_safe_grounded_policy_exchange(question=question, answer=text, reference=reference):
        output_checks = tuple(
            check
            for check in output_checks
            if check.name not in {"DetectPII", "LlamaGuard7B"}
        )

    _validate(
        checks=output_checks,
        text=text,
        phase="output",
        source=source,
        user_message=OUTPUT_BLOCK_MESSAGE,
    )
    if reference:
        _validate(
            checks=runtime.grounded_checks,
            text=text,
            phase="grounded_output",
            source=source,
            user_message=OUTPUT_BLOCK_MESSAGE,
            metadata={"query": question, "reference": reference},
        )


def warm_hr_onboarding_guardrails() -> None:
    try:
        _runtime()
    except Exception as exc:
        logger.warning("John Guardrails warmup failed: %s", exc)
