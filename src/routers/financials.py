# -*- coding: utf-8 -*-
"""/financial-statements — งบการเงินตามตำบล"""
import sqlite3

from fastapi import APIRouter, Depends, Query

from ..auth import get_current_user, scope_subdistrict_ids
from ..database import get_db, rows_to_dicts

router = APIRouter(tags=["financials"])


@router.get("/financial-statements")
@router.get("/financials")
def list_financial_statements(
    fiscal_year: int | None = Query(default=None),
    statement_type: str | None = Query(default=None),
    category: str | None = Query(default=None),
    account_item: str | None = Query(default=None),
    user: dict = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    allowed = scope_subdistrict_ids(conn, user)
    where, params = [], []

    if allowed is not None:
        if not allowed:
            return []
        where.append(f"subdistrict_id IN ({','.join('?' * len(allowed))})")
        params += allowed

    if fiscal_year is not None:
        where.append("fiscal_year = ?")
        params.append(fiscal_year)
    if statement_type is not None:
        where.append("statement_type = ?")
        params.append(statement_type)
    if category is not None:
        where.append("category = ?")
        params.append(category)
    if account_item is not None:
        where.append("account_item = ?")
        params.append(account_item)

    sql = "SELECT * FROM financial_statements"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY subdistrict_id, fiscal_year, statement_type, account_item"

    rows = conn.execute(sql, params).fetchall()
    return rows_to_dicts(rows)
