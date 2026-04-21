#!/usr/bin/env python3
"""
Confluence 文档爬虫（简化版）
用法: python scrape_confluence.py [--root ROOT_ID] [--output OUTPUT_DIR]

配置（按优先级）：
  1. 同目录 .env 文件
  2. ~/.claude/skills/confluence-api/.config.json

输出：每个页面保存为一个 .md 文件到同一目录
"""

import argparse
import json
import os
import re
import sys
import time
import logging
import urllib.parse
import requests
from pathlib import Path

if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("confluence_scrape")


def load_config():
    cfg = {"base_url": "", "username": "", "password": ""}

    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k == "CONFLUENCE_BASE_URL":
                cfg["base_url"] = v or cfg["base_url"]
            elif k == "CONFLUENCE_USERNAME":
                cfg["username"] = v or cfg["username"]
            elif k == "CONFLUENCE_PASSWORD":
                cfg["password"] = v or cfg["password"]

    cfg["base_url"] = os.environ.get("CONFLUENCE_BASE_URL", "") or cfg["base_url"]
    cfg["username"] = os.environ.get("CONFLUENCE_USERNAME", "") or cfg["username"]
    cfg["password"] = os.environ.get("CONFLUENCE_PASSWORD", "") or cfg["password"]

    missing = [k for k, v in cfg.items() if not v]
    if missing:
        log.error("配置不完整，缺少: %s", missing)
        sys.exit(1)

    return cfg


class ConfluenceClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()
        self._logged_in = False
        self._req_count = 0

    def _login(self):
        if self._logged_in:
            return
        resp = self.session.post(
            f"{self.base_url}/dologin.action",
            data=urllib.parse.urlencode({
                "os_username": self.username,
                "os_password": self.password,
                "login": "Log In",
            }),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            allow_redirects=False,
            timeout=30,
        )
        raw = resp.headers.get("Set-Cookie", "")
        m = re.search(r"JSESSIONID=([^;]+)", raw)
        jsession = m.group(1) if m else self.session.cookies.get_dict().get("JSESSIONID", "")
        if not jsession:
            raise RuntimeError(f"登录失败 (HTTP {resp.status_code})，请检查账号密码")
        self.session.cookies.set("JSESSIONID", jsession)
        self._logged_in = True
        log.debug("登录成功")

    def _api(self, path, retries=3):
        self._login()
        for attempt in range(retries):
            try:
                resp = self.session.get(f"{self.base_url}{path}", timeout=30)
                self._req_count += 1
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 30))
                    log.warning("限流，等待 %ds", wait)
                    time.sleep(wait)
                    continue
                else:
                    resp.raise_for_status()
            except Exception as e:
                if attempt < retries - 1:
                    log.warning("请求失败（%d/%d）: %s", attempt + 1, retries, e)
                    time.sleep(5 * (attempt + 1))
                    continue
                raise
        raise RuntimeError(f"API 请求失败: {path}")

    def get_page(self, page_id):
        return self._api(
            f"/rest/api/content/{page_id}?expand=body.storage,title,version,space,ancestors"
        )

    def get_children(self, page_id):
        results = []
        start = 0
        while True:
            data = self._api(
                f"/rest/api/content/{page_id}/child/page?limit=100&start={start}"
            )
            results.extend(data.get("results", []))
            if len(results) >= data.get("totalSize", len(results)):
                break
            start += 100
        return results


def sanitize(name: str) -> str:
    if not name or not name.strip():
        return "untitled"
    name = name.strip()
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name)
    return name[:150]


def html_to_text(html: str) -> str:
    """保留段落结构的 HTML 转纯文本"""
    if not html:
        return ""

    # 块级标签替换为双换行（保留结构）
    block_replacements = {
        # 标题
        r"<h1[^>]*>": "\n\n# ",
        r"</h1>": "\n\n",
        r"<h2[^>]*>": "\n\n## ",
        r"</h2>": "\n\n",
        r"<h3[^>]*>": "\n\n### ",
        r"</h3>": "\n\n",
        r"<h4[^>]*>": "\n\n#### ",
        r"</h4>": "\n\n",
        r"<h5[^>]*>": "\n\n##### ",
        r"</h5>": "\n\n",
        r"<h6[^>]*>": "\n\n###### ",
        r"</h6>": "\n\n",
        # 列表
        r"<ul[^>]*>": "\n",
        r"</ul>": "\n",
        r"<ol[^>]*>": "\n",
        r"</ol>": "\n",
        r"<li[^>]*>": "- ",
        r"</li>": "\n",
        # 表格
        r"<table[^>]*>": "\n\n",
        r"</table>": "\n\n",
        r"<tr[^>]*>": "\n",
        r"</tr>": "\n",
        r"<th[^>]*>": " | ",
        r"</th>": " | ",
        r"<td[^>]*>": " | ",
        r"</td>": " | ",
        r"<br[^>]*>": "\n",
        r"<p[^>]*>": "\n\n",
        r"</p>": "\n\n",
        r"<div[^>]*>": "\n",
        r"</div>": "\n",
        r"<hr[^>]*>": "\n\n---\n\n",
        r"<pre[^>]*>": "\n\n```\n",
        r"</pre>": "\n```\n\n",
        r"<code[^>]*>": "`",
        r"</code>": "`",
        r"<strong[^>]*>": "**",
        r"</strong>": "**",
        r"<b[^>]*>": "**",
        r"</b>": "**",
        r"<em[^>]*>": "_",
        r"</i[^>]*>": "_",
        r"</em>": "_",
        r"</i>": "_",
        r"<u[^>]*>": "",
        r"</u>": "",
        r"<span[^>]*>": "",
        r"</span>": "",
        r"<a[^>]*>": "",
        r"</a>": "",
        r"<img[^>]*>": "",
    }
    text = html
    for pattern, replacement in block_replacements.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # 移除所有剩余标签
    text = re.sub(r"<[^>]+>", "", text)

    # 解码 HTML 实体
    entities = {
        "&nbsp;": " ",
        "&ensp;": " ",
        "&emsp;": "  ",
        "&lt;": "<",
        "&gt;": ">",
        "&amp;": "&",
        "&quot;": '"',
        "&#39;": "'",
        "&apos;": "'",
        "&mdash;": "—",
        "&ndash;": "–",
        "&hellip;": "…",
        "&ldquo;": """,
        "&rdquo;": """,
        "&lsquo;": "'",
        "&rsquo;": "'",
        "&#xa0;": " ",
        "&#160;": " ",
    }
    for e, c in entities.items():
        text = text.replace(e, c)

    # 移除剩余数值实体
    text = re.sub(r"&#x?[0-9a-fA-F]+;", " ", text)

    # 清理多余空白，保留段落结构
    text = re.sub(r"[ \t]+", " ", text)        # 行内多余空格
    text = re.sub(r"\n{4,}", "\n\n\n", text)   # 过多空行
    text = re.sub(r" +\n", "\n", text)         # 行尾多余空格
    text = re.sub(r"\n +", "\n", text)         # 行首多余空格
    text = re.sub(r"\n{3,}", "\n\n", text)   # 双换行封顶

    return text.strip()


def crawl(client: ConfluenceClient, page_id: str, seen: set,
          output_dir: Path, indent: str = ""):
    if page_id in seen:
        return
    seen.add(page_id)

    page = client.get_page(page_id)

    title = page.get("title", "") or "untitled"
    body_html = page.get("body", {}).get("storage", {}).get("value", "")
    body_text = html_to_text(body_html)

    # 文件名: {pageId}_{标题}.md
    safe_title = sanitize(title)
    filename = f"{page_id}_{safe_title}.md"
    filepath = output_dir / filename

    log.info("%s[%s] %s", indent, page_id, title)

    # 写入 .md
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", "", f"**Page ID**: {page_id}", "", "---", "", body_text]
    filepath.write_text("\n".join(lines), encoding="utf-8")

    time.sleep(0.3)

    # 递归子页面
    for child in client.get_children(page_id):
        crawl(client, child["id"], seen, output_dir, indent + "  ")


def main():
    parser = argparse.ArgumentParser(description="爬取 Confluence 页面，保存为 .md 文件")
    # 尝试从 project_config.json 读取默认根页面
    _default_root = ""
    try:
        _cfg_path = Path(__file__).resolve().parent.parent / "project_config.json"
        if _cfg_path.exists():
            import json as _json
            _cfg = _json.loads(_cfg_path.read_text(encoding="utf-8"))
            _default_root = ",".join(_cfg.get("confluence", {}).get("root_page_ids", [_default_root]))
    except Exception:
        pass

    parser.add_argument(
        "--root",
        default=_default_root,
        help="根节点 pageId，多个用逗号分隔",
    )
    parser.add_argument(
        "--output",
        default="./confluence_data",
        help="输出目录（默认: ./confluence_data）",
    )
    parser.add_argument(
        "--single",
        metavar="PAGE_ID",
        help="只爬取单个页面，不递归",
    )
    args = parser.parse_args()

    cfg = load_config()
    client = ConfluenceClient(cfg["base_url"], cfg["username"], cfg["password"])
    output_dir = Path(args.output).resolve()

    seen = set()
    log.info("=" * 60)
    log.info("输出目录: %s", output_dir)
    log.info("=" * 60)

    if args.single:
        crawl(client, args.single, seen, output_dir)
    else:
        root_ids = [r.strip() for r in args.root.split(",") if r.strip()]
        for rid in root_ids:
            crawl(client, rid, seen, output_dir)

    log.info("=" * 60)
    log.info("完成，共爬取 %d 个页面", len(seen))
    log.info("=" * 60)


if __name__ == "__main__":
    main()
