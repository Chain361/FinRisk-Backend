# -*- coding: utf-8 -*-
"""/auth — login (bcrypt + JWT)"""
from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import create_access_token, get_current_user, verify_login
from ..database import Connection, get_db
from ..schemas import LoginRequest, LoginResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, conn: Connection = Depends(get_db)):
    user = verify_login(conn, body.username, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="username หรือ password ไม่ถูกต้อง",
        )
    token = create_access_token(user)
    return LoginResponse(token=token, user=UserOut(**user))


@router.get("/me", response_model=UserOut)
def me(user: dict = Depends(get_current_user)):
    return UserOut(**user)
