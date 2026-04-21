#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据库表结构拉取工具

从 MySQL 实例拉取所有库的表定义（DDL），保存为：
  schemas/{database}.sql  — 每个库的 CREATE TABLE 语句集合
  schema_index.json       — 全局表索引（表名 → 库名 + 字段列表）

用法：
  python fetch_db_schema.py            # 拉取所有库
  python fetch_db_schema.py --db my_database     # 只拉指定库
  python fetch_db_schema.py --list     # 只列出库名，不拉取

配置：
  编辑本文件底部的 DB_CONFIG，或在 .env 文件中配置
"""
import os, sys, re, json, argparse
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from datetime import datetime
import pymysql
import pymysql.cursors

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import config_loader as cfg

# ── 输出目录 ──────────────────────────────────────────────────────────────────

OUT_DIR   = Path(__file__).parent / "schemas"
INDEX_FILE = Path(__file__).parent / "schema_index.json"

# ── 数据库连接配置（敏感信息必须通过 .env 或环境变量提供）──────────────────

DB_CONFIG = {
    "host":     os.environ.get("DB_HOST",     "127.0.0.1"),
    "port":     int(os.environ.get("DB_PORT", "3306")),
    "user":     os.environ.get("DB_USER",     ""),
    "password": os.environ.get("DB_PASSWORD", ""),
    "charset":  "utf8mb4",
    "connect_timeout": 10,
}

# 不拉取这些库
SKIP_DATABASES = {"information_schema", "mysql", "performance_schema", "sys", "test"}

# ── 系统通用字段（从配置文件加载）─────────────────────────────────────────────

SYSTEM_FIELDS = cfg.get_system_fields()

TODAY = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ── 工具函数 ─────────────────────────────────────────────────────────────────

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def connect(database=None) -> pymysql.Connection:
    cfg = dict(DB_CONFIG)
    if database:
        cfg["database"] = database
    return pymysql.connect(**cfg)

def list_databases(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SHOW DATABASES")
        return [row[0] for row in cur.fetchall()
                if row[0].lower() not in SKIP_DATABASES]

def list_tables(conn, database: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(f"SHOW TABLES FROM `{database}`")
        return [row[0] for row in cur.fetchall()]

def get_create_table(conn, database: str, table: str) -> str:
    with conn.cursor() as cur:
        cur.execute(f"SHOW CREATE TABLE `{database}`.`{table}`")
        row = cur.fetchone()
        return row[1] if row else ""

def get_table_comment(conn, database: str, table: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_COMMENT FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
            (database, table)
        )
        row = cur.fetchone()
        return (row[0] or "") if row else ""

def get_columns(conn, database: str, table: str) -> list[dict]:
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            "SELECT COLUMN_NAME, COLUMN_TYPE, COLUMN_COMMENT "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
            "ORDER BY ORDINAL_POSITION",
            (database, table)
        )
        rows = cur.fetchall()
    return [
        {
            "name":    r["COLUMN_NAME"],
            "type":    r["COLUMN_TYPE"],
            "comment": r["COLUMN_COMMENT"] or "",
        }
        for r in rows
        if r["COLUMN_NAME"].lower() not in SYSTEM_FIELDS
    ]

# ── 核心逻辑 ─────────────────────────────────────────────────────────────────

def fetch_database(conn, database: str) -> dict:
    """
    拉取一个库的所有表，返回:
    {table_name: {comment, columns: [{name, type, comment}], ddl: str}}
    """
    tables = list_tables(conn, database)
    log(f"  {database}: {len(tables)} 张表")
    result = {}
    for tbl in tables:
        ddl     = get_create_table(conn, database, tbl)
        comment = get_table_comment(conn, database, tbl)
        columns = get_columns(conn, database, tbl)
        result[tbl] = {
            "database": database,
            "comment":  comment,
            "columns":  columns,
            "ddl":      ddl,
        }
    return result

def save_sql(database: str, tables: dict) -> None:
    """写 schemas/{database}.sql"""
    OUT_DIR.mkdir(exist_ok=True)
    lines = [f"-- 数据库: {database}  (拉取时间: {TODAY})\n"]
    for tbl, info in tables.items():
        lines.append(f"\n-- 表: {tbl}  {info['comment']}")
        lines.append(info["ddl"] + ";\n")
    (OUT_DIR / f"{database}.sql").write_text("\n".join(lines), encoding="utf-8")

def load_index() -> dict:
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    return {}

def save_index(index: dict) -> None:
    INDEX_FILE.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="拉取 MySQL 表结构")
    parser.add_argument("--db",   help="只拉取指定数据库")
    parser.add_argument("--list", action="store_true", help="只列出库名")
    args = parser.parse_args()

    log(f"连接 {DB_CONFIG['host']}:{DB_CONFIG['port']} ...")
    conn = connect()

    databases = list_databases(conn)
    conn.close()

    if args.db:
        if args.db not in databases:
            log(f"库 '{args.db}' 不存在，可用：{databases}")
            return
        databases = [args.db]

    if args.list:
        print("\n可用数据库：")
        for db in databases:
            print(f"  {db}")
        return

    log(f"发现 {len(databases)} 个库：{databases}")

    # 加载旧索引（增量更新）
    index = load_index()
    total_tables = 0

    for db in databases:
        log(f"拉取 {db} ...")
        try:
            conn = connect(database=db)
            tables = fetch_database(conn, db)
            conn.close()
        except Exception as e:
            log(f"  [失败] {db}: {e}")
            continue

        save_sql(db, tables)

        # 更新全局索引
        for tbl, info in tables.items():
            index[tbl] = {
                "database": db,
                "comment":  info["comment"],
                "columns":  info["columns"],
            }
        total_tables += len(tables)
        log(f"  -> schemas/{db}.sql  ({len(tables)}张表)")

    save_index(index)
    log(f"=== 完成 === 共 {len(databases)} 个库 {total_tables} 张表 -> schema_index.json")

if __name__ == "__main__":
    log(f"===== 数据库表结构拉取 {TODAY} =====")
    main()
