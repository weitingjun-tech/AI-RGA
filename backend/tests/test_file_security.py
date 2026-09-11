"""上传文件安全测试：文件名净化 + 文件头（魔数）校验。

两条独立的防线，缺一不可：
- 文件名净化挡住**路径穿越**（把文件写到上传目录之外）
- 魔数校验挡住**改名伪装**（把 .exe 改成 .pdf）
"""
import pytest

from app.utils.file_security import (
    FileValidationError,
    sanitize_filename,
    validate_file,
)


class TestSanitizeFilename:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            # 路径穿越：Linux 与 Windows 两种写法
            ("../../etc/passwd", "passwd"),
            ("..\\..\\windows\\system32\\evil.txt", "evil.txt"),
            ("/etc/shadow", "shadow"),
            ("C:/Users/x/secret.docx", "secret.docx"),
            # 文件名里的非法字符
            ('a<b>c:d"e|f?g*h.txt', "abcdefgh.txt"),
            # 全是空白 / 空值
            ("   ", "unnamed"),
            ("", "unnamed"),
            (None, "unnamed"),
            # 纯点名
            ("...", "unnamed"),
            # 正常文件名保持不变
            ("用户手册 v2.pdf", "用户手册 v2.pdf"),
        ],
    )
    def test_sanitize(self, raw, expected):
        assert sanitize_filename(raw) == expected

    def test_path_traversal_is_neutralized(self):
        """核心断言：净化结果里**不允许**再出现任何路径分隔符。

        逐字符检查而不是比对字符串，是为了防止将来有人改实现时
        只处理了 ".." 却漏了别的分隔符写法。
        """
        for attack in (
            "../../etc/passwd",
            "..\\..\\boot.ini",
            "....//....//etc/passwd",
            "/absolute/path.txt",
        ):
            result = sanitize_filename(attack)
            assert "/" not in result and "\\" not in result
            assert not result.startswith("..")

    def test_leading_dots_are_stripped(self):
        """前导点会被剥掉，因此 ".env" 这类隐藏文件名不会原样落盘。"""
        assert sanitize_filename(".env") == "env"

    def test_long_filename_is_truncated_but_extension_survives(self):
        """超长文件名要截断，但**扩展名必须保留**——否则校验和后续解析都拿不到类型。"""
        result = sanitize_filename("a" * 300 + ".pdf")
        assert len(result) <= 200
        assert result.endswith(".pdf")

    def test_long_filename_without_extension(self):
        assert len(sanitize_filename("b" * 500)) <= 200

    def test_null_byte_is_stripped(self):
        """NUL 字节会被底层文件系统当成字符串终止符，必须清掉。"""
        assert "\x00" not in sanitize_filename("evil\x00.txt")


class TestMagicByteValidation:
    def test_valid_pdf(self, tmp_path):
        p = tmp_path / "a.pdf"
        p.write_bytes(b"%PDF-1.4\n%...")
        validate_file(".pdf", str(p))

    def test_exe_renamed_to_pdf_is_rejected(self, tmp_path):
        """把可执行文件改名成 .pdf —— 扩展名白名单拦不住，只有魔数能拦。"""
        p = tmp_path / "fake.pdf"
        p.write_bytes(b"MZ\x90\x00\x03\x00\x00\x00")  # Windows PE 文件头
        with pytest.raises(FileValidationError, match="文件头校验失败"):
            validate_file(".pdf", str(p))

    def test_docx_and_epub_share_zip_magic(self, tmp_path):
        for ext in (".docx", ".epub"):
            p = tmp_path / f"a{ext}"
            p.write_bytes(b"PK\x03\x04" + b"\x00" * 64)
            validate_file(ext, str(p))

    def test_zip_content_in_pdf_is_rejected(self, tmp_path):
        p = tmp_path / "x.pdf"
        p.write_bytes(b"PK\x03\x04" + b"\x00" * 64)
        with pytest.raises(FileValidationError):
            validate_file(".pdf", str(p))

    def test_legacy_office_gets_actionable_message(self, tmp_path):
        """老版 .doc 给出「请另存为 .docx」的提示，比笼统的「不支持」更有用。"""
        p = tmp_path / "old.docx"
        p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
        with pytest.raises(FileValidationError, match="另存为"):
            validate_file(".docx", str(p))

    def test_mobi_magic_at_offset_60(self, tmp_path):
        p = tmp_path / "book.mobi"
        p.write_bytes(b"\x00" * 60 + b"BOOKMOBI" + b"\x00" * 64)
        validate_file(".mobi", str(p))

    def test_mobi_without_signature_is_rejected(self, tmp_path):
        p = tmp_path / "fake.mobi"
        p.write_bytes(b"\x00" * 60 + b"NOTMOBI!" + b"\x00" * 64)
        with pytest.raises(FileValidationError, match="BOOKMOBI"):
            validate_file(".mobi", str(p))

    def test_empty_file_is_rejected(self, tmp_path):
        p = tmp_path / "empty.txt"
        p.write_bytes(b"")
        with pytest.raises(FileValidationError, match="为空"):
            validate_file(".txt", str(p))

    def test_missing_file_is_rejected(self, tmp_path):
        with pytest.raises(FileValidationError, match="为空"):
            validate_file(".txt", str(tmp_path / "nope.txt"))


class TestTextFileValidation:
    """文本类文件没有固定文件头，改用"能否解码"来判断。"""

    def test_utf8_chinese_text(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_text("这是一份中文文档", encoding="utf-8")
        validate_file(".txt", str(p))

    def test_gb18030_chinese_text(self, tmp_path):
        """中文 .txt 在 Windows 上常见 GBK 编码，只试 UTF-8 会误杀合法文件。"""
        p = tmp_path / "gbk.txt"
        p.write_bytes("这是 GBK 编码的中文".encode("gb18030"))
        validate_file(".txt", str(p))

    def test_binary_disguised_as_text_is_rejected(self, tmp_path):
        p = tmp_path / "fake.txt"
        p.write_bytes(b"\x00\x01\x02\x03binary")
        with pytest.raises(FileValidationError, match="二进制"):
            validate_file(".txt", str(p))

    def test_undecodable_bytes_are_rejected(self, tmp_path):
        p = tmp_path / "bad.md"
        # 既不是合法 UTF-8 也不是合法 GB18030，且不含 NUL
        p.write_bytes(b"\xff\xfe\xfd\xfc\xfb\xfa")
        with pytest.raises(FileValidationError):
            validate_file(".md", str(p))

    def test_csv_is_treated_as_text(self, tmp_path):
        p = tmp_path / "a.csv"
        p.write_text("id,name\n1,张三\n", encoding="utf-8")
        validate_file(".csv", str(p))

    def test_multibyte_char_split_across_chunk_boundary(self, tmp_path):
        """多字节字符跨读取分块时要能正确处理，不能误判成编码错误。

        有些实现用固定大小的块 `read()` 后逐块 decode，会把一个汉字的
        三个字节切到两个块里，导致合法的中文文件被判为非法。
        """
        p = tmp_path / "big.txt"
        p.write_text("中" * 5000, encoding="utf-8")
        validate_file(".txt", str(p))
