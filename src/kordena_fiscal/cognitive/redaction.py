"""Deterministic redaction applied before text leaves the process and on model output."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

_PEM = re.compile(r"-----BEGIN [A-Z ]+-----.*?(?:-----END [A-Z ]+-----|$)", re.DOTALL)
_URL_CREDENTIALS = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_KEYED_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|senha|password|csc|passwd)\b(\s*[:=]\s*)([^\s,;\"']{4,})"
)
_ACCESS_KEY = re.compile(r"(?<!\d)(?:\d[ .-]?){44}(?!\d)")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CNPJ_FORMATTED = re.compile(r"(?<!\d)\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}(?!\d)")
_CPF_FORMATTED = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")
_DIGIT_RUN = re.compile(r"(?<![\d.-])\d{11,19}(?![\d.-])")
_CARD_SPACED = re.compile(r"(?<!\d)\d{4}(?:[ -]\d{4}){2,3}(?:[ -]\d{1,4})?(?!\d)")
_PHONE = re.compile(r"(?<!\d)(?:\+?55[ -]?)?\(?\d{2}\)?[ -]?9?\d{4}[ -]?\d{4}(?!\d)")
_LONG_SECRET = re.compile(r"\b[A-Za-z0-9+/_-]{40,}={0,2}")


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def is_valid_cpf(value: str) -> bool:
    digits = _digits(value)
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    for size in (9, 10):
        total = sum(int(d) * w for d, w in zip(digits[:size], range(size + 1, 1, -1), strict=True))
        check = (total * 10) % 11 % 10
        if check != int(digits[size]):
            return False
    return True


def is_valid_cnpj(value: str) -> bool:
    digits = _digits(value)
    if len(digits) != 14 or len(set(digits)) == 1:
        return False
    for size in (12, 13):
        weights = list(range(size - 7, 1, -1)) + list(range(9, 1, -1))
        total = sum(int(d) * w for d, w in zip(digits[:size], weights, strict=False))
        check = total % 11
        check = 0 if check < 2 else 11 - check
        if check != int(digits[size]):
            return False
    return True


def is_luhn_valid(value: str) -> bool:
    digits = _digits(value)
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2 == 1:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    return total % 10 == 0


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str
    findings: tuple[str, ...]

    @property
    def redacted(self) -> bool:
        return bool(self.findings)


class Redactor:
    """Masks identifiers and secrets. Over-redaction is preferred to leakage."""

    def redact(self, text: str) -> RedactionResult:
        found: Counter[str] = Counter()

        def sub(pattern: re.Pattern[str], label: str, source: str) -> str:
            def repl(_match: re.Match[str]) -> str:
                found[label] += 1
                return f"[{label}]"

            return pattern.sub(repl, source)

        def sub_checked(
            pattern: re.Pattern[str], label: str, source: str, validator: object
        ) -> str:
            def repl(match: re.Match[str]) -> str:
                raw = match.group(0)
                if callable(validator) and validator(raw):
                    found[label] += 1
                    return f"[{label}]"
                return raw

            return pattern.sub(repl, source)

        out = text
        out = sub(_PEM, "CHAVE_PRIVADA", out)
        out = _URL_CREDENTIALS.sub(
            lambda m: (found.update(["CREDENCIAL_URL"]) or f"{m.group(1)}[CREDENCIAL_URL]@"), out
        )
        out = sub(_JWT, "TOKEN", out)
        out = sub(_BEARER, "TOKEN", out)
        out = _KEYED_SECRET.sub(
            lambda m: (found.update(["SEGREDO"]) or f"{m.group(1)}{m.group(2)}[SEGREDO]"), out
        )
        out = sub_checked(_ACCESS_KEY, "CHAVE_ACESSO", out, lambda v: len(_digits(v)) == 44)
        out = sub(_EMAIL, "EMAIL", out)
        out = sub_checked(_CARD_SPACED, "CARTAO", out, is_luhn_valid)
        out = sub_checked(_CNPJ_FORMATTED, "CNPJ", out, is_valid_cnpj)
        out = sub_checked(_CPF_FORMATTED, "CPF", out, is_valid_cpf)

        def digit_run(match: re.Match[str]) -> str:
            raw = match.group(0)
            if len(raw) == 14 and is_valid_cnpj(raw):
                found["CNPJ"] += 1
                return "[CNPJ]"
            if len(raw) == 11 and is_valid_cpf(raw):
                found["CPF"] += 1
                return "[CPF]"
            if is_luhn_valid(raw):
                found["CARTAO"] += 1
                return "[CARTAO]"
            return raw

        out = _DIGIT_RUN.sub(digit_run, out)
        out = sub_checked(
            _PHONE, "TELEFONE", out, lambda v: any(ch in v for ch in "()+ -")
        )
        out = sub(_LONG_SECRET, "SEGREDO", out)
        findings = tuple(f"{label}:{count}" for label, count in sorted(found.items()))
        return RedactionResult(text=out, findings=findings)

    def contains_sensitive(self, text: str) -> bool:
        return self.redact(text).redacted
