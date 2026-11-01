"""Rejection knowledge base.

Entries are a curated *seed* and are labelled ``PENDING_NORMATIVE_REVIEW``: they must be
reviewed by a human against the official rejection table (with artifact SHA-256) before
being promoted to ``REVIEWED``. Unknown codes never receive an invented explanation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from kordena_fiscal.domain import FiscalValidationError

from ..contracts import stable_hash

_CODE = re.compile(r"^\d{3,4}$")
_SOURCE = (
    "Tabela oficial de códigos de rejeição do Manual de Orientação do Contribuinte — "
    "conferir a versão vigente antes de decidir."
)


class ReviewStatus(StrEnum):
    PENDING_NORMATIVE_REVIEW = "pending_normative_review"
    REVIEWED = "reviewed"


@dataclass(frozen=True, slots=True)
class RejectionEntry:
    code: str
    title: str
    meaning: str
    typical_causes: tuple[str, ...]
    suggested_checks: tuple[str, ...]
    review_status: ReviewStatus = ReviewStatus.PENDING_NORMATIVE_REVIEW
    source_ref: str = _SOURCE

    def __post_init__(self) -> None:
        if not _CODE.match(self.code):
            raise FiscalValidationError("rejection code must have 3 or 4 digits")
        if not (self.title and self.meaning and self.typical_causes and self.suggested_checks):
            raise FiscalValidationError("rejection entry is incomplete")


class RejectionKnowledgeBase:
    def __init__(self, entries: Iterable[RejectionEntry], *, version: str) -> None:
        self._entries: dict[str, RejectionEntry] = {}
        for entry in entries:
            if entry.code in self._entries:
                raise FiscalValidationError(f"duplicate rejection code {entry.code}")
            self._entries[entry.code] = entry
        self.version = version
        self.fingerprint = stable_hash(
            [
                [e.code, e.title, e.meaning, list(e.typical_causes), list(e.suggested_checks),
                 e.review_status.value]
                for e in sorted(self._entries.values(), key=lambda e: e.code)
            ]
        )

    def lookup(self, raw_code: str) -> RejectionEntry | None:
        return self._entries.get(raw_code.strip())

    def __len__(self) -> int:
        return len(self._entries)


_SEED: tuple[RejectionEntry, ...] = (
    RejectionEntry(
        "204",
        "Duplicidade de NF-e",
        "A SEFAZ já possui documento autorizado com a mesma chave de acesso.",
        (
            "Reenvio de um documento que já havia sido autorizado.",
            "A resposta anterior se perdeu (timeout) e o documento foi enviado de novo.",
        ),
        (
            "Consultar a situação do documento pela chave de acesso antes de qualquer novo envio.",
            "Verificar na conciliação se há resultado desconhecido pendente para este documento.",
            "Não gerar novo número sem confirmar que o documento anterior não foi autorizado.",
        ),
    ),
    RejectionEntry(
        "539",
        "Duplicidade de NF-e com diferença na chave de acesso",
        "Já existe documento com o mesmo emitente, série e número, mas com chave diferente.",
        (
            "Nova tentativa com a mesma numeração após envio anterior sem retorno confirmado.",
            "Dados que compõem a chave (data, código numérico) mudaram entre as tentativas.",
        ),
        (
            "Consultar o documento anterior e confirmar seu estado.",
            "Revisar o controle de numeração e a idempotência das tentativas de emissão.",
        ),
    ),
    RejectionEntry(
        "206",
        "NF-e já está inutilizada",
        "A numeração informada consta como inutilizada na base da SEFAZ.",
        ("Reuso de um número que já foi inutilizado.",),
        (
            "Revisar o controle de numeração da série.",
            "Usar a próxima numeração válida, confirmada pelo responsável fiscal.",
        ),
    ),
    RejectionEntry(
        "225",
        "Falha no schema XML",
        "O XML enviado não respeita o leiaute (XSD) da versão em uso.",
        (
            "Campo obrigatório ausente ou com formato inválido.",
            "Campo novo introduzido por Nota Técnica ainda não tratado.",
        ),
        (
            "Validar o XML contra o XSD da versão vigente do leiaute.",
            "Ler a mensagem detalhada do validador para localizar o campo.",
        ),
    ),
    RejectionEntry(
        "228",
        "Data de emissão muito atrasada",
        "A data de emissão está fora do prazo aceito em relação ao momento do recebimento.",
        (
            "Documento criado e transmitido com atraso (fila parada ou contingência).",
            "Relógio ou fuso horário incorreto no emissor.",
        ),
        (
            "Conferir data/hora e fuso de emissão do documento.",
            "Verificar o estado da fila de transmissão e da contingência.",
        ),
    ),
    RejectionEntry(
        "301",
        "Uso denegado por irregularidade fiscal do emitente",
        "A SEFAZ denegou o uso do documento por situação cadastral ou fiscal do emitente.",
        ("Pendência cadastral ou fiscal do emitente junto à SEFAZ.",),
        (
            "Acionar o contador responsável para regularizar a situação do emitente.",
            "Não retransmitir repetidamente enquanto a pendência existir.",
        ),
    ),
    RejectionEntry(
        "656",
        "Consumo indevido",
        "O serviço da SEFAZ bloqueou temporariamente por excesso de consultas.",
        ("Consultas repetidas em intervalo curto.",),
        (
            "Respeitar o intervalo mínimo entre consultas e aplicar espera progressiva.",
            "Reduzir a frequência de consulta de status.",
        ),
    ),
    RejectionEntry(
        "108",
        "Serviço paralisado momentaneamente",
        "O serviço do autorizador está indisponível por curto período.",
        ("Instabilidade ou manutenção do autorizador.",),
        (
            "Aguardar e tentar novamente conforme a política de retentativa.",
            "Avaliar contingência conforme a política fiscal da unidade.",
        ),
    ),
    RejectionEntry(
        "109",
        "Serviço paralisado sem previsão",
        "O serviço do autorizador está indisponível sem previsão de retorno.",
        ("Indisponibilidade prolongada do autorizador.",),
        (
            "Consultar o status oficial do autorizador.",
            "Avaliar contingência conforme a política fiscal da unidade.",
        ),
    ),
    RejectionEntry(
        "280",
        "Certificado transmissor inválido",
        "O certificado digital usado na transmissão não foi aceito.",
        (
            "Certificado inválido, revogado ou com cadeia incompleta.",
            "Certificado de outro titular usado na unidade errada.",
        ),
        (
            "Verificar o certificado A1 da unidade no cofre (sem exibir o conteúdo).",
            "Confirmar com o responsável se há substituição de certificado em andamento.",
        ),
    ),
    RejectionEntry(
        "281",
        "Certificado transmissor com validade vencida",
        "O certificado digital usado na transmissão está fora da validade.",
        ("Certificado expirado sem renovação.",),
        (
            "Conferir a data de validade do certificado A1 da unidade.",
            "Providenciar a renovação e a substituição governada no cofre.",
        ),
    ),
    RejectionEntry(
        "778",
        "NCM inexistente",
        "O NCM informado não consta na tabela vigente.",
        (
            "NCM digitado incorretamente no cadastro do produto.",
            "NCM descontinuado ou ainda não vigente na data da emissão.",
        ),
        (
            "Revisar o NCM do produto na tabela vigente à data de emissão.",
            "Pedir confirmação ao contador antes de alterar o cadastro.",
        ),
    ),
)


def default_rejection_knowledge_base() -> RejectionKnowledgeBase:
    return RejectionKnowledgeBase(_SEED, version="rejections.seed/2026-10-31")
