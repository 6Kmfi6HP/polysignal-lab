from __future__ import annotations

import posixpath
import re
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

BASE_URL = "https://nautilustrader.io"
GUIDE_ROOT = f"{BASE_URL}/docs/latest/developer_guide/"
RAW_ROOT = "https://raw.githubusercontent.com/nautechsystems/nautilus_trader/master/docs/developer_guide"
GITHUB_BLOB_ROOT = "https://github.com/nautechsystems/nautilus_trader/blob/master"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "nautilus_reference" / "developer_guide"
INDEX_PATH = OUTPUT_DIR / "README.md"
TIMEOUT = 30

PAGES = [
    ("index.md", GUIDE_ROOT),
    ("environment_setup.md", f"{GUIDE_ROOT}environment_setup/"),
    ("design_principles.md", f"{GUIDE_ROOT}design_principles/"),
    ("coding_standards.md", f"{GUIDE_ROOT}coding_standards/"),
    ("rust.md", f"{GUIDE_ROOT}rust/"),
    ("python.md", f"{GUIDE_ROOT}python/"),
    ("testing.md", f"{GUIDE_ROOT}testing/"),
    ("test_datasets.md", f"{GUIDE_ROOT}test_datasets/"),
    ("docs.md", f"{GUIDE_ROOT}docs/"),
    ("releases.md", f"{GUIDE_ROOT}releases/"),
    ("release_security.md", f"{GUIDE_ROOT}release_security/"),
    ("adapters.md", f"{GUIDE_ROOT}adapters/"),
    ("spec_data_testing.md", f"{GUIDE_ROOT}spec_data_testing/"),
    ("spec_exec_testing.md", f"{GUIDE_ROOT}spec_exec_testing/"),
    ("benchmarking.md", f"{GUIDE_ROOT}benchmarking/"),
    ("ffi.md", f"{GUIDE_ROOT}ffi/"),
]
EXPORTED = {filename for filename, _ in PAGES}
MD_LINK_RE = re.compile(r"(\]\()([^)#]+\.md)(#[^)]+)?(\))")


def fetch_text(url: str) -> str:
    with urlopen(url, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8")


def title_from_markdown(markdown: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    raise RuntimeError("未找到一级标题")


def normalize_posix(path: PurePosixPath) -> PurePosixPath:
    return PurePosixPath(posixpath.normpath(str(path)))


def docs_url_from_repo_path(repo_path: PurePosixPath) -> str:
    parts = list(repo_path.parts)
    if parts[0] != "docs":
        raise ValueError(f"不是 docs 目录路径: {repo_path}")
    if repo_path.name == "index.md":
        subpath = "/".join(parts[1:-1])
    else:
        subpath = "/".join(parts[1:-1] + [repo_path.stem])
    if subpath:
        return f"{BASE_URL}/docs/latest/{subpath}/"
    return f"{BASE_URL}/docs/latest/"


def rewrite_relative_links(markdown: str, source_name: str) -> str:
    source_path = PurePosixPath("docs/developer_guide") / source_name

    def repl(match: re.Match[str]) -> str:
        rel_path = match.group(2)
        anchor = match.group(3) or ""

        if "://" in rel_path or rel_path.startswith("/") or rel_path.startswith("#"):
            return match.group(0)

        resolved = normalize_posix(source_path.parent / rel_path)

        if resolved.parts[:2] == ("docs", "developer_guide") and resolved.name in EXPORTED:
            target = resolved.name + anchor
        elif resolved.parts and resolved.parts[0] == "docs":
            target = docs_url_from_repo_path(resolved) + anchor
        else:
            target = f"{GITHUB_BLOB_ROOT}/{resolved.as_posix()}{anchor}"
        return f"]({target})"

    return MD_LINK_RE.sub(repl, markdown)


def build_document(official_url: str, source_name: str) -> str:
    source_url = f"{RAW_ROOT}/{source_name}"
    markdown = fetch_text(source_url).strip()
    markdown = rewrite_relative_links(markdown, source_name)
    footer = [
        "",
        "---",
        "",
        "来源链接：",
        f"- {official_url}",
    ]
    return markdown + "\n" + "\n".join(footer).rstrip() + "\n"


def write_index(output_files: list[tuple[str, str, str]]) -> None:
    lines = [
        "# NautilusTrader Developer Guide 导出索引",
        "",
        "> 本目录由 `scripts/export_nautilus_developer_guide.py` 根据官方 Developer Guide 页面地址，批量抓取对应源码 Markdown 后导出。",
        "",
        "## 文件列表",
        "",
    ]
    for filename, title, url in output_files:
        lines.append(f"- [{title}](./{filename})")
        lines.append(f"  - 来源：{url}")
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 按页面拆分保存，不是单文档汇总。",
            "- `developer_guide` 内部相对链接保持本地可跳转。",
            "- 指向导出范围外的相对链接已改写为官方文档 URL 或 GitHub 源文件 URL。",
            "- 每个 Markdown 文件底部都附带官方页面来源链接。",
            "",
        ]
    )
    INDEX_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUTPUT_DIR.glob("*.md"):
        stale.unlink()

    written: list[tuple[str, str, str]] = []
    for source_name, official_url in PAGES:
        document = build_document(official_url, source_name)
        title = title_from_markdown(document)
        path = OUTPUT_DIR / source_name
        path.write_text(document, encoding="utf-8")
        written.append((source_name, title, official_url))
        print(f"Wrote {path}")
    write_index(written)
    print(f"Wrote {INDEX_PATH}")


if __name__ == "__main__":
    main()
