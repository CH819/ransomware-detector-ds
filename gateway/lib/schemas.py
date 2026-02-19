from .models import Role
from pydantic import BaseModel, EmailStr
from typing import Union


class UserBase(BaseModel):
    email: EmailStr
    role: str = Role.user


class UserCreate(UserBase):
    password: str


class User(UserBase):
    id: int

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class AuthResponse(Token):
    user: User


class TokenData(BaseModel):
    email: Union[str, None] = None


class Node(BaseModel):
    id: int
    name: str
    status: str
    last_seen: str
    ip_address: str
    mac_address: str
    os_type: str
    os_version: str


class NodeRecover(BaseModel):
    snapshot_id: str
