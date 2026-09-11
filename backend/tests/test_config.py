"""配置模块测试：路径解析 + 生产环境强校验。

JWT 密钥校验为什么值得写测试：
一个**固定的默认密钥**不是"弱口令"，是**后门**——密钥一旦公开，
任何人都能自己签一个 `{"sub": "1", "role": "admin"}` 的 token 冒充管理员。
所以这条校验必须确保"在生产环境真的会拦住启动"，而不只是打印一行警告。
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent

from app.config import BACKEND_DIR as CONFIG_BACKEND_DIR  # noqa: E402
from app.config import resolve_path  # noqa: E402

PLACEHOLDER = "my-secret-key-change-in-production"


def _import_config(**env_overrides) -> subprocess.CompletedProcess:
    """在子进程里以指定环境变量导入 app.config。

    用子进程而不是 importlib.reload：config 的校验发生在**模块顶层**，
    reload 会把副作用带到当前测试进程，污染后续测试。
    """
    env = dict(os.environ)
    # 显式置空（而不是删除）——python-dotenv 对"已存在的键"不会覆盖，
    # 这样无论开发机上有没有 .env，测试结果都一致。
    env["JWT_SECRET"] = ""
    env.update(env_overrides)
    env["PYTHONPATH"] = str(BACKEND_DIR)

    return subprocess.run(
        [sys.executable, "-c", "import app.config; print('CONFIG_LOADED')"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestResolvePath:
    def test_relative_path_anchors_to_backend_dir(self):
        """相对路径必须锚定到 backend 目录，而不是当前工作目录。

        否则从别的目录（测试脚本 / eval 脚本）启动时会连到一个**空的数据目录**，
        表现为「知识库明明有数据却检索不到」，而且不报任何错。
        """
        assert resolve_path("./chroma_data") == str(CONFIG_BACKEND_DIR / "chroma_data")

    def test_absolute_path_is_untouched(self, tmp_path):
        """绝对路径原样返回。

        用 tmp_path 而不是硬编码的路径字符串：Windows 上 "/var/lib/x"
        并**不是**绝对路径（没有盘符），硬编码会让这条测试变成"只在 Linux 上成立"。
        """
        assert resolve_path(str(tmp_path)) == str(tmp_path)
        assert resolve_path("D:/data/x") == str(Path("D:/data/x"))

    @pytest.mark.skipif(os.name != "nt", reason="这是 Windows 特有的路径语义")
    def test_posix_style_path_lands_at_drive_root_on_windows(self):
        """记录一个容易踩的坑：`/data/chroma` 在 Windows 上**不是**绝对路径。

        `Path("/data/chroma").is_absolute()` 在 Windows 返回 False（没有盘符），
        于是 resolve_path 会执行 `BACKEND_DIR / "/data/chroma"`。
        而 pathlib 遇到"带根但无盘符"的路径时，会**保留盘符、丢弃其余全部前缀**，
        结果是 `D:\\data\\chroma` —— 既不是配置里写的那个位置，
        也不在 backend 目录下，而是跑到了盘符根目录。

        同一个配置在 Linux 容器里 `/data/chroma` 就是真正的绝对路径，行为完全不同。
        **结论：配置项里不要用 POSIX 风格的绝对路径，跨平台会静默落到别处。**
        """
        resolved = resolve_path("/data/chroma")

        assert resolved == str(Path(CONFIG_BACKEND_DIR.anchor) / "data" / "chroma")
        assert not resolved.startswith(str(CONFIG_BACKEND_DIR)), (
            "它会跑到盘符根目录，而不是 backend 目录下——这正是危险之处"
        )

    def test_result_is_cwd_independent(self):
        """同一个配置项，无论从哪个目录解释，结果都必须一样。"""
        first = resolve_path("uploads")
        os.chdir(BACKEND_DIR.parent)
        try:
            assert resolve_path("uploads") == first
        finally:
            os.chdir(BACKEND_DIR)


class TestProductionJwtValidation:
    def test_missing_secret_blocks_production_startup(self):
        result = _import_config(APP_ENV="production")
        assert result.returncode != 0, "生产环境缺少 JWT_SECRET 时必须拒绝启动"
        assert "JWT_SECRET" in result.stderr

    def test_placeholder_secret_blocks_production_startup(self):
        """占位值等同于"没设置"——很多项目就是栽在这一条上。"""
        result = _import_config(APP_ENV="production", JWT_SECRET=PLACEHOLDER)
        assert result.returncode != 0
        assert "JWT_SECRET" in result.stderr

    def test_short_secret_blocks_production_startup(self):
        result = _import_config(APP_ENV="production", JWT_SECRET="short-secret")
        assert result.returncode != 0
        assert "32" in result.stderr, "错误信息里要带上长度下限，方便直接改对"

    def test_valid_secret_starts_normally(self):
        result = _import_config(APP_ENV="production", JWT_SECRET="x" * 64)
        assert result.returncode == 0, result.stderr
        assert "CONFIG_LOADED" in result.stdout

    def test_production_error_message_tells_how_to_fix(self):
        """报错要给出可执行的修复方式，而不是只说"配置错误"。"""
        result = _import_config(APP_ENV="production")
        assert "secrets.token_urlsafe" in result.stderr


class TestDevelopmentFallback:
    def test_development_still_starts_without_secret(self):
        """开发环境要开箱即用，不能因为没配密钥就跑不起来。"""
        result = _import_config(APP_ENV="development")
        assert result.returncode == 0, result.stderr
        assert "CONFIG_LOADED" in result.stdout

    def test_development_warns_loudly(self):
        """降级可以，但必须**出声**——静默降级等于埋雷。"""
        result = _import_config(APP_ENV="development")
        assert "JWT_SECRET" in result.stderr

    def test_auto_generated_secrets_differ_between_runs(self):
        """开发环境随机生成密钥，保证"至少不可预测"。

        代价是重启后旧 token 失效（需要重新登录）——这是刻意为之：
        宁可开发者多登录一次，也不能让固定密钥被带进生产。
        """
        script = "import app.config as c; print(c.JWT_SECRET)"
        env = dict(os.environ)
        env["JWT_SECRET"] = ""
        env["APP_ENV"] = "development"
        env["PYTHONPATH"] = str(BACKEND_DIR)

        def _run():
            return subprocess.run(
                [sys.executable, "-c", script],
                cwd=str(BACKEND_DIR), env=env, capture_output=True, text=True, timeout=60,
            ).stdout.strip()

        assert _run() != _run()

    def test_development_short_secret_warns_but_starts(self):
        result = _import_config(APP_ENV="development", JWT_SECRET="tiny")
        assert result.returncode == 0
        assert "32" in result.stderr


class TestSecurityDefaults:
    """安全检查默认值——默认值即"用户什么都不配时的行为"，最重要。"""

    def test_acl_is_on_by_default(self):
        from app.config import KB_ACL_ENABLED

        assert KB_ACL_ENABLED is True, "ACL 默认必须是开的，安全功能不能默认关闭"

    def test_rate_limit_is_on_by_default(self):
        from app.config import RATE_LIMIT_ENABLED

        assert RATE_LIMIT_ENABLED is True

    def test_hybrid_search_is_on_by_default(self):
        from app.config import HYBRID_SEARCH_ENABLED

        assert HYBRID_SEARCH_ENABLED is True

    def test_dedup_is_on_by_default(self):
        from app.config import DEDUP_ENABLED

        assert DEDUP_ENABLED is True

    def test_chunk_overlap_is_smaller_than_chunk_size(self):
        """重叠大于块大小会让分块逻辑陷入死循环或产出无限重复内容。"""
        from app.config import CHUNK_OVERLAP, CHUNK_SIZE

        assert 0 <= CHUNK_OVERLAP < CHUNK_SIZE

    def test_rrf_k_is_positive(self):
        from app.config import RRF_K

        assert RRF_K > 0
