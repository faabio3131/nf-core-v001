# Jundiaí/SP — GissOnline V2 / ABRASF 2.04 — contratos oficiais

**Estado em 14/11/2026: AQUISIÇÃO OFICIAL PENDENTE — NÃO CERTIFICADO.**

Esta pasta documenta a **fonte oficial**, a cadeia de custódia dos documentos e
os critérios de aceite do contrato de integração. Não se encontra aqui um
WSDL/XSD certificado. Não substituir o material original por arquivos
sintéticos, de Ginfes, de terceiros ou de outra versão.

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

**Atenção:** no momento, o acesso externo ao RAR não foi completado por esta
sessão e o WSDL requer autenticação por certificado. Os arquivos, seus hashes
e as assinaturas municipais reais não foram apresentados/verificados aqui.

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

- [ ] RAR oficial e WSDL autorizado integralmente obtidos, originados, hashados.
- [ ] Arquivos XSD originais completos, incluindo `tipos-v2_04.xsd`.
- [ ] Todos os imports/includes compilam sem rede, e os 6 roots usados estão válidos.
- [ ] SOAPActions reais do WSDL coincidem com as operações implementadas.
- [ ] Exemplos reais de emissão/consulta/cancelamento/retorno validados nos XSD.
- [ ] A1, contratos, regras municipais/RTC e certificado de assinatura municipal
      conferidos nos gates do runtime, com segredos fora do Git.
- [ ] CI dos testes de contrato aprovada no HEAD exato.
- [ ] Agente B revisa independentemente a entrega; só o coordenador integra.

**Classificação:** construção técnica de verificador/contratos: implementação
interna; homologação externa real: separada. Nenhuma aprovação fiscal municipal
ou prontidão comercial implícita.

**Proibição de mascaramento:** um relatório emitido com XSD sintético é apenas
teste da ferramenta, nunca prova de origem oficial. A ausência dos bytes
oficiais mantém a pendência aberta, ainda que a CI esteja verde.
