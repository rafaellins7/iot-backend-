-- =============================================================================
-- Migração: Suporte a status 'gerando' e lock anti-duplicação em parecer_agronomico
-- Idempotente: seguro para rodar múltiplas vezes. Apenas adiciona colunas/índices.
-- =============================================================================

-- 1. Coluna de controle atômico de geração em andamento
ALTER TABLE parecer_agronomico 
    ADD COLUMN IF NOT EXISTS em_geracao BOOLEAN DEFAULT FALSE;

-- 2. Coluna para registro de falhas transitórias de IA (para exibir 'Tentar novamente')
ALTER TABLE parecer_agronomico 
    ADD COLUMN IF NOT EXISTS erro_geracao TEXT;

-- 3. Índices de performance para verificação instantânea de lock e hash de entrada
CREATE INDEX IF NOT EXISTS idx_parecer_agronomico_lote_status 
    ON parecer_agronomico (fk_lote_id_lote, status);

CREATE INDEX IF NOT EXISTS idx_parecer_agronomico_hash 
    ON parecer_agronomico (fk_lote_id_lote, hash_entrada);
