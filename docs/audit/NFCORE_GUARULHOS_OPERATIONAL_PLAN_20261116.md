# Guarulhos — composição operacional na mesma família GISS

CURRENT81914807: preparo e seleção de canal já existem; wrapper de transporte também. O entrypoint não configura Guarulhos; startup, eventos e formulário ainda contêm restrições exclusivas de Jundiaí. Os24XSD do pacote Guarulhos recuperado do portal oficial são byte a byte idênticos aos24XSD versionados de Jundiaí. Reutilizar recursos por referência e registrar hashes, sem duplicar schemas ou motor.

TARGET/escopo: parametrizar o startup revisado da família para somente3525904/3518800, manter default Jundiaí compatível, exigir município explícito no manifesto de Guarulhos, ligar o wrapper existente ao entrypoint e disponibilizar cancelamento/consulta de recuperação no mesmo Portal/Application/UoW. Pré-revisão de substituição conserva a semântica existente: cancelar original e emitir substituta separadamente; NÃO é SOAP SubstituirNfse nem confirmação atômica. Não ampliar regras tributárias ou inferir WSDL/certificado municipal.

Impacto: startup/entrypoint, builders e retornos de eventos GISS, aplicação de cancelamento compartilhada, handlers, permissões/intent recovery e formulário já existentes. Autoridades protegidas: sessão, tenant/unidade, binding, A1, número RPS, fingerprint, claim durável e arquivo. Plano de testes: manifesto errado, fonte de outra cidade, falso binding, campos assinados adulterados, HTTP até emissão/consulta/cancelamento e recuperação sem rePOST, isolamento, regressão Jundiaí, XSDs oficiais compartilhados, lint/mypy/frontend/CI e revisão independente.

Fonte primária consultada16/11: https://guarulhos.giss.com.br/giss-ajuda/desenvolvedores.html ; pacote vigente `manuais/Schemas_XSD-Servicos_Prestados.rar`; Manual Técnico Serviços Prestados V1.8. WSDL oficial exige certificado ICP-Brasil. Contratos/signer revisados devem ser provisionados pelo operador; testes sintéticos não comprovam homologação externa. Não declarar Guarulhos completo enquanto o ciclo pretendido permanecer pendente.

## Evidência local

11 testes HTTP e51 focais PASS; Ruff/Mypy421 PASS; frontend26 PASS/lint/typecheck/build. Startup compila24schemas oficiais para ambas cidades e rejeita canal/emitente divergente. E2E browser local não executado com sucesso: download do Playwright truncado; Chromium do sistema bloqueado por socket/ptrace. Três cenários novos aguardam CI completa. Suíte integral local e revisão independente em execução. Override read-only e runbook adicionados, sem provisionamento no host.

## Correções da revisão independente

Override corrigido para serviço canônico nfcore-api. Invariável de permissão dupla centralizada em FiscalIntentRecovery.allowed para prepare/validate/resume/replay/list de todas as substituições já suportadas.12 testes negativos SQLite verificam6operações e2estados; variantes PG dependem da CI.14gateway PASS incluindo fonte/nota com municípios cruzados e Barueri rejeitado pela família GISS. Prova independente HTTP200 antes de revogar ISSUE,403depois,zero dispatch. Nenhum bloqueador adicional; certificado somente após CI no novo HEAD cumulativo MF04+Guarulhos.
