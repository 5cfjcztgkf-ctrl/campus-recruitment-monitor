#!/usr/bin/env python3
"""
企业宣讲会监控 - 自动检查脚本
追踪华为和长鑫存储在27所目标高校的2027届秋招宣讲会安排。

运行环境: GitHub Actions (ubuntu-latest)
需要安装: pip install requests beautifulsoup4
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("请先安装依赖: pip install requests beautifulsoup4")
    sys.exit(1)

# ============================================================
# 配置
# ============================================================

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "companies.json")
TZ = timezone(timedelta(hours=8))
REQUEST_TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (compatible; CompanyMonitor/1.0; +https://github.com)"

# 目标公司
TARGET_COMPANIES = ["华为", "长鑫存储"]

# 日期正则模式
DATE_PATTERNS = [
    (r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})', '{}-{:02d}-{:02d}'),
    (r'(\d{4})年(\d{1,2})月(\d{1,2})日', '{}-{:02d}-{:02d}'),
    (r'(\d{1,2})月(\d{1,2})日', None),  # 需要补充年份
]

# 排除词：不是宣讲会
EXCLUDE_KEYWORDS = ["实习", "提前批", "内推", "测评", "笔试", "面试"]

# 地点关键词
VENUE_KEYWORDS = ["教室", "报告厅", "会议室", "中心", "厅", "楼", "馆", "堂", "就业", "招聘", "活动"]


def fetch_page(url, encoding=None):
    """抓取网页内容"""
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT,
                          allow_redirects=True, verify=False)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return None, None, "timeout"
    except requests.exceptions.ConnectionError:
        return None, None, "connection_error"
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response else 'unknown'
        return None, None, f"http_error:{code}"
    except Exception as e:
        return None, None, f"error:{str(e)[:100]}"

    # 自动检测编码
    if encoding:
        resp.encoding = encoding
    elif resp.apparent_encoding:
        resp.encoding = resp.apparent_encoding
    else:
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


def extract_dates(text):
    """从文本提取日期列表，返回 [(原始匹配, 标准化日期), ...]"""
    results = []
    for pattern, fmt in DATE_PATTERNS:
        for m in re.finditer(pattern, text):
            if fmt:
                try:
                    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    if 2025 <= y <= 2027 and 1 <= mo <= 12 and 1 <= d <= 31:
                        results.append((m.group(0), fmt.format(y, mo, d)))
                except:
                    continue
            else:
                # 无年份，假设2026年
                try:
                    mo, d = int(m.group(1)), int(m.group(2))
                    if 1 <= mo <= 12 and 1 <= d <= 31:
                        results.append((m.group(0), f"2026-{mo:02d}-{d:02d}"))
                except:
                    continue
    return results


def extract_venue(text):
    """尝试从文本中提取地点"""
    # 常见地点模式
    patterns = [
        r'地点[：:]\s*(.{2,30}?)(?:$|\n|\r|\s{2,})',
        r'场地[：:]\s*(.{2,30}?)(?:$|\n|\r|\s{2,})',
        r'地址[：:]\s*(.{2,30}?)(?:$|\n|\r|\s{2,})',
        r'([\w\u4e00-\u9fff]+(?:教室|报告厅|会议室|大厅|中心|楼\d+|馆|堂))',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            venue = m.group(1).strip()
            if len(venue) >= 2:
                return venue
    return ""


def extract_time(text):
    """尝试从文本中提取时间"""
    patterns = [
        r'时间[：:]\s*(.{3,20}?)(?:$|\n|\r|\s{2,})',
        r'(\d{1,2}:\d{2}\s*[-~—至到]\s*\d{1,2}:\d{2})',
        r'(\d{1,2}:\d{2})',
        r'([上下中]午\d{1,2}[时点])',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip()
    return ""


def find_company_in_page(soup, base_url, company_name):
    """在页面中搜索指定公司，返回事件列表"""
    events = []
    body_text = soup.get_text()

    # 方法1：找包含公司名的链接
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        if company_name in text and not any(kw in text for kw in EXCLUDE_KEYWORDS):
            href = urljoin(base_url, a["href"])
            # 在父元素中找日期和地点
            parent = a.parent
            # 尝试找最近的包含日期/地点的父容器的完整文本
            container = parent
            for _ in range(5):
                if container is None:
                    break
                container_text = container.get_text(" ", strip=True)
                if len(container_text) > len(text) + 10:
                    break
                container = container.parent

            container_text = (container.get_text(" ", strip=True)
                            if container else parent.get_text(" ", strip=True))

            # 提取信息
            dates = extract_dates(container_text)
            venue = extract_venue(container_text)
            event_time = extract_time(container_text)

            # 排除太短的标题（不是宣讲会条目）
            if len(text) < 8:
                continue

            event = {
                "date": dates[0][1] if dates else "",
                "time": event_time,
                "venue": venue,
                "type": "宣讲会",
                "source_url": href,
                "notes": text
            }

            # 如果有多个日期，可能有多场
            if len(dates) > 1:
                for d in dates:
                    event_copy = event.copy()
                    event_copy["date"] = d[1]
                    event_copy["notes"] = text
                    if event_copy not in events:
                        events.append(event_copy)
            elif events.count(event) == 0:
                events.append(event)

    # 方法2：在文本中搜索（针对非链接形式的展示）
    if not events:
        lines = body_text.split('\n')
        for i, line in enumerate(lines):
            if company_name in line and not any(kw in line for kw in EXCLUDE_KEYWORDS):
                if len(line) < 8:
                    continue
                # 获取上下文（上下几行）
                context_start = max(0, i - 3)
                context_end = min(len(lines), i + 4)
                context = ' '.join(lines[context_start:context_end])
                dates = extract_dates(context)
                venue = extract_venue(context)
                event_time = extract_time(context)
                events.append({
                    "date": dates[0][1] if dates else "",
                    "time": event_time,
                    "venue": venue,
                    "type": "宣讲会",
                    "source_url": base_url,
                    "notes": line.strip()
                })

    # 去重并限制数量
    seen = set()
    unique_events = []
    for e in events:
        key = (e["date"], e["venue"], e["source_url"])
        if key not in seen:
            seen.add(key)
            unique_events.append(e)

    return unique_events[:5]  # 最多保留5个


def check_university(u):
    """检查单个高校的两个公司"""
    name = u["name"]
    search_url = u.get("presentation_search_url", "")
    results = {}

    if not search_url:
        return {"university": name, "results": {"huawei": {"status": "not_found", "events": []},
                                                  "cxmt": {"status": "not_found", "events": []}}}

    # 尝试搜索页面
    html, soup, error = fetch_page(search_url)
    if error:
        return {"university": name,
                "results": {"huawei": {"status": "not_found", "events": [], "_error": error},
                            "cxmt": {"status": "not_found", "events": [], "_error": error}}}

    # 搜索每个目标公司
    for company in TARGET_COMPANIES:
        events = find_company_in_page(soup, search_url, company)
        key = "huawei" if company == "华为" else "cxmt"

        if events:
            results[key] = {"status": "scheduled", "events": events}
        else:
            results[key] = {"status": "not_found", "events": []}

    return {"university": name, "results": results}


def main():
    print(f"=== 企业宣讲会监控自动检查 ===")
    print(f"时间: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')} 北京时间")
    print(f"目标: 27所高校 × 2家公司\n")

    # 忽略 SSL 警告（很多高校网站证书有问题）
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # 读取数据
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    universities = data["universities"]
    total_found = {"华为": 0, "长鑫存储": 0}
    errors = []

    for i, u in enumerate(universities):
        name = u["name"]
        print(f"[{i+1:2d}/27] 检查 {name}...", end=" ")
        sys.stdout.flush()

        result = check_university(u)
        r = result["results"]

        hw_status = r["huawei"]["status"]
        cx_status = r["cxmt"]["status"]
        hw_count = len(r["huawei"]["events"]) if r["huawei"]["events"] else 0
        cx_count = len(r["cxmt"]["events"]) if r["cxmt"]["events"] else 0

        # 更新数据
        u["huawei"] = r["huawei"]
        u["cxmt"] = r["cxmt"]

        # 打印状态
        status_icons = []
        if hw_status == "scheduled":
            status_icons.append(f"华为✅x{hw_count}")
            total_found["华为"] += 1
        else:
            status_icons.append("华为⚪")

        if cx_status == "scheduled":
            status_icons.append(f"长鑫✅x{cx_count}")
            total_found["长鑫存储"] += 1
        else:
            status_icons.append("长鑫⚪")

        print(" | ".join(status_icons))

        # 打印找到的事件摘要
        for company_key, label in [("huawei", "华为"), ("cxmt", "长鑫存储")]:
            evts = r[company_key]["events"]
            if evts:
                for evt in evts[:2]:
                    info = f"   {label}: {evt['date']} {evt['time']} @ {evt['venue']}"
                    if evt.get('notes'):
                        info += f" [{evt['notes'][:40]}]"
                    print(info)

        # 间隔
        if i < len(universities) - 1:
            time.sleep(1.5)

    # 汇总
    print(f"\n{'='*50}")
    print(f"=== 检查完成 ===")
    print(f"共检查 {len(universities)} 所高校")
    print(f"华为有宣讲会: {total_found['华为']} 所")
    print(f"长鑫存储有宣讲会: {total_found['长鑫存储']} 所")

    # 更新时间戳
    data["last_updated"] = datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"数据已保存到: {DATA_FILE}")

    has_changes = total_found["华为"] > 0 or total_found["长鑫存储"] > 0
    return has_changes


if __name__ == "__main__":
    changed = main()
    sys.exit(0)
