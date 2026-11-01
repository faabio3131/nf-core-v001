from kordena_fiscal.cognitive import Redactor
from kordena_fiscal.cognitive.redaction import is_luhn_valid, is_valid_cnpj, is_valid_cpf

R = Redactor()
VALID_CNPJ = "11.222.333/0001-81"
VALID_CPF = "529.982.247-25"


def test_validators() -> None:
    assert is_valid_cnpj(VALID_CNPJ)
    assert not is_valid_cnpj("11.222.333/0001-82")
    assert is_valid_cpf(VALID_CPF)
    assert not is_valid_cpf("111.111.111-11")
    assert is_luhn_valid("4111 1111 1111 1111")
    assert not is_luhn_valid("4111 1111 1111 1112")


def test_masks_cnpj_cpf_formatted_and_plain() -> None:
    out = R.redact(f"emitente {VALID_CNPJ} cpf {VALID_CPF} plain 11222333000181 52998224725")
    assert "11.222.333" not in out.text and "529.982" not in out.text
    assert "11222333000181" not in out.text and "52998224725" not in out.text
    assert out.text.count("[CNPJ]") == 2 and out.text.count("[CPF]") == 2


def test_does_not_mask_ordinary_numbers() -> None:
    text = "NCM 84713012 cClassTrib 000001 cStat 204 numero 0000001234 serie 1 valor 1234.56"
    assert R.redact(text).text == text


def test_masks_access_key_with_and_without_separators() -> None:
    key = "3526" + "1" * 40
    spaced = " ".join(key[i : i + 4] for i in range(0, 44, 4))
    out = R.redact(f"chave {key} e {spaced}")
    assert key not in out.text and out.text.count("[CHAVE_ACESSO]") == 2


def test_masks_secrets_and_tokens() -> None:
    dashes = "-" * 5
    pem = f"{dashes}BEGIN PRIVATE KEY{dashes}\nMIIEvQIBADANBgkq\n{dashes}END PRIVATE KEY{dashes}"
    out = R.redact(
        f"{pem} Authorization: Bearer abcdef1234567890 senha=hunter2x "
        "https://user:pass@host.example/x eyJhbGciOiJI.eyJzdWIiOiIx.c2lnbmF0dXJl"
    )
    for leaked in ("MIIEvQ", "abcdef1234567890", "hunter2x", "user:pass", "eyJhbGci"):
        assert leaked not in out.text
    assert {"CHAVE_PRIVADA", "TOKEN", "SEGREDO", "CREDENCIAL_URL"} <= {
        f.split(":")[0] for f in out.findings
    }


def test_masks_email_phone_and_card() -> None:
    out = R.redact("a@b.com (11) 91234-5678 cartao 4111 1111 1111 1111")
    assert "a@b.com" not in out.text and "91234" not in out.text
    assert "4111 1111" not in out.text.replace("[CARTAO]", "")


def test_masks_long_opaque_secret() -> None:
    secret = "A" * 20 + "b" * 20 + "9" * 4
    assert secret not in R.redact(f"x {secret}").text
