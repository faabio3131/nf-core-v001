# NFCore V1 — NFS-e Nacional: XML autorizado em emissão e recuperação (P0)

**Data:** 2026-11-12. **Status:** IMPLEMENTADO EM BRANCH / TESTES CRIADOS / CI INTEGRADA NÃO COMPROVADA.
**Owner:** Agente B. **PR:** #454. **Dependências:** #427 (nDPS durável), #451/#456 (XSD 1.01), #450 (emissor nativo), reconciliação funcional com #446 (Agente A).
**Sem:** merge, deploy, transmissão, A1 real, migração v22, homologação ou autorização produtiva.

## Achado CURRENT no candidato #427

1. gateway/nfse_national_query.py:_validate_official_nfse() conferia raiz e infNFSe/@Id vinculados à chave retornada pelo GET nacional, mas não devolvia o XML descomprimido.
2. gateway/nfse_national_query.py:NfseNationalHomologationQueryGateway.query() devolvia apenas invoice_reference e provider_request_id. O XML que acabara de ser obtido desaparecia.
3. application/service.py:reconcile_prepared_nfse_authorization() registrava PROVIDER_RESPONSE, marcava AUTHORIZED e committava sem inserir AUTHORIZED_XML.
4. application/service.py:authorize_prepared_document() arquivava AUTHORIZED_XML somente quando o resultado era de NF-e/NFC-e (AuthorizationResult), não NFS-e (NfseAuthorizationResult).

**Risco:** estado terminal AUTHORIZED sem o documento fiscal autorizado, impedindo prova, reimpressão e custódia; a chave sozinha não basta.

## Alteração implementada

- issuance/nfe_nfse.py: NfseAuthorizationResult tem authorized_xml opcional tipado e limitado (2 MiB); somente AUTHORIZED permite esse campo; REJECTED/PENDING com XML falha fechado.
- gateway/nfse_national_query.py: _validate_official_nfse() devolve os bytes originais após descompressão limitada, parse XML e conferência da chave/Id. O GET nacional propaga esse XML para o resultado canônico, sem POST ou novo DPS.
- application/service.py: authorize_prepared_document() aceita authorized_xml de ambos os tipos de resultado fiscal e chama finalize_authorized com a mesma UoW/arquivo.
- application/service.py: reconcile_prepared_nfse_authorization() anexa AUTHORIZED_XML dentro da mesma UoW que grava estado AUTHORIZED, reserva/idempotência e PROVIDER_RESPONSE. Falha transacional impede metade do commit.
- tests/gateway/test_national_nfse_query_receipt_archive.py: conserva bytes, rejeita XML de chave divergente e teste do contrato de estados/limites.
- tests/application/test_nfse_recovered_receipt_atomicity.py: casos sintéticos de emissão direta, timeout/recovery com consulta, AUTHORIZED_XML e PROVIDER_RESPONSE uma só vez; replay não chama outra emissão/consulta.

## Limitações de evidência

Os testes construídos são **sintéticos**. O fake de recibo não tem assinatura ICP-Brasil real nem autenticação SEFIN. O gateway real consulta com mTLS e valida raiz/Id, mas a verificação de XMLDSig, schema oficial integral, vínculo de protocolo e certificação independente precisam ser implementados/verificados no gate B11 antes de considerar o fluxo internamente certificado.

O pacote XSD do ZIP oficial 1.01 precisa ser comparado byte a byte ao recurso versionado (ver dossiê de #454). A reconciliação dos arquivos e resultados com #450 e último HEAD da #446 é obrigatória: preservar as regras de elegibilidade SP/MG e o número reservado da #427; nunca copiar builder hash anterior da #446.

## Gates

- [x] Implementação da cadeia de dados sem segunda API/motor/persistência.
- [x] Testes unitários e sintéticos de replay/atômicos adicionados.
- [ ] Pytest/PG/Ruff/Mypy/CI **no HEAD integrado exato**.
- [ ] XMLDSig independente e schema completo de NFSe autorizada.
- [ ] Resposta oficial SEFIN com A1 autorizado em homologação.
- [ ] Conciliação final de #427/#450/#446 por função.
- [ ] Autorização humana separada para migration v22, merge e homologação.

**Classificação:** INTERNAL_IMPLEMENTATION_CANDIDATE / INTERNAL_CERTIFICATION_PENDING /
EXTERNAL_HOMOLOGATION_PENDING. Nunca tratar status AUTHORIZED sintético como nota emitida.


## Incremento G9 — Rejeição estruturada e evidência sem corte silencioso

Estado: IMPLEMENTED_NOT_CERTIFIED, na mesma PR #454.

Implementação: NfseRejectionDetail (code, origin, raw_message), uma coleção tipada
e ordenada NfseAuthorizationResult.rejections (máximo de 32 itens). A mensagem
crua pode conter até 32768 caracteres sem truncamento em 512. Valores maiores
falham fechado e não geram retorno supostamente válido. O resumo legado é
mantido por compatibilidade e não autoriza XML na presença de rejeições.

gateway/nfse_national_homologation.py fornece parse_national_nfse_rejections,
que interpreta todas as entradas de erros SEFIN e preserva código, origem,
ordem e texto integral. Entradas malformadas são rejeitadas sem ecoar
internals ou mensagens externas em exceções públicas.

application/service.py armazena os dados em artefato PROVIDER_RESPONSE
application/vnd.nfcore.nfse-rejection.v1+json sob escopo tenant/unidade
na mesma UoW que registra REJECTED e a chave de idempotência. Isso cobre
rejeição direta e rejeição confirmada em consulta após resultado incerto,
sem segundo POST nem segundo registro terminal no replay.

Testes novos, ainda NÃO EXECUTADOS no HEAD final de CI:
- tests/issuance/test_nfse_rejection_details.py (mensagem longa, múltiplas rejeições, invariantes).
- tests/gateway/test_nfse_national_rejections.py (JSON SEFIN completo, erros malformados, limite).
- tests/application/test_nfse_recovered_receipt_atomicity.py (rejeição direta e por consulta, arquivo e replay).

Dependência G9: conectar este parser ao gateway operacional da #450 durante
a reconciliação por função, preservando os guards SP/MG da #446 e a numeração
reservada da #427. O resultado privado não pode ser exposto integralmente
no Portal nem nos logs. A projeção web de 512 caracteres é contrato público
distinto da evidência íntegra arquivada.

LACUNA: CI integrada, E2E Portal, XSD e XMLDSig do XML autorizado permanecem
NÃO COMPROVADOS. Nenhum município é homologado por essa implementação.

DRIFT DE GOVERNANÇA: a PR #458 implementou uma primeira versão de T2 na main
após a #457. T2 confere o texto e o checklist de PR não-Draft; não certifica
execução fiscal nem E2E. O topo de AGENTS.md, que afirma T1-T6 integralmente
não implementadas, tornou-se desatualizado. Esta PR não modifica AGENTS.md
ou CI, para preservar escopo e responsabilidade.


## Checkpoint de integração CURRENT (12/11/2026, Agente B)

- Base main reconciliada: fb7cc9bcc029ba9a4d5a91c487859fd7f32b2a13.
- Integração na PR #454: merge interno bbbe380c8249df5efbc70eecd903ff3f8677bf80.
- Retarget: PR #454 em Draft para main; **não** é merge na main.
- Reconciliação seletiva: 82 arquivos exclusivos da main preservados; oito arquivos
  de conflito foram conciliados por função, preservando código WebISS de Extrema,
  serial RPS municipal, numeração DPS transacional, resposta NFS-e e segurança.
- Corrigido: prepare_nfse_authorization reserva número DPS **somente** na rota
  Nacional; na rota WebISS Extrema utiliza intenção/RPS no mesmo UoW, sem
  reservar número DPS redundante.
- Corrigido G2: domicílio nacional/estrangeiro, CPF/CNPJ/NIF/cNaoNIF no
  modelo, fingerprint imutável, codec durável e XML toma por XSD 1.01.
- Corrigido G9 candidato: erros SEFIN estruturados, código, origem e
  mensagem original íntegra, arquivamento terminal atômico e status separado.
- Evidência de teste: novos testes versionados; CI completa no SHA integrado
  **NÃO COMPROVADA** até terminar o workflow sobre main.
- Fronteiras protegidas e PR da cobertura #446 não foram modificadas.
- Migração v22: apenas código de schema; **não aplicada**. Nenhuma emissão fiscal real.
- A integração seletiva posterior com a #450 e o HEAD final da #446
  permanece pendente antes da certificação geral do P0.
