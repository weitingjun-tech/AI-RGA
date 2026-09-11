"""上传文件安全校验。

两道独立防线，缺一不可：

1. **文件名净化** —— 文件名完全由客户端控制，可以写成 `../../../etc/passwd`
   或 Windows 下的 `..\\..\\evil.txt`。如果直接拿去拼路径，文件就写到上传目录之外了。

2. **文件头（魔数）校验** —— 扩展名只是一个字符串，把 `evil.exe` 改名成 `a.pdf`
   就能绕过白名单。真正决定文件类型的是开头的几个字节。

关于历史的 `f"{uuid}_{filename}"` 写法：它挡不住路径穿越。
随机前缀只是变成了路径的一部分（`abc123_../../../x.txt`），`../` 依然生效。
真正有效的是取 basename。
"""
import codecs
import os
import re
from pathlib import PurePosixPath

# 常见文件头
_PDF_MAGIC = b"%PDF"
_ZIP_MAGIC = b"PK\x03\x04"  # docx / epub 本质都是 zip 容器
_MOBI_MAGIC = b"BOOKMOBI"  # 位于文件偏移 60 字节处
_OLE_MAGIC = b"\xd0\xcf\x11\xe0"  # 老版 .doc/.xls，本项目不支持，用于给出更好提示

# 扩展名 -> 允许的文件头（None 表示纯文本，没有固定文件头，改由解码校验）
_SIGNATURES: dict[str, list[bytes] | None] = {
    ".pdf": [_PDF_MAGIC],
    ".docx": [_ZIP_MAGIC],
    ".epub": [_ZIP_MAGIC],
    ".txt": None,
    ".md": None,
    ".csv": None,
    ".mobi": None,  # MOBI 文件头在偏移 60，单独判断
}

_UNSAFE_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
_MAX_FILENAME_LENGTH = 200
_TEXT_ENCODINGS = ("utf-8", "gb18030")


class FileValidationError(ValueError):
    """文件未通过安全校验，消息可直接展示给用户。"""


def sanitize_filename(raw: str | None) -> str:
    """从客户端提供的文件名中提取安全的 basename。

    >>> sanitize_filename("../../etc/passwd")
    'passwd'
    >>> sanitize_filename("..\\\\..\\\\windows\\\\evil.txt")
    'evil.txt'
    >>> sanitize_filename("   ")
    'unnamed'
    """
    name = (raw or "").replace("\\", "/")
    # 只取最后一段 —— 这一步同时解决了 "../" 和 "C:/x/" 两类前缀
    name = PurePosixPath(name).name
    name = _UNSAFE_CHARS.sub("", name).strip().strip(".")
    # 防止超长文件名撑爆文件系统（多数文件系统单个文件名上限 255 字节）
    if len(name) > _MAX_FILENAME_LENGTH:
        stem, dot, suffix = name.rpartition(".")
        if dot:
            keep = _MAX_FILENAME_LENGTH - len(suffix) - 1
            name = stem[:keep] + dot + suffix
        else:
            name = name[:_MAX_FILENAME_LENGTH]
    return name or "unnamed"


def validate_file(extension: str, path: str) -> None:
    """校验磁盘上文件的内容是否与其扩展名相符。

    校验的是**文件本体**而非上传时读到的片段，避免"只检查前 N 字节"被绕过。
    """
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        raise FileValidationError("文件内容为空")

    ext = extension.lower()
    with open(path, "rb") as f:
        head = f.read(512)

    # 明确拦截常见伪装：告诉用户真实类型，比笼统的"不支持"更有帮助
    if head[:4] == _OLE_MAGIC:
        raise FileValidationError(
            "检测到这是旧版 Office 格式（.doc/.xls），请另存为 .docx/.csv 后再上传"
        )

    if ext == ".mobi":
        # 标准要求偏移 60 字节处为 BOOKMOBI 标识
        with open(path, "rb") as f:
            f.seek(60)
            if f.read(8) != _MOBI_MAGIC:
                raise FileValidationError(
                    "文件内容不是有效的 MOBI 格式（缺少 BOOKMOBI 标识）"
                )
        return

    signatures = _SIGNATURES.get(ext)
    if signatures is None:
        _validate_text_file(path)
        return

    if not any(head.startswith(sig) for sig in signatures):
        raise FileValidationError(
            f"文件内容与扩展名 {ext} 不符（文件头校验失败），请确认没有改过后缀名"
        )


def _validate_text_file(path: str) -> None:
    """文本类文件没有固定文件头，改用两条规则判断：

    1. 出现 NUL 字节 → 是二进制，不是文本
    2. 能按 UTF-8 或 GB18030 完整解码（中文 .txt 常见 GBK 编码，所以不能只试 UTF-8）
    """
    with open(path, "rb") as f:
        if b"\x00" in f.read(8192):
            raise FileValidationError(
                "文件不是有效的文本（含二进制内容），可能是其他格式改了后缀"
            )

    for encoding in _TEXT_ENCODINGS:
        try:
            # iterdecode 会正确处理跨 chunk 的多字节字符，不会把合法的
            # 中文文件误判成编码错误
            with open(path, "rb") as f:
                for _ in codecs.iterdecode(f, encoding):
                    pass
            return
        except (UnicodeDecodeError, LookupError):
            continue

    raise FileValidationError(
        "文件不是有效的文本（无法按 UTF-8/GB18030 解码），可能是二进制文件改了后缀"
    )
