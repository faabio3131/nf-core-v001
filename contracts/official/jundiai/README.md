# Jundiaí/SP — GissOnline V2 / ABRASF 2.04 — contratos oficiais

**Estado em 14/11/2026: XSDs oficiais adquiridos e versionados (24/24); WSDL autenticado mTLS e CI integral do HEAD final ainda pendentes. Sem homologação municipal.**

Esta pasta documenta a **fonte oficial**, a cadeia de custódia dos documentos e
os critérios de aceite do contrato de integração. O pacote original dos **24 XSDs**
já está preservado em `giss_v2_04/xsd/Schemas_XSD-Servicos_Prestados/`, com
integridade individual em `giss_v2_04/manifest.json` e compilação em
`giss_v2_04/schema-validation.json`. O RAR oficial da fonte pública foi obtido
por HTTPS e auditado (SHA-256 `c14a542de5fa2ce1a6a2b43da6e4eb0bebab12e6ebc850fe24dbdc8f6bb04356`).
**O WSDL autenticado ainda NÃO foi obtido**, portanto não inventar SOAPActions,
interfaces municipais nem equivalência de substituição. Não substituir schemas
originais por versões sintéticas ou de outros provedores.

## Fontes primárias verificadas

- Desenvolvedores Jundiaí (fonte municipal): https://jundiai.giss.com.br/giss-ajuda/desenvolvedores.html
- Distribuição XSD **vigente** para serviços prestados:
  https://jundiai.giss.com.br/giss-ajuda/manuais/Schemas_XSD-Servicos_Prestados.rar
- Manual técnico Serviços Prestados V1.8:
  https://jundiai.giss.com.br/giss-ajuda/manuais/Manual%20T%C3%A9cnico%20-%20Servi%C3%A7os%20Prestados%20-%20V1.8.pdf
- WSDL oficial de homologação (leitura com certificado ICP-Brasil pelo handshake mTLS):
  https://v2-ws-homologacao.giss.com.br/service-ws/nf/nfse-ws?wsdl

O manual indica ABRASF 2.04 com extensões RTC, TLS 1.2 e seis métodos:
`CancelarNfse`, `RecepcionarLoteRps`, `ConsultarLoteRps`,
`ConsultarNfsePorFaixa`, `ConsultarNfsePorRps` e
`ConsultarNfseServicoPrestado`. Os quatro métodos integrados no adaptador
não tornam os demais métodos do WSDL automaticamente implementados.

**Atenção:** o pacote XSD e seus hashes foram adquiridos e conferidos pela auditoria
independente em `docs/audit/JUNDIAI_GISS_OFFICIAL_20261114.md` e seu workflow.
O WSDL de homologação retornou HTTP 400 sem o certificado ICP-Brasil/mTLS.
Não há SOAPActions reais capturados nem XML assinado emitido pelo município.
O método de **substituição atômica** permanece não comprovado; o código atual
implementa somente cancelamento verificado seguido de nova emissão, como
processos separados, e não declara equivalência municipal.

## Coleta em ambiente autorizado

1. Baixar a distribuição RAR **diretamente do link oficial**. Arquivar URL,
   data de coleta, tamanho e SHA-256 do RAR original. Extrair os arquivos
   `.xsd` para diretório de auditoria, preservando seus nomes oficiais.
2. Em computador autorizado, acessar o WSDL de homologação com certificado
   ICP-Brasil **sem copiar a chave privada para repositório, chat, CI ou logs**.
   Salvar a resposta XML bruta como `nfse.wsdl`, sem transformações.
   Este passo é apenas leitura; não transmite nenhuma NFS-e.
3. Conferir existência do `tipos-v2_04.xsd` e da cadeia `include/import`.
   Todas as dependências XSD devem vir da **mesma distribuição oficial**;
   não aceitar downloads automáticos ou paths remotos durante validação.
4. Executar o verificador offline de engenharia, por exemplo:

   ```bash
   python scripts/verify_jundiai_giss_official_contracts.py \
     --wsdl /auditoria/jundiai/nfse.wsdl \
     --xsd-dir /auditoria/jundiai/xsd \
     --source-rar /auditoria/jundiai/Schemas_XSD-Servicos_Prestados.rar \
     --report /auditoria/jundiai/contrato-auditado-20261114.json
   ```

5. Conferir o JSON: `wsdl_sha256`, `source_rar_sha256`,
   `xsd_resources`, `xsd_package_sha256`, `xsd_roots`,
   `method_actions`, `service_namespace`, versão e
   `all_operation_xsd_compilation`. Auditoria independente deve confirmar
   origem e contemporaneidade (o relatório registra
   `source_authenticity=requires_independent_review`).
6. Preservar **WSDL/XSD oficiais e seus hashes** no armazenamento versionado
   e autorizado da FM Tecnologia conforme licenças/restrições do provedor.
   Registrar ponteiro imutável e hashes na PR. Somente incluir os arquivos
   completos no repositório caso o contrato/licença e a classificação
   permitam; não registrar certificado privado nem segredos.
7. Com material oficial acessível, reconciliar os layouts XML, SOAPAction,
   versão, documentação e assinatura municipal com
   `src/kordena_fiscal/runtime/jundiai_environment.py`. O startup já exige
   referências locais hash-pinned, certificado **público** municipal revisado,
   regras tributárias de emitente e A1 do cofre existente.

## Gates para entrega do Agente A ao Agente B

- [x] RAR oficial obtido por HTTPS, 24 XSDs pinados e SHA-256 registrado.
- [ ] WSDL autorizado mTLS integralmente obtido, verificado e hashado.
- [x] Arquivos XSD originais completos, incluindo `tipos-v2_04.xsd`.
- [x] 24 imports/includes compilados sem rede; emissão/consulta/cancelamento
      verificados em cinco payloads de engenharia contra os XSDs originais.
- [ ] SOAPActions reais do WSDL coincidem com as operações implementadas.
- [ ] Exemplos assinados reais de emissão/consulta/cancelamento/retorno do fornecedor
      (os cinco exemplos de engenharia auditados não são respostas municipais reais).
- [ ] A1, contratos, regras municipais/RTC e certificado de assinatura municipal
      conferidos nos gates do runtime, com segredos fora do Git.
- [ ] CI dos testes de contrato aprovada no HEAD exato.
- [ ] Agente B revisa independentemente a entrega; só o coordenador integra.

**Classificação:** construção técnica de verificador/contratos: implementação
interna; homologação externa real: separada. Nenhuma aprovação fiscal municipal
ou prontidão comercial implícita.

**Proibição de mascaramento:** os XSDs deste pacote são oficiais e hash-pinned,
mas uma CI verde não comprova WSDL/SOAPAction via mTLS, resposta real de Jundiaí,
certificação de assinatura municipal, homologação externa ou substituição atômica.
