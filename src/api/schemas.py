from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


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