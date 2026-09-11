"""Alembic 运行环境。

连接串从 app.config 读取，保证与应用用的是同一份 .env。
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 让 alembic 能 import 到 app 包
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import DATABASE_URL  # noqa: E402
from app.database import Base  # noqa: E402
import app.models  # noqa: E402,F401  必须导入，否则 Base.metadata 里没有表

config = context.config
# 覆盖 alembic.ini 中的占位值，数据库地址以 .env 为准
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _include_object(obj, name, type_, reflected, compare_to):
    """autogenerate 时忽略哪些对象。"""
    if type_ == "table" and name in {"alembic_version"}:
        return False
    return True


def _normalize_default(value):
    """把不同写法的时间默认值归一化，用于比较。

    MySQL 会把 `now()`、`localtime`、`localtimestamp` 全部规范化存成
    `CURRENT_TIMESTAMP`。于是模型里写 `func.now()`、数据库里是
    `CURRENT_TIMESTAMP`，autogenerate 每一轮都会报"默认值不一致"，
    生成一堆毫无意义的迁移。

    这类噪声的危害不只是烦：真正需要关注的结构变更会被淹没在里面，
    久而久之就没人认真看 autogenerate 的输出了。
    """
    if value is None:
        return None
    text = str(value).strip()
    # 反射出来的默认值常带一层括号，例如 (CURRENT_TIMESTAMP)
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    text = text.rstrip("()").strip().lower()
    if text in {"current_timestamp", "now", "localtime", "localtimestamp"}:
        return "now"
    if text in {"null", "none", ""}:
        return None
    return text


def _compare_server_default(
    context,
    inspected_column,
    metadata_column,
    inspected_default,
    metadata_default,
    rendered_metadata_default,
):
    """自定义默认值比较逻辑，屏蔽 MySQL 的时间函数写法差异。

    返回 False 表示"认为二者相同"，不生成迁移。
    """
    left = _normalize_default(inspected_default)
    right = _normalize_default(rendered_metadata_default)
    if left is None and right is None:
        return False
    return left != right


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 脚本，不连数据库。

    用法：alembic upgrade head --sql > migration.sql
    适合交给 DBA 审核后手工执行的场景。
    """
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        # 传自定义比较函数而不是 True：MySQL 的时间默认值写法差异需要归一化
        compare_server_default=_compare_server_default,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # 开启这两项，autogenerate 才能识别"改字段类型"和"改默认值"这类变更。
            # 不开的话它们会被静默忽略——迁移文件看起来生成了，实际没生效。
            compare_type=True,
            compare_server_default=_compare_server_default,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
