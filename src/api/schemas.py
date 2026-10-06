from datetime import date, datetime, timezone
from enum import Enum
from typing import Annotated, Optional

from pydantic import BaseModel, EmailStr, Field, PlainSerializer, field_validator


def _iso_utc(dt: datetime) -> str:
    """ISO 8601 com 'Z' (o banco guarda UTC sem fuso)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _origem_api(valor: str) -> str:
    """Mesmo vocabulario dos endpoints novos: thingspeak -> real; 'simulado' continua."""
    v = valor.lower()
    return "real" if v == "thingspeak" else v


DataUTC = Annotated[datetime, PlainSerializer(_iso_utc, return_type=str)]
OrigemAPI = Annotated[str, PlainSerializer(_origem_api, return_type=str)]

class StatusUsuario(str, Enum):
    ativo = "ativo"
    inativo = "inativo"


class PerfilOut(BaseModel):
    id_perfil: int
    nome: Optional[str] = None
    descricao: Optional[str] = None


class UsuarioOut(BaseModel):
    id_usuario: int
    nome: Optional[str] = None
    email: Optional[str] = None
    status: Optional[StatusUsuario] = None
    data_cadastro: Optional[date] = None
    id_perfil: Optional[int] = None
    perfil: Optional[str] = None


class UsuarioCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=150)
    email: EmailStr
    senha: str = Field(min_length=8, max_length=72)
    id_perfil: int


class UsuarioUpdate(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=1, max_length=150)
    email: Optional[EmailStr] = None
    id_perfil: Optional[int] = None
    status: Optional[StatusUsuario] = None


class SenhaUpdate(BaseModel):
    senha_atual: str
    senha_nova: str = Field(min_length=8, max_length=72)

class LeituraOut(BaseModel):
    id_leitura: int
    id_sensor: Optional[int] = None
    temperatura: Optional[float] = None
    umidade: Optional[float] = None
    data_hora: Optional[DataUTC] = None
    data_recebimento: Optional[DataUTC] = None
    origem: Optional[OrigemAPI] = None
    entry_id_thingspeak: Optional[int] = None


class EstatisticasLeituraOut(BaseModel):
    total_leituras: int
    primeira_leitura: Optional[DataUTC] = None
    ultima_leitura: Optional[DataUTC] = None
    temperatura_min: Optional[float] = None
    temperatura_max: Optional[float] = None
    temperatura_media: Optional[float] = None
    umidade_min: Optional[float] = None
    umidade_max: Optional[float] = None
    umidade_media: Optional[float] = None


class LeituraRejeitadaOut(BaseModel):
    id_rejeicao: int
    id_sensor: Optional[int] = None
    entry_id_thingspeak: Optional[int] = None
    temperatura_bruta: Optional[str] = None
    umidade_bruta: Optional[str] = None
    data_hora_bruta: Optional[str] = None
    motivo: str
    origem: Optional[str] = None
    data_rejeicao: Optional[datetime] = None


class LogAuditoriaOut(BaseModel):
    id_log: int
    data_hora: Optional[datetime] = None
    acao: Optional[str] = None
    ip: Optional[str] = None
    resultado: Optional[str] = None
    id_usuario: Optional[int] = None
    usuario: Optional[str] = None

    @field_validator("ip", mode="before")
    @classmethod
    def _ip_sem_mascara(cls, v):
        if v is None:
            return None
        v = str(v)
        return v[:-3] if v.endswith("/32") else v[:-4] if v.endswith("/128") else v    
    
class SensorOut(BaseModel):
        id_sensor: int
        nome: Optional[str] = None
        tipo_sensor: Optional[str] = None
        localizacao: Optional[str] = None
        channel_id: Optional[int] = None
        status: Optional[str] = None
        id_lote: Optional[int] = None
        ambiente: str
        # dados da última leitura (ficam None se o sensor ainda não tem leituras)
        ultima_leitura: Optional[DataUTC] = None
        temperatura: Optional[float] = None
        umidade: Optional[float] = None
        origem: Optional[OrigemAPI] = None

class AmbienteSensor(str, Enum):
    ar = "ar"
    solo = "solo"


class StatusSensor(str, Enum):
    ativo = "ativo"
    inativo = "inativo"


class SensorCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=150)
    tipo_sensor: Optional[str] = Field(default=None, max_length=150)
    localizacao: Optional[str] = Field(default=None, max_length=150)
    channel_id: Optional[int] = None
    id_lote: Optional[int] = None
    ambiente: AmbienteSensor = AmbienteSensor.ar
    status: StatusSensor = StatusSensor.ativo


class SensorUpdate(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=1, max_length=150)
    tipo_sensor: Optional[str] = Field(default=None, max_length=150)
    localizacao: Optional[str] = Field(default=None, max_length=150)
    channel_id: Optional[int] = None
    id_lote: Optional[int] = None
    ambiente: Optional[AmbienteSensor] = None
    status: Optional[StatusSensor] = None

class EtapaConfig(str, Enum):
        campo = "campo"
        armazenamento = "armazenamento"
        transporte = "transporte"


class ConfigParametroOut(BaseModel):
    id_config: int
    id_fruta: Optional[int] = None
    fruta: Optional[str] = None
    etapa: str
    temp_min: Optional[float] = None
    temp_max: Optional[float] = None
    umidade_min: Optional[float] = None
    umidade_max: Optional[float] = None


class ConfigParametroCreate(BaseModel):
    id_fruta: int
    etapa: EtapaConfig
    temp_min: float = Field(ge=-40, le=80)
    temp_max: float = Field(ge=-40, le=80)
    umidade_min: float = Field(ge=0, le=100)
    umidade_max: float = Field(ge=0, le=100)


class ConfigParametroUpdate(BaseModel):
    id_fruta: Optional[int] = None
    etapa: Optional[EtapaConfig] = None
    temp_min: Optional[float] = Field(default=None, ge=-40, le=80)
    temp_max: Optional[float] = Field(default=None, ge=-40, le=80)
    umidade_min: Optional[float] = Field(default=None, ge=0, le=100)
    umidade_max: Optional[float] = Field(default=None, ge=0, le=100)