# FIS-03 — contrato de recibo nacional (16/11/2026)

CURRENT auditado: main 549ab3c0; #468 ab93ef0d; #514 bfd5d0d4 e #515 9cfe2e07 ainda não integradas. Base deste incremento: 9cfe2e074743879dfafdc14998bb0107720989a6. Revisão independente reproduziu XML assinado incompleto aceito e NFSe NT009 válida com DPS assinada recusada.

TARGET e escopo congelado: POST/GET nacional só autorizam com XSD NFSe NT009 pinado, assinatura externa, correlação da DPS/CNPJ/município/ambiente/série/número com identidade canônica, assinatura DPS opcional validada quando presente e idDps do envelope coerente. Reusar autoridade existente de numeração e de criptografia; manter contrato Simpliss independente. Atualizar consumidores de XML arquivado nacionais. Não introduzir fallback entre perfis.

Impacto: builder/identificador DPS; verificador de recibo; adaptadores nacional POST/GET e transporte de baixo nível; preflights nacionais na aplicação; import municipal do núcleo de integridade; fixtures sintéticas completas e regressões. Protegidos: RBAC, tenant/unidade, claim/idempotência, A1, numeração durável e contratos HTTP. Nenhuma migration ou mudança de endpoint.

Aceite: nenhum AUTHORIZED em recibo incompleto, outra identidade, assinatura adulterada ou perfil sem suporte. GET divergente não causa rePOST. Assinatura DPS legal não bloqueia recibo. Bytes verificados preservados. Simpliss/eventos não regridem. Ruff/Mypy/testes focais/integral/CI e revisão independente no delta final.

Limites separados: consulta histórica sem perfil/proveniência persistido permanece fail-closed quando incompatível; pacote nacional legado local não fornece NFSe XSD. Trust store ICP/SEFIN, cadeia, revogação e validade histórica continuam pendentes. Este incremento não é homologação externa nem fechamento comercial.


Revisão independente detectou e corrigiu validação de identidade depois de exchange no transporte baixo nível; agora precede TLS/rede e há regressão de zero chamadas. Também detectou chave NFSe de outro CNPJ/município apesar de DPS correta. Correlação adicionada segundo TSIdNFSe do pacote pinado e Guia do Emissor Nacional, seção9.1: município emissor, ambGer, tipo inscrição2=CNPJ e CNPJ. Conferir também município no endereço do emitente. ambGer não é tpAmb. Fonte: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/guia-emissorpubliconacionalweb_snnfse-ern-v12.pdf . Cálculo de DV e correlação de número/data codificados na chave não são certificados por este incremento.


Revisão independente final do delta: nenhum bloqueador remanescente identificado após correções. Revisor executou 122 testes focais e 24 HTTP com PYTHONPATH=src, incluindo nacional, eventos, Simpliss e composição. Integrador executou 148 focais, Ruff e Mypy418 fontes. Certificação remota depende do HEAD publicado/CI; suíte integral final4677 PASS/521 SKIP por ausência de DSN PostgreSQL local,2 avisos de depreciação.36 testes antigos de recibo reexecutados com contexto completo PASS. Ruff/Mypy finais PASS; governança do plano59 tarefas PASS. Testes negativos antigos passam contexto válido para não obter falso positivo apenas por ausência de contexto.


## Complemento de certificação — dependência de telemetria, 16/11/2026

CURRENT: #516 HEAD7a6ee50f3f88d3238abef76d4f3d6872725f58b5, CI43918215893 SUCCESS com5195 Python PASS/3 SKIP e71 E2E PASS. O workflow instala apenas o extra dev; dois módulos de teste SDK/OTLP são pulados por importorskip. O terceiro skip é a variante SQLite de um teste que exige composição PostgreSQL. A atribuição anterior dos521 skips locais exclusivamente a PostgreSQL era imprecisa: telemetria e Docker também têm condições de skip.

TARGET/escopo congelado: instalar os extras canônicos dev e telemetry no mesmo job e exibir motivos de skip com pytest -ra. Autoridade: pyproject.toml, extra telemetry já existente; sem nova dependência de produto ou segundo pipeline. Impacto restrito ao workflow e evidência documental. Nenhuma alteração fiscal, de autenticação, tenant, migração ou deploy.

Aceite/gates: testes reais SDK e OTLP/HTTP executam sem skip; todos os gates da CI do novo HEAD passam; motivos restantes ficam explícitos. Não remover skip válido da variante SQLite. Validar os dois testes existentes localmente, revisar o diff e executar CI integral remota. Até isso ocorrer, a CI antiga não certifica o novo HEAD.

Achado ao ativar os testes: TracerProvider() herda sampler do ambiente; nesta execução forneceu ParentBasedTraceIdRatio e produziu NonRecordingSpan, causando falha intermitente de len(spans). Escopo complementar justificado: fixar ALWAYS_ON apenas nos dois testes SDK/HTTP para validar exportação determinística; preservar amostragem de produção. Isso não enfraquece assertivas de redaction, duração ou exportação.

Validação do complemento: dois testes reais PASS sem skips; repetição com OTEL_TRACES_SAMPLER=always_off também2 PASS, comprovando independência da configuração externa. Ruff nos dois testes e git diff --check PASS; plano canônico59 tarefas PASS. Nova CI integral necessária após publicação; nenhuma certificação por antecipação. Monitor horário somente leitura ativo para novas conclusões das PRs515/516 e candidata468.
