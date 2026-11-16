# MF-04 — decisão tributária nacional na preparação existente

CURRENT: candidata #468 `0ebb510a`; #519 documental em revisão/gates. O domínio, fingerprint e codec já possuem `NfseNationalTaxTreatment`, mas o HTTP não fornece decisão aprovada e rejeita ISS zero/sublimite antes do preparo. Nenhuma autoridade de mercadorias deve receber CFOP/ICMS inventados para serviços.

TARGET/escopo: configurar no servidor decisões revisadas, pinadas por SHA-256 e escopo, para o canal nacional existente. Seleção exata por perfil/versão, local/serviço, tomador/retenção e vigência, sem classificação tributária inferida. Persistir proveniência no objeto/arquivo canônico e preservar replay após rotação da configuração. Ausência de configuração preserva somente o comportamento tributável anterior; configuração inválida, sem correspondência ou ambígua recusa antes da reserva/A1/rede. Não altera contratos municipais Simpliss/SP4.

Impacto: runtime de configuração, preparação HTTP, contrato/codec/fingerprint, testes HTTP/domínio, override de implantação e documentação. Mesmas sessão, permissões, unidade, numeração e arquivo. Sem migration. Política não cria catálogo normativo oficial nem comprova incidência municipal por si só: operador deve fornecer decisão fundamentada e classificações revisadas. BH integral e catálogo normativo continuam pendentes até as regras/tabelas aplicáveis serem verificadas.

Aceite: casos tributável, imunidade/não incidência/exportação e sublimite com decisão explícita; incompatibilidades rejeitadas; cadeia HTTP→arquivo→XML usa exatamente o snapshot; replay não usa política nova; payload alterado conflita; outro tenant/unidade não encontra política; versão já usada é imutável; origem SHA no fingerprint; nenhum segredo/config fiscal vindo do browser. Verificar Ruff/Mypy, testes focais e HTTP, regressão dos municípios e CI remota PG/Portal; revisão independente antes de integração.

Autorização: proprietário reafirmou conclusão interna seguida de deploy nesta conversa. A implantação só ocorrerá após integração e verificação final; emissão fiscal oficial permanece prova separada. Este plano não é conclusão do bloco.

## Evidência do incremento

Revisão independente não encontrou bloqueador no delta inicial; executou91 testes (domínio/HTTP), incluindo13 casos novos. Casos adicionais de installer, não fallback e isolamento municipal foram acrescentados depois e precisam da validação final. Nenhum EGM original executado. Arquivo/configuração/policy_id/SHA são internos; nenhuma conclusão fiscal externa inferida. Replay conserva política/perfil, mas continua exigindo binding de provider vigente — não alegar suporte à rotação do provedor por este incremento.

Complementos: revisão independente do instalador/override/runbook não encontrou bloqueador e executou6 testes adicionais PASS. Suíte focal do integrador139 PASS. Ruff e Mypy422 fontes PASS. Suíte integral local em execução; CI remota ainda necessária. O override é por instância e exige arquivos para todos os escopos nacionais servidos.
