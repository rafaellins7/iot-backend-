from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

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
    data_hora: Optional[datetime] = None
    data_recebimento: Optional[datetime] = None
    origem: Optional[str] = None
    entry_id_thingspeak: Optional[int] = None


class EstatisticasLeituraOut(BaseModel):
    total_leituras: int
    primeira_leitura: Optional[datetime] = None
    ultima_leitura: Optional[datetime] = None
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
    