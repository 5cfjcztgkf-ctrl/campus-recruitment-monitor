#!/usr/bin/env python3
"""
秋招进校监控 - 自动检查脚本
每天自动检查27所目标高校的就业网，发现新通知后更新数据。

运行环境: GitHub Actions (ubuntu-latest)
需要安装: pip install requests beautifulsoup4
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("请先安装依赖: pip install requests beautifulsoup4")
    sys.exit(1)

# ============================================================
# 配置
# ============================================================

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "universities.json")
TZ = timezone(timedelta(hours=8))  # 北京时间
REQUEST_TIMEOUT = 15  # 请求超时秒数
USER_AGENT = "Mozilla/5.0 (compatible; CampusMonitor/1.0; +https://github.com)"

# 关键词：匹配2027届秋季招聘通知
KEYWORDS = [
    r"2027届.*秋[季招]",      # 2027届秋招/秋季招聘
    r"202[67]年.*秋[季招]",    # 2026/2027年秋招
    r"秋季.*校园招聘.*安排",
    r"秋季.*招聘.*服务.*安排",
    r"秋季.*校园招聘.*通知",
    r"秋季.*校园招聘.*邀请函",
    r"秋季.*校园招聘.*指南",
    r"秋季.*进校.*招聘",
    r"秋招.*进校",
    r"20[23][267]年.*秋季.*招聘",  # 年份范围
    r"用人单位.*进校.*招聘",
]

# 排除词：这些不算秋招总安排
EXCLUDE_KEYWORDS = [
    "宣讲会",
    "双选会",
    "招聘会",
    "空中",
    "提前批",
    "暑期实习",
    "实习招聘",
    "博士后",
    "人才引进",
]

# ============================================================
# 工具函数
# ============================================================

def fetch_page(url, encoding=None):
    """抓取网页内容，返回文本和soup对象"""
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return None, None, "timeout"
    except requests.exceptions.ConnectionError:
        return None, None, "connection_error"
    except requests.exceptions.HTTPError as e:
        return None, None, f"http_error:{e.response.status_code if e.response else 'unknown'}"
    except Exception as e:
        return None, None, f"error:{str(e)[:100]}"

    # 自动检测编码
    if encoding:
        resp.encoding = encoding
    elif resp.apparent_encoding:
        resp.encoding = resp.apparent_encoding
    else:
        # 尝试常见的中文编码
        for enc in ['utf-8', 'gb2312', 'gbk', 'gb18030']:
            try:
                resp.content.decode(enc)
                resp.encoding = enc
                break
            except:
                continue

    try:
        html = resp.text
    except:
        return None, None, "decode_error"

    soup = BeautifulSoup(html, "html.parser")
    return html, soup, None


def extract_links_and_titles(soup, base_url):
    """从页面中提取所有链接和标题文本"""
    results = []
    # 提取所有 <a> 标签
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        href = a["href"]
        full_url = urljoin(base_url, href)
        results.append({
            "text": text,
            "url": full_url
        })
    # 也提取 <li> 中可能包含的链接
    for li in soup.find_all("li"):
        a = li.find("a", href=True)
        if a:
            text = a.get_text(strip=True) or li.get_text(strip=True)
            href = a["href"]
            full_url = urljoin(base_url, href)
            results.append({
                "text": text,
                "url": full_url
            })
    return results


def match_keywords(text):
    """检查文本是否匹配秋招关键词"""
    text_lower = text.lower()
    for kw in KEYWORDS:
        if re.search(kw, text_lower):
            return True
    return False


def match_exclude(text):
    """检查是否应该排除（有可能只是双选会通知而非总安排）"""
    # 如果标题很短，不排除
    if len(text) < 15:
        return True
    for kw in EXCLUDE_KEYWORDS:
        if kw in text:
            return True
    return False


def check_university(u):
    """检查单个高校的就业网"""
    name = u["name"]
    notice_url = u.get("notice_url", "")
    status = u["status"]
    
    if not notice_url:
        return {"university": name, "status": status, "changed": False, 
                "error": "no_notice_url", "new_notices": []}
    
    # 抓取页面
    html, soup, error = fetch_page(notice_url)
    if error:
        return {"university": name, "status": status, "changed": False, 
                "error": error, "new_notices": []}
    
    # 提取链接和文本
    items = extract_links_and_titles(soup, notice_url)
    
    # 筛选匹配秋招关键词的条目
    matched = []
    for item in items:
        text = item["text"]
        if not text or len(text) < 8:
            continue
        if match_keywords(text) and not match_exclude(text):
            matched.append(item)
    
    return {
        "university": name,
        "status": status,
        "changed": False,
        "error": None,
        "new_notices": matched
    }


def parse_date_from_text(text):
    """尝试从文本中提取日期"""
    patterns = [
        r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})",
        r"发布于[：:]?\s*(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 2025 <= y <= 2027 and 1 <= mo <= 12 and 1 <= d <= 31:
                return f"{y}-{mo:02d}-{d:02d}"
    return None


# ============================================================
# 主逻辑
# ============================================================

def main():
    print(f"=== 秋招监控自动检查 ===")
    print(f"时间: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')} 北京时间")
    print(f"目标: 27所高校\n")

    # 读取数据
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    universities = data["universities"]
    changes = []
    results = []

    # 逐校检查
    for i, u in enumerate(universities):
        name = u["name"]
        status = u["status"]
        print(f"[{i+1}/27] 检查 {name} ({status})...", end=" ")
        sys.stdout.flush()

        result = check_university(u)
        results.append(result)

        if result["error"]:
            print(f"❌ {result['error']}")
        elif result["new_notices"]:
            count = len(result["new_notices"])
            print(f"📋 找到 {count} 条相关条目")
            for item in result["new_notices"][:3]:
                print(f"   → {item['text'][:60]}...")
            changes.append(result)
        else:
            print("✓ 无新内容")

        # 礼貌间隔，避免被封
        if i < len(universities) - 1:
            time.sleep(1)

    # 汇总
    print(f"\n=== 检查完成 ===")
    print(f"共检查 {len(universities)} 所高校")
    print(f"有潜在新内容的: {len(changes)} 所")

    # 更新数据文件的时间戳
    data["last_updated"] = datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")

    # 自动更新：如果 pending 的高校发现了新通知，更新 notice_url_link
    for c in changes:
        for u in universities:
            if u["name"] == c["university"] and u["status"] == "pending" and c["new_notices"]:
                # 取第一个匹配的链接
                first = c["new_notices"][0]
                u["notice_url_link"] = first["url"]
                u["notice_title"] = first["text"]
                u["notice_date"] = parse_date_from_text(first["text"]) or datetime.now(TZ).strftime("%Y-%m")
                print(f"\n🔗 自动更新 {u['name']} 的通知链接: {first['url']}")
                break

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 输出给 GitHub Actions 用的变更摘要
    has_changes = len(changes) > 0
    
    # 生成变更报告
    if has_changes:
        print("\n⚠️ 检测到潜在变化，建议人工复核:")
        for c in changes:
            print(f"\n【{c['university']}】当前状态: {c['status']}")
            for item in c['new_notices'][:5]:
                print(f"  📎 {item['text']}")
                print(f"     {item['url']}")

    return has_changes


if __name__ == "__main__":
    changed = main()
    sys.exit(0 if not changed else 1)
