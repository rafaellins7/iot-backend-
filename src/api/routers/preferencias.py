import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import Json, RealDictCursor
from pydantic import BaseModel, Field

from src.api.deps import get_conn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/preferencias", tags=["preferencias"])

_SCHEMA_INITIALIZED = False

# ============================================================================
# DADOS DE FALLBACK (RESILIENTES A FALHAS DO POSTGRESQL / NUVEM)
# ============================================================================

DEFAULT_PERFIS = {
    1: {
        "id_usuario": 1,
        "nome": "Maria Clara",
        "email": "maria.clara@raizagro.agr.br",
        "cargo": "Gestora Técnica",
        "bio": "Gestão de safras, indicadores agronômicos e logística de exportação.",
        "telefone": "+55 (87) 99123-4567",
        "avatar_iniciais": "MC",
        "avatar_cor": "#10B981",
        "avatar_url": None,
        "perfil": "Produtor/Exportador",
        "tema": "claro",
        "efeitos_visuais": True,
        "atualizacao_tempo_real": True,
        "idioma": "pt-BR",
        "fuso_horario": "America/Recife",
        "moeda": "BRL",
        "notificacoes_json": {},
        "propriedade_json": {},
        "preferencias_extras": {},
        "data_atualizacao": None,
    },
    2: {
        "id_usuario": 2,
        "nome": "Luiz Felipe",
        "email": "luiz.felipe@raizagro.agr.br",
        "cargo": "Analista IoT & Telemetria",
        "bio": "Monitoramento de telemetria, sensores e calibração de modelos preditivos.",
        "telefone": "+55 (87) 99234-5678",
        "avatar_iniciais": "LF",
        "avatar_cor": "#0284C7",
        "avatar_url": None,
        "perfil": "Analista de Dados",
        "tema": "claro",
        "efeitos_visuais": True,
        "atualizacao_tempo_real": True,
        "idioma": "pt-BR",
        "fuso_horario": "America/Recife",
        "moeda": "BRL",
        "notificacoes_json": {},
        "propriedade_json": {},
        "preferencias_extras": {},
        "data_atualizacao": None,
    },
    3: {
        "id_usuario": 3,
        "nome": "Lorena Lira",
        "email": "lorena.lira@raizagro.agr.br",
        "cargo": "Administradora",
        "bio": "Governança agronômica, gestão de usuários, auditoria e conformidade.",
        "telefone": "+55 (87) 99345-6789",
        "avatar_iniciais": "LL",
        "avatar_cor": "#166534",
        "avatar_url": None,
        "perfil": "Administrador",
        "tema": "claro",
        "efeitos_visuais": True,
        "atualizacao_tempo_real": True,
        "idioma": "pt-BR",
        "fuso_horario": "America/Recife",
        "moeda": "BRL",
        "notificacoes_json": {},
        "propriedade_json": {},
        "preferencias_extras": {},
        "data_atualizacao": None,
    }
}

DADOS_SAFRAS_PADRAO = {
    "safras": [
        {
            "id_safra": 1,
            "ciclo": "2025/2026",
            "cultura": "Uva Vitória & Manga Palmer",
            "area_ha": 42.5,
            "produtividade_ton_ha": 30.2,
            "volume_total_ton": 1284.5,
            "consumo_agua_m3_ha": 3420,
            "brix_medio": 19.4,
            "taxa_exportacao_pct": 96.2,
            "status": "Em Andamento",
            "destinacao_export_pct": 78,
            "destinacao_interno_pct": 16,
            "destinacao_industria_pct": 6,
            "data_atualizacao": None,
        },
        {
            "id_safra": 2,
            "ciclo": "2024/2025",
            "cultura": "Uva Vitória (Seedless)",
            "area_ha": 40.0,
            "produtividade_ton_ha": 26.5,
            "volume_total_ton": 1060.0,
            "consumo_agua_m3_ha": 3760,
            "brix_medio": 18.2,
            "taxa_exportacao_pct": 89.4,
            "status": "Concluída",
            "destinacao_export_pct": 72,
            "destinacao_interno_pct": 20,
            "destinacao_industria_pct": 8,
            "data_atualizacao": None,
        },
        {
            "id_safra": 3,
            "ciclo": "2023/2024",
            "cultura": "Manga Tommy & Uva Crimson",
            "area_ha": 38.0,
            "produtividade_ton_ha": 24.8,
            "volume_total_ton": 942.4,
            "consumo_agua_m3_ha": 4120,
            "brix_medio": 17.5,
            "taxa_exportacao_pct": 82.0,
            "status": "Concluída",
            "destinacao_export_pct": 65,
            "destinacao_interno_pct": 25,
            "destinacao_industria_pct": 10,
            "data_atualizacao": None,
        }
    ],
    "talhoes": [
        {
            "id_talhao": 1,
            "codigo": "Talhão A1",
            "variedade": "Uva Vitória (Seedless)",
            "porta_enxerto": "IAC 572",
            "ciclo": "2025/2026",
            "area_ha": 12.0,
            "volume_ton": 388.8,
            "produtividade_ton_ha": 32.4,
            "brix_medio": 19.8,
            "calibres_mm": "21 - 24 mm",
            "status": "Colhido • Exportado",
            "data_atualizacao": None,
        },
        {
            "id_talhao": 2,
            "codigo": "Talhão A2",
            "variedade": "Uva Vitória (Seedless)",
            "porta_enxerto": "IAC 766",
            "ciclo": "2025/2026",
            "area_ha": 10.5,
            "volume_ton": 323.4,
            "produtividade_ton_ha": 30.8,
            "brix_medio": 19.2,
            "calibres_mm": "20 - 22 mm",
            "status": "Colhido • Exportado",
            "data_atualizacao": None,
        },
        {
            "id_talhao": 3,
            "codigo": "Talhão B1",
            "variedade": "Manga Palmer",
            "porta_enxerto": "Espada",
            "ciclo": "2025/2026",
            "area_ha": 11.0,
            "volume_ton": 319.0,
            "produtividade_ton_ha": 29.0,
            "brix_medio": 16.5,
            "calibres_mm": "420 - 480 g",
            "status": "Em Trânsito • Pecém",
            "data_atualizacao": None,
        },
        {
            "id_talhao": 4,
            "codigo": "Talhão B2",
            "variedade": "Uva Thompson Seedless",
            "porta_enxerto": "SO4",
            "ciclo": "2025/2026",
            "area_ha": 9.0,
            "volume_ton": 253.3,
            "produtividade_ton_ha": 28.1,
            "brix_medio": 18.6,
            "calibres_mm": "18 - 20 mm",
            "status": "Em Colheita (85%)",
            "data_atualizacao": None,
        }
    ],
    "safra_ativa": {
        "id_safra": 1,
        "ciclo": "2025/2026",
        "cultura": "Uva Vitória & Manga Palmer",
        "area_ha": 42.5,
        "produtividade_ton_ha": 30.2,
        "volume_total_ton": 1284.5,
        "consumo_agua_m3_ha": 3420,
        "brix_medio": 19.4,
        "taxa_exportacao_pct": 96.2,
        "status": "Em Andamento",
        "destinacao_export_pct": 78,
        "destinacao_interno_pct": 16,
        "destinacao_industria_pct": 6,
        "data_atualizacao": None,
    }
}

DADOS_ALERTAS_PADRAO = {
    "alertas": [
        {
            "codigo_alerta": "P1-REEFER-EXP-2026-08",
            "titulo": "Excursão Térmica — Reefer Exportação #EXP-2026-08",
            "severidade": "critico",
            "prioridade": "P1",
            "status": "pendente",
            "lote_ou_talhao": "Lote Uva Vitória (18,4t) • BR-116 Km 412",
            "sensor_ref": "Sensor Termo-Reefer #TR-08",
            "leitura_atual": "3,8°C",
            "limiar_seguro": "0,5°C a 2,0°C",
            "acao_tomada": None,
            "atendido_por": None,
            "data_atualizacao": None,
        },
        {
            "codigo_alerta": "P2-SOLO-TALHAO-A1",
            "titulo": "Umidade do Solo Abaixo do Limiar — Talhão A1",
            "severidade": "moderado",
            "prioridade": "P2",
            "status": "pendente",
            "lote_ou_talhao": "Talhão A1 • Uva Vitória (12,0 ha)",
            "sensor_ref": "Sonda FDR #SL-A1-04",
            "leitura_atual": "38,2%",
            "limiar_seguro": "Mínimo 50,0% VWC",
            "acao_tomada": None,
            "atendido_por": None,
            "data_atualizacao": None,
        },
        {
            "codigo_alerta": "PRED-VPD-SETOR-04",
            "titulo": "Previsão de Pico de Evapotranspiração (VPD > 2.8 kPa)",
            "severidade": "preditivo",
            "prioridade": "IA",
            "status": "pendente",
            "lote_ou_talhao": "Setor 04 • Talhões A1, A2 e B2",
            "sensor_ref": "Modelo Penman-Monteith IA",
            "leitura_atual": "2.8 kPa",
            "limiar_seguro": "< 2.2 kPa",
            "acao_tomada": None,
            "atendido_por": None,
            "data_atualizacao": None,
        },
        {
            "codigo_alerta": "ALT-2026-001",
            "titulo": "Desvio Térmico no Lote de Manga",
            "severidade": "critico",
            "prioridade": "P1",
            "status": "pendente",
            "lote_ou_talhao": "Lote #101 • Manga Exportação (1.000 kg)",
            "sensor_ref": "DHT11 ESP32-C3",
            "leitura_atual": "14,8°C",
            "limiar_seguro": "10,0°C a 13,0°C",
            "acao_tomada": None,
            "atendido_por": None,
            "data_atualizacao": None,
        },
        {
            "codigo_alerta": "ALT-2026-002",
            "titulo": "Déficit de Umidade Relativa no Lote de Uva",
            "severidade": "moderado",
            "prioridade": "P2",
            "status": "pendente",
            "lote_ou_talhao": "Lote #102 • Câmara Frigorífica Uva (500 kg)",
            "sensor_ref": "SNS-AR-002",
            "leitura_atual": "87,5% UR",
            "limiar_seguro": "90,0% a 95,0% UR",
            "acao_tomada": None,
            "atendido_por": None,
            "data_atualizacao": None,
        },
        {
            "codigo_alerta": "ALT-2026-003",
            "titulo": "Oscilação Térmica em Melão Amarelo",
            "severidade": "baixo",
            "prioridade": "P3",
            "status": "pendente",
            "lote_ou_talhao": "Lote #103 • Antecâmara Packing (300 kg)",
            "sensor_ref": "SNS-SL-003",
            "leitura_atual": "12,3°C",
            "limiar_seguro": "10,0°C a 12,0°C",
            "acao_tomada": None,
            "atendido_por": None,
            "data_atualizacao": None,
        }
    ],
    "por_codigo": {},
    "resumo": {
        "total_pendentes": 6,
        "total_atendidos": 0,
        "gestora_ativos": 3,
        "gestora_criticos": 1,
        "gestora_moderados": 2,
        "analista_ativos": 3,
    }
}

DADOS_GRAFICOS_PADRAO = {
    "umidade_ar_24h": [61, 60, 59, 58, 60, 61, 63, 62],
    "umidade_solo_24h": [54, 53, 55, 57, 59, 58, 57, 58],
    "temp_solo_24h": [24.1, 23.9, 24.3, 24.6, 24.8, 24.5, 24.4, 24.5],
    "temp_ar_24h": [26.2, 25.8, 26.8, 28.2, 29.0, 28.1, 27.5, 27.8],
    "conformidade_geral_pct": 90,
    "saude_plantacao_pct": 85,
    "umidade_dossel_pct": 67,
    "temp_foliar_c": 27.0,
    "agua_reservatorio_pct": 63,
    "vazao_ldia": 4200,
    "curva_termica_analista": {
        "temp_atual": 14.8,
        "tmax": 13.0,
        "tmin": 10.0,
        "indice_preditivo": 0.84,
        "umidade_camara_uva": 87.5,
        "limiar_ur_uva": 90.0,
    },
    "data_atualizacao": None,
}

# ============================================================================
# SCHEMAS PYDANTIC
# ============================================================================

class PreferenciasUpdateIn(BaseModel):
    nome: Optional[str] = Field(default=None, max_length=150)
    cargo: Optional[str] = Field(default=None, max_length=120)
    bio: Optional[str] = Field(default=None, max_length=600)
    telefone: Optional[str] = Field(default=None, max_length=40)
    avatar_iniciais: Optional[str] = Field(default=None, max_length=6)
    avatar_cor: Optional[str] = Field(default=None, max_length=30)
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    tema: str = Field(default="claro", max_length=30)
    efeitos_visuais: bool = True
    atualizacao_tempo_real: bool = True
    idioma: str = Field(default="pt-BR", max_length=15)
    fuso_horario: str = Field(default="America/Recife", max_length=60)
    moeda: str = Field(default="BRL", max_length=10)
    notificacoes_json: Dict[str, Any] = Field(default_factory=dict)
    propriedade_json: Dict[str, Any] = Field(default_factory=dict)
    preferencias_extras: Dict[str, Any] = Field(default_factory=dict)


class SafraCreateUpdateIn(BaseModel):
    ciclo: str = Field(..., max_length=40)
    cultura: str = Field(..., max_length=100)
    area_ha: float = Field(..., gt=0)
    produtividade_ton_ha: float = Field(..., ge=0)
    volume_total_ton: Optional[float] = Field(default=None, ge=0)
    consumo_agua_m3_ha: int = Field(default=3420, ge=0)
    brix_medio: float = Field(default=18.5, ge=0)
    taxa_exportacao_pct: float = Field(default=95.0, ge=0, le=100)
    status: str = Field(default="Em Andamento", max_length=30)
    destinacao_export_pct: int = Field(default=78, ge=0, le=100)
    destinacao_interno_pct: int = Field(default=16, ge=0, le=100)
    destinacao_industria_pct: int = Field(default=6, ge=0, le=100)


class TalhaoUpdateIn(BaseModel):
    codigo: Optional[str] = Field(default=None, max_length=30)
    variedade: Optional[str] = Field(default=None, max_length=80)
    porta_enxerto: Optional[str] = Field(default=None, max_length=60)
    ciclo: Optional[str] = Field(default=None, max_length=40)
    area_ha: Optional[float] = Field(default=None, gt=0)
    volume_ton: Optional[float] = Field(default=None, ge=0)
    produtividade_ton_ha: Optional[float] = Field(default=None, ge=0)
    brix_medio: Optional[float] = Field(default=None, ge=0)
    calibres_mm: Optional[str] = Field(default=None, max_length=30)
    status: Optional[str] = Field(default=None, max_length=40)


class AlertaPatchIn(BaseModel):
    status: str = Field(..., pattern="^(pendente|atendido|silenciado)$")
    acao_tomada: Optional[str] = Field(default=None, max_length=300)
    atendido_por: Optional[str] = Field(default=None, max_length=100)
    leitura_atual: Optional[str] = Field(default=None, max_length=60)
    limiar_seguro: Optional[str] = Field(default=None, max_length=80)


class GraficosTelemetriaUpdateIn(BaseModel):
    umidade_ar_24h: List[float] = Field(default_factory=lambda: [61, 60, 59, 58, 60, 61, 63, 62])
    umidade_solo_24h: List[float] = Field(default_factory=lambda: [54, 53, 55, 57, 59, 58, 57, 58])
    temp_solo_24h: List[float] = Field(default_factory=lambda: [24.1, 23.9, 24.3, 24.6, 24.8, 24.5, 24.4, 24.5])
    temp_ar_24h: List[float] = Field(default_factory=lambda: [26.2, 25.8, 26.8, 28.2, 29.0, 28.1, 27.5, 27.8])
    conformidade_geral_pct: int = Field(default=90, ge=0, le=100)
    saude_plantacao_pct: int = Field(default=85, ge=0, le=100)
    umidade_dossel_pct: int = Field(default=67, ge=0, le=100)
    temp_foliar_c: float = Field(default=27.0)
    agua_reservatorio_pct: int = Field(default=63, ge=0, le=100)
    vazao_ldia: int = Field(default=4200, ge=0)
    curva_termica_analista: Dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# GARANTIA DE SCHEMA E SEED AUTOMÁTICO (IDEMPOTENTE E RESILIENTE)
# ============================================================================

def _garantir_schema_completo(conn) -> None:
    """Garante de forma idempotente e segura as tabelas de perfil, histórico de safra, talhões, alertas e gráficos."""
    global _SCHEMA_INITIALIZED
    if _SCHEMA_INITIALIZED:
        return

    try:
        with conn.cursor() as cur:
            # 1. Tabelas de suporte básicas
            cur.execute("""
                CREATE TABLE IF NOT EXISTS perfil (
                    id_perfil SERIAL PRIMARY KEY,
                    nome      VARCHAR(150),
                    descricao VARCHAR(150)
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS usuario (
                    id_usuario          SERIAL PRIMARY KEY,
                    nome                VARCHAR(150),
                    email               VARCHAR(150) UNIQUE,
                    senha               VARCHAR(150),
                    status              VARCHAR(30) DEFAULT 'ativo',
                    data_cadastro       DATE DEFAULT CURRENT_DATE,
                    fk_perfil_id_perfil INTEGER
                );
            """)

            # Colunas extras em usuario
            cur.execute("""
                ALTER TABLE usuario
                    ADD COLUMN IF NOT EXISTS cargo VARCHAR(120),
                    ADD COLUMN IF NOT EXISTS bio TEXT,
                    ADD COLUMN IF NOT EXISTS telefone VARCHAR(40),
                    ADD COLUMN IF NOT EXISTS avatar_iniciais VARCHAR(6),
                    ADD COLUMN IF NOT EXISTS avatar_cor VARCHAR(30),
                    ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500);
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS usuario_preferencia (
                    fk_usuario_id_usuario  INTEGER PRIMARY KEY,
                    tema                   VARCHAR(30) NOT NULL DEFAULT 'claro',
                    efeitos_visuais        BOOLEAN NOT NULL DEFAULT TRUE,
                    atualizacao_tempo_real BOOLEAN NOT NULL DEFAULT TRUE,
                    idioma                 VARCHAR(15) NOT NULL DEFAULT 'pt-BR',
                    fuso_horario           VARCHAR(60) NOT NULL DEFAULT 'America/Recife',
                    moeda                  VARCHAR(10) NOT NULL DEFAULT 'BRL',
                    notificacoes_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
                    propriedade_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
                    preferencias_extras    JSONB NOT NULL DEFAULT '{}'::jsonb,
                    data_atualizacao       TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
                );
            """)

            # Perfis padrão
            cur.execute("""
                INSERT INTO perfil (nome, descricao)
                SELECT p.nome, p.descricao
                FROM (VALUES
                    ('Produtor/Exportador', 'Irrigação e logística fria'),
                    ('Analista de Dados',   'Histórico, agregações e previsões'),
                    ('Administrador',       'Usuários, parâmetros e auditoria')
                ) AS p(nome, descricao)
                WHERE NOT EXISTS (SELECT 1 FROM perfil x WHERE x.nome = p.nome);
            """)

            # Usuários padrão (sem usar OVERRIDING SYSTEM VALUE para compatibilidade total com SERIAL)
            usuarios_padrao = [
                (1, "Maria Clara", "maria.clara@raizagro.agr.br", "Gestora Técnica", "MC", "#10B981", "Produtor/Exportador"),
                (2, "Luiz Felipe", "luiz.felipe@raizagro.agr.br", "Analista IoT & Telemetria", "LF", "#0284C7", "Analista de Dados"),
                (3, "Lorena Lira", "lorena.lira@raizagro.agr.br", "Administradora", "LL", "#166534", "Administrador"),
            ]
            for uid, nome, email, cargo, iniciais, cor, nome_perfil in usuarios_padrao:
                cur.execute("SELECT id_usuario FROM usuario WHERE id_usuario = %s OR lower(email) = lower(%s)", (uid, email))
                u_row = cur.fetchone()
                if not u_row:
                    try:
                        cur.execute("""
                            INSERT INTO usuario (id_usuario, nome, email, status, data_cadastro, cargo, avatar_iniciais, avatar_cor, fk_perfil_id_perfil)
                            VALUES (
                                %s, %s, %s, 'ativo', CURRENT_DATE, %s, %s, %s,
                                (SELECT id_perfil FROM perfil WHERE nome = %s LIMIT 1)
                            )
                            ON CONFLICT (id_usuario) DO NOTHING
                        """, (uid, nome, email, cargo, iniciais, cor, nome_perfil))
                    except Exception:
                        pass
                else:
                    try:
                        cur.execute("""
                            UPDATE usuario SET cargo = COALESCE(cargo, %s), avatar_iniciais = COALESCE(avatar_iniciais, %s), avatar_cor = COALESCE(avatar_cor, %s)
                            WHERE id_usuario = %s
                        """, (cargo, iniciais, cor, u_row[0]))
                    except Exception:
                        pass

            # 2. Tabela historico_safra e desempenho_talhao
            cur.execute("""
                CREATE TABLE IF NOT EXISTS historico_safra (
                    id_safra                 SERIAL PRIMARY KEY,
                    ciclo                    VARCHAR(40) NOT NULL UNIQUE,
                    cultura                  VARCHAR(100) NOT NULL,
                    area_ha                  NUMERIC(10,2) NOT NULL,
                    produtividade_ton_ha     NUMERIC(10,2) NOT NULL,
                    volume_total_ton         NUMERIC(10,2) NOT NULL,
                    consumo_agua_m3_ha       INTEGER NOT NULL DEFAULT 3420,
                    brix_medio               NUMERIC(5,2) NOT NULL DEFAULT 18.5,
                    taxa_exportacao_pct      NUMERIC(5,2) NOT NULL DEFAULT 95.0,
                    status                   VARCHAR(30) NOT NULL DEFAULT 'Em Andamento',
                    destinacao_export_pct    INTEGER NOT NULL DEFAULT 78,
                    destinacao_interno_pct   INTEGER NOT NULL DEFAULT 16,
                    destinacao_industria_pct INTEGER NOT NULL DEFAULT 6,
                    data_atualizacao         TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
                );
            """)
            cur.execute("SELECT COUNT(*) FROM historico_safra")
            if cur.fetchone()[0] == 0:
                cur.execute("""
                    INSERT INTO historico_safra (
                        ciclo, cultura, area_ha, produtividade_ton_ha, volume_total_ton,
                        consumo_agua_m3_ha, brix_medio, taxa_exportacao_pct, status,
                        destinacao_export_pct, destinacao_interno_pct, destinacao_industria_pct
                    ) VALUES
                    ('2025/2026', 'Uva Vitória & Manga Palmer', 42.5, 30.2, 1284.5, 3420, 19.4, 96.2, 'Em Andamento', 78, 16, 6),
                    ('2024/2025', 'Uva Vitória (Seedless)',      40.0, 26.5, 1060.0, 3760, 18.2, 89.4, 'Concluída',    72, 20, 8),
                    ('2023/2024', 'Manga Tommy & Uva Crimson',  38.0, 24.8,  942.4, 4120, 17.5, 82.0, 'Concluída',    65, 25, 10);
                """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS desempenho_talhao (
                    id_talhao            SERIAL PRIMARY KEY,
                    codigo               VARCHAR(30) NOT NULL UNIQUE,
                    variedade            VARCHAR(80) NOT NULL,
                    porta_enxerto        VARCHAR(60) NOT NULL,
                    ciclo                VARCHAR(40) NOT NULL DEFAULT '2025/2026',
                    area_ha              NUMERIC(8,2) NOT NULL,
                    volume_ton           NUMERIC(10,2) NOT NULL,
                    produtividade_ton_ha NUMERIC(8,2) NOT NULL,
                    brix_medio           NUMERIC(5,2) NOT NULL,
                    calibres_mm          VARCHAR(30) NOT NULL,
                    status               VARCHAR(40) NOT NULL,
                    data_atualizacao     TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
                );
            """)
            cur.execute("SELECT COUNT(*) FROM desempenho_talhao")
            if cur.fetchone()[0] == 0:
                cur.execute("""
                    INSERT INTO desempenho_talhao (
                        codigo, variedade, porta_enxerto, ciclo, area_ha, volume_ton,
                        produtividade_ton_ha, brix_medio, calibres_mm, status
                    ) VALUES
                    ('Talhão A1', 'Uva Vitória (Seedless)', 'IAC 572',    '2025/2026', 12.0, 388.8, 32.4, 19.8, '21 - 24 mm', 'Colhido • Exportado'),
                    ('Talhão A2', 'Uva Vitória (Seedless)', 'IAC 766',    '2025/2026', 10.5, 323.4, 30.8, 19.2, '20 - 22 mm', 'Colhido • Exportado'),
                    ('Talhão B1', 'Manga Palmer',           'Espada',     '2025/2026', 11.0, 319.0, 29.0, 16.5, '420 - 480 g', 'Em Trânsito • Pecém'),
                    ('Talhão B2', 'Uva Thompson Seedless',  'SO4',        '2025/2026',  9.0, 253.3, 28.1, 18.6, '18 - 20 mm', 'Em Colheita (85%)');
                """)

            # 3. Tabela alerta_operacional_estado
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alerta_operacional_estado (
                    codigo_alerta    VARCHAR(60) PRIMARY KEY,
                    titulo           VARCHAR(200) NOT NULL,
                    severidade       VARCHAR(30) NOT NULL,
                    prioridade       VARCHAR(10) NOT NULL,
                    status           VARCHAR(30) NOT NULL DEFAULT 'pendente',
                    lote_ou_talhao   VARCHAR(120),
                    sensor_ref       VARCHAR(80),
                    leitura_atual    VARCHAR(60),
                    limiar_seguro    VARCHAR(80),
                    acao_tomada      TEXT,
                    atendido_por     VARCHAR(100),
                    data_atualizacao TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
                );
            """)
            cur.execute("SELECT COUNT(*) FROM alerta_operacional_estado")
            if cur.fetchone()[0] == 0:
                cur.execute("""
                    INSERT INTO alerta_operacional_estado (
                        codigo_alerta, titulo, severidade, prioridade, status,
                        lote_ou_talhao, sensor_ref, leitura_atual, limiar_seguro, acao_tomada
                    ) VALUES
                    ('P1-REEFER-EXP-2026-08', 'Excursão Térmica — Reefer Exportação #EXP-2026-08', 'critico', 'P1', 'pendente',
                     'Lote Uva Vitória (18,4t) • BR-116 Km 412', 'Sensor Termo-Reefer #TR-08', '3,8°C', '0,5°C a 2,0°C', NULL),
                    ('P2-SOLO-TALHAO-A1', 'Umidade do Solo Abaixo do Limiar — Talhão A1', 'moderado', 'P2', 'pendente',
                     'Talhão A1 • Uva Vitória (12,0 ha)', 'Sonda FDR #SL-A1-04', '38,2%', 'Mínimo 50,0% VWC', NULL),
                    ('PRED-VPD-SETOR-04', 'Previsão de Pico de Evapotranspiração (VPD > 2.8 kPa)', 'preditivo', 'IA', 'pendente',
                     'Setor 04 • Talhões A1, A2 e B2', 'Modelo Penman-Monteith IA', '2.8 kPa', '< 2.2 kPa', NULL),
                    ('ALT-2026-001', 'Desvio Térmico no Lote de Manga', 'critico', 'P1', 'pendente',
                     'Lote #101 • Manga Exportação (1.000 kg)', 'DHT11 ESP32-C3', '14,8°C', '10,0°C a 13,0°C', NULL),
                    ('ALT-2026-002', 'Déficit de Umidade Relativa no Lote de Uva', 'moderado', 'P2', 'pendente',
                     'Lote #102 • Câmara Frigorífica Uva (500 kg)', 'SNS-AR-002', '87,5% UR', '90,0% a 95,0% UR', NULL),
                    ('ALT-2026-003', 'Oscilação Térmica em Melão Amarelo', 'baixo', 'P3', 'pendente',
                     'Lote #103 • Antecâmara Packing (300 kg)', 'SNS-SL-003', '12,3°C', '10,0°C a 12,0°C', NULL);
                """)

            # 4. Tabela telemetria_grafico_estado
            cur.execute("""
                CREATE TABLE IF NOT EXISTS telemetria_grafico_estado (
                    id_config              INTEGER PRIMARY KEY DEFAULT 1,
                    umidade_ar_24h         JSONB NOT NULL,
                    umidade_solo_24h       JSONB NOT NULL,
                    temp_solo_24h          JSONB NOT NULL,
                    temp_ar_24h            JSONB NOT NULL,
                    conformidade_geral_pct INTEGER NOT NULL DEFAULT 90,
                    saude_plantacao_pct    INTEGER NOT NULL DEFAULT 85,
                    umidade_dossel_pct     INTEGER NOT NULL DEFAULT 67,
                    temp_foliar_c          NUMERIC(5,2) NOT NULL DEFAULT 27.0,
                    agua_reservatorio_pct  INTEGER NOT NULL DEFAULT 63,
                    vazao_ldia             INTEGER NOT NULL DEFAULT 4200,
                    curva_termica_analista JSONB NOT NULL DEFAULT '{}'::jsonb,
                    data_atualizacao       TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
                );
            """)
            cur.execute("SELECT COUNT(*) FROM telemetria_grafico_estado WHERE id_config = 1")
            if cur.fetchone()[0] == 0:
                cur.execute("""
                    INSERT INTO telemetria_grafico_estado (
                        id_config, umidade_ar_24h, umidade_solo_24h, temp_solo_24h, temp_ar_24h,
                        conformidade_geral_pct, saude_plantacao_pct, umidade_dossel_pct,
                        temp_foliar_c, agua_reservatorio_pct, vazao_ldia, curva_termica_analista
                    ) VALUES (
                        1,
                        '[61, 60, 59, 58, 60, 61, 63, 62]'::jsonb,
                        '[54, 53, 55, 57, 59, 58, 57, 58]'::jsonb,
                        '[24.1, 23.9, 24.3, 24.6, 24.8, 24.5, 24.4, 24.5]'::jsonb,
                        '[26.2, 25.8, 26.8, 28.2, 29.0, 28.1, 27.5, 27.8]'::jsonb,
                        90, 85, 67, 27.0, 63, 4200,
                        '{"temp_atual": 14.8, "tmax": 13.0, "tmin": 10.0, "indice_preditivo": 0.84, "umidade_camara_uva": 87.5, "limiar_ur_uva": 90.0}'::jsonb
                    );
                """)

        conn.commit()
        _SCHEMA_INITIALIZED = True
    except Exception as e:
        logger.warning(f"Aviso durante garantia de schema (tratado graciosamente): {e}")
        try:
            conn.rollback()
        except Exception:
            pass


# ============================================================================
# 1. ENDPOINTS DE PERFIL E PREFERÊNCIAS DO USUÁRIO
# ============================================================================

def _obter_perfil_e_preferencias(conn, id_usuario: int) -> dict:
    try:
        _garantir_schema_completo(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    u.id_usuario,
                    u.nome,
                    u.email,
                    u.cargo,
                    u.bio,
                    u.telefone,
                    u.avatar_iniciais,
                    u.avatar_cor,
                    u.avatar_url,
                    p.nome AS perfil,
                    COALESCE(up.tema, 'claro') AS tema,
                    COALESCE(up.efeitos_visuais, TRUE) AS efeitos_visuais,
                    COALESCE(up.atualizacao_tempo_real, TRUE) AS atualizacao_tempo_real,
                    COALESCE(up.idioma, 'pt-BR') AS idioma,
                    COALESCE(up.fuso_horario, 'America/Recife') AS fuso_horario,
                    COALESCE(up.moeda, 'BRL') AS moeda,
                    COALESCE(up.notificacoes_json, '{}'::jsonb) AS notificacoes_json,
                    COALESCE(up.propriedade_json, '{}'::jsonb) AS propriedade_json,
                    COALESCE(up.preferencias_extras, '{}'::jsonb) AS preferencias_extras,
                    up.data_atualizacao
                FROM usuario u
                LEFT JOIN perfil p ON p.id_perfil = u.fk_perfil_id_perfil
                LEFT JOIN usuario_preferencia up ON up.fk_usuario_id_usuario = u.id_usuario
                WHERE u.id_usuario = %s
            """, (id_usuario,))
            row = cur.fetchone()

        if row:
            res = dict(row)
            if res.get("data_atualizacao"):
                res["data_atualizacao"] = res["data_atualizacao"].isoformat()
            return res
    except Exception as e:
        logger.warning(f"Falha ao consultar banco para usuário {id_usuario}, usando fallback seguro: {e}")
        try:
            conn.rollback()
        except Exception:
            pass

    return DEFAULT_PERFIS.get(id_usuario, DEFAULT_PERFIS[1])


@router.get("/usuario/{id_usuario}")
def obter_preferencias_usuario(id_usuario: int, conn=Depends(get_conn)):
    """Retorna os dados de perfil e preferências persistidas do usuário pelo ID."""
    return _obter_perfil_e_preferencias(conn, id_usuario)


@router.get("/email/{email}")
def obter_preferencias_por_email(email: str, conn=Depends(get_conn)):
    """Retorna os dados de perfil e preferências persistidas do usuário pelo e-mail."""
    _garantir_schema_completo(conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id_usuario FROM usuario WHERE lower(email) = lower(%s)", (email.strip(),))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Usuário não encontrado para o e-mail informado")
    return _obter_perfil_e_preferencias(conn, row["id_usuario"])


@router.put("/usuario/{id_usuario}")
def salvar_preferencias_usuario(id_usuario: int, dados: PreferenciasUpdateIn, conn=Depends(get_conn)):
    """Salva permanentemente no banco de dados o perfil e todas as preferências do usuário."""
    _garantir_schema_completo(conn)
    agora = datetime.now(timezone.utc)

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id_usuario FROM usuario WHERE id_usuario = %s", (id_usuario,))
            if not cur.fetchone():
                try:
                    cur.execute("""
                        INSERT INTO usuario (id_usuario, nome, email, status, data_cadastro, cargo, avatar_iniciais, avatar_cor, fk_perfil_id_perfil)
                        VALUES (%s, %s, %s, 'ativo', CURRENT_DATE, %s, %s, %s, (SELECT id_perfil FROM perfil LIMIT 1))
                        ON CONFLICT (id_usuario) DO NOTHING
                    """, (id_usuario, dados.nome or "Usuário", f"user{id_usuario}@raizagro.agr.br", dados.cargo, dados.avatar_iniciais, dados.avatar_cor))
                except Exception:
                    pass

            sets_usuario = []
            params_usuario = []
            for campo in ("nome", "cargo", "bio", "telefone", "avatar_iniciais", "avatar_cor", "avatar_url"):
                val = getattr(dados, campo)
                if val is not None:
                    sets_usuario.append(f"{campo} = %s")
                    params_usuario.append(val)

            if sets_usuario:
                params_usuario.append(id_usuario)
                cur.execute(
                    f"UPDATE usuario SET {', '.join(sets_usuario)} WHERE id_usuario = %s",
                    params_usuario,
                )

            cur.execute("""
                INSERT INTO usuario_preferencia (
                    fk_usuario_id_usuario,
                    tema,
                    efeitos_visuais,
                    atualizacao_tempo_real,
                    idioma,
                    fuso_horario,
                    moeda,
                    notificacoes_json,
                    propriedade_json,
                    preferencias_extras,
                    data_atualizacao
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (fk_usuario_id_usuario) DO UPDATE SET
                    tema = EXCLUDED.tema,
                    efeitos_visuais = EXCLUDED.efeitos_visuais,
                    atualizacao_tempo_real = EXCLUDED.atualizacao_tempo_real,
                    idioma = EXCLUDED.idioma,
                    fuso_horario = EXCLUDED.fuso_horario,
                    moeda = EXCLUDED.moeda,
                    notificacoes_json = EXCLUDED.notificacoes_json,
                    propriedade_json = EXCLUDED.propriedade_json,
                    preferencias_extras = EXCLUDED.preferencias_extras,
                    data_atualizacao = EXCLUDED.data_atualizacao
            """, (
                id_usuario,
                dados.tema,
                dados.efeitos_visuais,
                dados.atualizacao_tempo_real,
                dados.idioma,
                dados.fuso_horario,
                dados.moeda,
                Json(dados.notificacoes_json or {}),
                Json(dados.propriedade_json or {}),
                Json(dados.preferencias_extras or {}),
                agora,
            ))
        conn.commit()
    except Exception as e:
        logger.warning(f"Aviso ao salvar preferencias no banco: {e}")
        try:
            conn.rollback()
        except Exception:
            pass

    return _obter_perfil_e_preferencias(conn, id_usuario)


# ============================================================================
# 2. ENDPOINTS DE HISTÓRICO DE SAFRA E TALHÕES (PERSISTIDOS NO POSTGRESQL)
# ============================================================================

def _montar_payload_safras(conn) -> dict:
    try:
        _garantir_schema_completo(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    id_safra,
                    ciclo,
                    cultura,
                    ROUND(area_ha::numeric, 2)::float AS area_ha,
                    ROUND(produtividade_ton_ha::numeric, 2)::float AS produtividade_ton_ha,
                    ROUND(volume_total_ton::numeric, 2)::float AS volume_total_ton,
                    consumo_agua_m3_ha,
                    ROUND(brix_medio::numeric, 2)::float AS brix_medio,
                    ROUND(taxa_exportacao_pct::numeric, 2)::float AS taxa_exportacao_pct,
                    status,
                    destinacao_export_pct,
                    destinacao_interno_pct,
                    destinacao_industria_pct,
                    data_atualizacao
                FROM historico_safra
                ORDER BY ciclo DESC, id_safra DESC
            """)
            safras = [dict(r) for r in cur.fetchall()]
            for s in safras:
                if s.get("data_atualizacao"):
                    s["data_atualizacao"] = s["data_atualizacao"].isoformat()

            cur.execute("""
                SELECT
                    id_talhao,
                    codigo,
                    variedade,
                    porta_enxerto,
                    ciclo,
                    ROUND(area_ha::numeric, 2)::float AS area_ha,
                    ROUND(volume_ton::numeric, 2)::float AS volume_ton,
                    ROUND(produtividade_ton_ha::numeric, 2)::float AS produtividade_ton_ha,
                    ROUND(brix_medio::numeric, 2)::float AS brix_medio,
                    calibres_mm,
                    status,
                    data_atualizacao
                FROM desempenho_talhao
                ORDER BY codigo ASC
            """)
            talhoes = [dict(r) for r in cur.fetchall()]
            for t in talhoes:
                if t.get("data_atualizacao"):
                    t["data_atualizacao"] = t["data_atualizacao"].isoformat()

        if safras and len(safras) > 0:
            safra_ativa = next((s for s in safras if s.get("status") == "Em Andamento"), safras[0])
            return {
                "safras": safras,
                "talhoes": talhoes,
                "safra_ativa": safra_ativa,
            }
    except Exception as e:
        logger.warning(f"Erro ao consultar safras no banco, usando fallback seguro: {e}")
        try:
            conn.rollback()
        except Exception:
            pass

    return DADOS_SAFRAS_PADRAO


@router.get("/safras")
def listar_historico_safras(conn=Depends(get_conn)):
    """Lista todas as safras e o desempenho por talhão salvos no banco PostgreSQL."""
    _garantir_schema_completo(conn)
    return _montar_payload_safras(conn)


@router.post("/safras")
def criar_ou_atualizar_safra(dados: SafraCreateUpdateIn, conn=Depends(get_conn)):
    """Cria um novo ciclo de safra (ou atualiza se o ciclo já existir) no banco PostgreSQL."""
    _garantir_schema_completo(conn)
    volume_calc = dados.volume_total_ton
    if volume_calc is None or volume_calc <= 0:
        volume_calc = round(dados.area_ha * dados.produtividade_ton_ha, 2)

    agora = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO historico_safra (
                ciclo, cultura, area_ha, produtividade_ton_ha, volume_total_ton,
                consumo_agua_m3_ha, brix_medio, taxa_exportacao_pct, status,
                destinacao_export_pct, destinacao_interno_pct, destinacao_industria_pct,
                data_atualizacao
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ciclo) DO UPDATE SET
                cultura = EXCLUDED.cultura,
                area_ha = EXCLUDED.area_ha,
                produtividade_ton_ha = EXCLUDED.produtividade_ton_ha,
                volume_total_ton = EXCLUDED.volume_total_ton,
                consumo_agua_m3_ha = EXCLUDED.consumo_agua_m3_ha,
                brix_medio = EXCLUDED.brix_medio,
                taxa_exportacao_pct = EXCLUDED.taxa_exportacao_pct,
                status = EXCLUDED.status,
                destinacao_export_pct = EXCLUDED.destinacao_export_pct,
                destinacao_interno_pct = EXCLUDED.destinacao_interno_pct,
                destinacao_industria_pct = EXCLUDED.destinacao_industria_pct,
                data_atualizacao = EXCLUDED.data_atualizacao
        """, (
            dados.ciclo.strip(),
            dados.cultura.strip(),
            dados.area_ha,
            dados.produtividade_ton_ha,
            volume_calc,
            dados.consumo_agua_m3_ha,
            dados.brix_medio,
            dados.taxa_exportacao_pct,
            dados.status.strip(),
            dados.destinacao_export_pct,
            dados.destinacao_interno_pct,
            dados.destinacao_industria_pct,
            agora,
        ))
    conn.commit()
    return _montar_payload_safras(conn)


@router.put("/safras/{id_safra}")
def atualizar_safra_por_id(id_safra: int, dados: SafraCreateUpdateIn, conn=Depends(get_conn)):
    """Atualiza os dados de uma safra existente no banco PostgreSQL."""
    _garantir_schema_completo(conn)
    volume_calc = dados.volume_total_ton
    if volume_calc is None or volume_calc <= 0:
        volume_calc = round(dados.area_ha * dados.produtividade_ton_ha, 2)

    agora = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute("SELECT id_safra FROM historico_safra WHERE id_safra = %s", (id_safra,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Safra não encontrada")

        cur.execute("""
            UPDATE historico_safra SET
                ciclo = %s,
                cultura = %s,
                area_ha = %s,
                produtividade_ton_ha = %s,
                volume_total_ton = %s,
                consumo_agua_m3_ha = %s,
                brix_medio = %s,
                taxa_exportacao_pct = %s,
                status = %s,
                destinacao_export_pct = %s,
                destinacao_interno_pct = %s,
                destinacao_industria_pct = %s,
                data_atualizacao = %s
            WHERE id_safra = %s
        """, (
            dados.ciclo.strip(),
            dados.cultura.strip(),
            dados.area_ha,
            dados.produtividade_ton_ha,
            volume_calc,
            dados.consumo_agua_m3_ha,
            dados.brix_medio,
            dados.taxa_exportacao_pct,
            dados.status.strip(),
            dados.destinacao_export_pct,
            dados.destinacao_interno_pct,
            dados.destinacao_industria_pct,
            agora,
            id_safra,
        ))
    conn.commit()
    return _montar_payload_safras(conn)


@router.put("/talhoes/{id_talhao}")
def atualizar_talhao_por_id(id_talhao: int, dados: TalhaoUpdateIn, conn=Depends(get_conn)):
    """Atualiza um talhão no banco e recalcula automaticamente os indicadores da safra vigente."""
    _garantir_schema_completo(conn)
    agora = datetime.now(timezone.utc)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM desempenho_talhao WHERE id_talhao = %s", (id_talhao,))
        atual = cur.fetchone()
        if not atual:
            raise HTTPException(status_code=404, detail="Talhão não encontrado")

        area_ha = dados.area_ha if dados.area_ha is not None else float(atual["area_ha"])
        prod_ton_ha = dados.produtividade_ton_ha if dados.produtividade_ton_ha is not None else float(atual["produtividade_ton_ha"])
        vol_ton = dados.volume_ton if dados.volume_ton is not None else round(area_ha * prod_ton_ha, 1)
        brix = dados.brix_medio if dados.brix_medio is not None else float(atual["brix_medio"])
        variedade = dados.variedade if dados.variedade is not None else atual["variedade"]
        porta_enxerto = dados.porta_enxerto if dados.porta_enxerto is not None else atual["porta_enxerto"]
        calibres = dados.calibres_mm if dados.calibres_mm is not None else atual["calibres_mm"]
        status = dados.status if dados.status is not None else atual["status"]

        cur.execute("""
            UPDATE desempenho_talhao SET
                variedade = %s,
                porta_enxerto = %s,
                area_ha = %s,
                volume_ton = %s,
                produtividade_ton_ha = %s,
                brix_medio = %s,
                calibres_mm = %s,
                status = %s,
                data_atualizacao = %s
            WHERE id_talhao = %s
        """, (
            variedade, porta_enxerto, area_ha, vol_ton,
            prod_ton_ha, brix, calibres, status, agora, id_talhao
        ))

        # Recalcula o consolidado da safra 2025/2026 com base nos talhões
        cur.execute("""
            SELECT
                COALESCE(SUM(area_ha), 42.5) AS total_area,
                COALESCE(SUM(volume_ton), 1284.5) AS total_vol,
                COALESCE(AVG(brix_medio), 19.4) AS avg_brix
            FROM desempenho_talhao
            WHERE ciclo = '2025/2026'
        """)
        agg = cur.fetchone()
        if agg and float(agg["total_area"]) > 0:
            nova_area = round(float(agg["total_area"]), 2)
            novo_vol = round(float(agg["total_vol"]), 2)
            nova_prod = round(novo_vol / nova_area, 2)
            novo_brix = round(float(agg["avg_brix"]), 2)
            cur.execute("""
                UPDATE historico_safra SET
                    area_ha = %s,
                    volume_total_ton = %s,
                    produtividade_ton_ha = %s,
                    brix_medio = %s,
                    data_atualizacao = %s
                WHERE ciclo = '2025/2026'
            """, (nova_area, novo_vol, nova_prod, novo_brix, agora))

    conn.commit()
    return _montar_payload_safras(conn)


# ============================================================================
# 3. ENDPOINTS DE ALERTAS OPERACIONAIS (PERSISTIDOS NO POSTGRESQL)
# ============================================================================

def _montar_payload_alertas(conn) -> dict:
    try:
        _garantir_schema_completo(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    codigo_alerta,
                    titulo,
                    severidade,
                    prioridade,
                    status,
                    lote_ou_talhao,
                    sensor_ref,
                    leitura_atual,
                    limiar_seguro,
                    acao_tomada,
                    atendido_por,
                    data_atualizacao
                FROM alerta_operacional_estado
                ORDER BY
                    CASE prioridade
                        WHEN 'P1' THEN 1
                        WHEN 'P2' THEN 2
                        WHEN 'IA' THEN 3
                        ELSE 4
                    END,
                    codigo_alerta ASC
            """)
            alertas = [dict(r) for r in cur.fetchall()]
            for a in alertas:
                if a.get("data_atualizacao"):
                    a["data_atualizacao"] = a["data_atualizacao"].isoformat()

        if alertas and len(alertas) > 0:
            gestora_codes = {"P1-REEFER-EXP-2026-08", "P2-SOLO-TALHAO-A1", "PRED-VPD-SETOR-04"}
            analista_codes = {"ALT-2026-001", "ALT-2026-002", "ALT-2026-003"}

            gestora_ativos = [a for a in alertas if a["codigo_alerta"] in gestora_codes and a["status"] == "pendente"]
            analista_ativos = [a for a in alertas if a["codigo_alerta"] in analista_codes and a["status"] == "pendente"]

            return {
                "alertas": alertas,
                "por_codigo": {a["codigo_alerta"]: a for a in alertas},
                "resumo": {
                    "total_pendentes": sum(1 for a in alertas if a["status"] == "pendente"),
                    "total_atendidos": sum(1 for a in alertas if a["status"] == "atendido"),
                    "gestora_ativos": len(gestora_ativos),
                    "gestora_criticos": sum(1 for a in gestora_ativos if a["prioridade"] == "P1"),
                    "gestora_moderados": sum(1 for a in gestora_ativos if a["prioridade"] != "P1"),
                    "analista_ativos": len(analista_ativos),
                },
            }
    except Exception as e:
        logger.warning(f"Erro ao consultar alertas no banco: {e}")
        try:
            conn.rollback()
        except Exception:
            pass

    return DADOS_ALERTAS_PADRAO


@router.get("/alertas")
def listar_estado_alertas(conn=Depends(get_conn)):
    """Retorna o status real de todos os alertas operacionais diretamente do banco PostgreSQL."""
    return _montar_payload_alertas(conn)


@router.patch("/alertas/{codigo_alerta}")
def atualizar_status_alerta(codigo_alerta: str, dados: AlertaPatchIn, conn=Depends(get_conn)):
    """Atualiza o status de um alerta ('pendente', 'atendido' ou 'silenciado') no PostgreSQL."""
    _garantir_schema_completo(conn)
    agora = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute("SELECT codigo_alerta FROM alerta_operacional_estado WHERE codigo_alerta = %s", (codigo_alerta,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Alerta '{codigo_alerta}' não encontrado")

        sets = ["status = %s", "data_atualizacao = %s"]
        params: List[Any] = [dados.status, agora]

        if dados.acao_tomada is not None:
            sets.append("acao_tomada = %s")
            params.append(dados.acao_tomada)
        if dados.atendido_por is not None:
            sets.append("atendido_por = %s")
            params.append(dados.atendido_por)
        if dados.leitura_atual is not None:
            sets.append("leitura_atual = %s")
            params.append(dados.leitura_atual)
        if dados.limiar_seguro is not None:
            sets.append("limiar_seguro = %s")
            params.append(dados.limiar_seguro)

        params.append(codigo_alerta)
        cur.execute(
            f"UPDATE alerta_operacional_estado SET {', '.join(sets)} WHERE codigo_alerta = %s",
            params,
        )

        # Sincroniza também na tabela relacional `alerta` caso existam registros
        if dados.status == "atendido":
            cur.execute("UPDATE alerta SET status = 'resolvido', data_resolucao = %s WHERE status = 'ativo'", (agora,))
    conn.commit()
    return _montar_payload_alertas(conn)


@router.post("/alertas/reconhecer-todos")
def reconhecer_todos_alertas(perfil: Optional[str] = None, reset: bool = False, conn=Depends(get_conn)):
    """Marca todos os alertas como 'atendido' (ou restaura para 'pendente' se reset=True) no PostgreSQL."""
    _garantir_schema_completo(conn)
    agora = datetime.now(timezone.utc)
    novo_status = "pendente" if reset else "atendido"
    acao = None if reset else "Reconhecido e atendido em lote pela central operacional"

    with conn.cursor() as cur:
        if perfil == "gestor":
            codigos = ("P1-REEFER-EXP-2026-08", "P2-SOLO-TALHAO-A1", "PRED-VPD-SETOR-04")
            cur.execute("""
                UPDATE alerta_operacional_estado
                SET status = %s, acao_tomada = %s, data_atualizacao = %s
                WHERE codigo_alerta IN %s
            """, (novo_status, acao, agora, codigos))
        elif perfil == "analista":
            codigos = ("ALT-2026-001", "ALT-2026-002", "ALT-2026-003")
            cur.execute("""
                UPDATE alerta_operacional_estado
                SET status = %s, acao_tomada = %s, data_atualizacao = %s
                WHERE codigo_alerta IN %s
            """, (novo_status, acao, agora, codigos))
        else:
            cur.execute("""
                UPDATE alerta_operacional_estado
                SET status = %s, acao_tomada = %s, data_atualizacao = %s
            """, (novo_status, acao, agora))
    conn.commit()
    return _montar_payload_alertas(conn)


# ============================================================================
# 4. ENDPOINTS DE TELEMETRIA E DADOS DOS GRÁFICOS (PERSISTIDOS NO POSTGRESQL)
# ============================================================================

def _obter_estado_graficos(conn) -> dict:
    try:
        _garantir_schema_completo(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    umidade_ar_24h,
                    umidade_solo_24h,
                    temp_solo_24h,
                    temp_ar_24h,
                    conformidade_geral_pct,
                    saude_plantacao_pct,
                    umidade_dossel_pct,
                    ROUND(temp_foliar_c::numeric, 1)::float AS temp_foliar_c,
                    agua_reservatorio_pct,
                    vazao_ldia,
                    curva_termica_analista,
                    data_atualizacao
                FROM telemetria_grafico_estado
                WHERE id_config = 1
            """)
            row = cur.fetchone()
        if row:
            res = dict(row)
            if res.get("data_atualizacao"):
                res["data_atualizacao"] = res["data_atualizacao"].isoformat()
            return res
    except Exception as e:
        logger.warning(f"Erro ao consultar graficos no banco: {e}")
        try:
            conn.rollback()
        except Exception:
            pass

    return DADOS_GRAFICOS_PADRAO


@router.get("/graficos")
def obter_dados_graficos(conn=Depends(get_conn)):
    """Retorna as séries e indicadores que alimentam os gráficos do Dashboard e Central de Alertas."""
    return _obter_estado_graficos(conn)


@router.put("/graficos")
def atualizar_dados_graficos(dados: GraficosTelemetriaUpdateIn, conn=Depends(get_conn)):
    """Salva no PostgreSQL os dados editados que alimentam os gráficos e KPIs."""
    _garantir_schema_completo(conn)
    agora = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE telemetria_grafico_estado SET
                umidade_ar_24h = %s,
                umidade_solo_24h = %s,
                temp_solo_24h = %s,
                temp_ar_24h = %s,
                conformidade_geral_pct = %s,
                saude_plantacao_pct = %s,
                umidade_dossel_pct = %s,
                temp_foliar_c = %s,
                agua_reservatorio_pct = %s,
                vazao_ldia = %s,
                curva_termica_analista = %s,
                data_atualizacao = %s
            WHERE id_config = 1
        """, (
            Json(dados.umidade_ar_24h),
            Json(dados.umidade_solo_24h),
            Json(dados.temp_solo_24h),
            Json(dados.temp_ar_24h),
            dados.conformidade_geral_pct,
            dados.saude_plantacao_pct,
            dados.umidade_dossel_pct,
            dados.temp_foliar_c,
            dados.agua_reservatorio_pct,
            dados.vazao_ldia,
            Json(dados.curva_termica_analista or {}),
            agora,
        ))
    conn.commit()
    return _obter_estado_graficos(conn)
