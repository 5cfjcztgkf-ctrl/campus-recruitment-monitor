#!/usr/bin/env python3
"""校招看板日报 - 每日22:00自动发送"""
import os
import json
import smtplib
import urllib.request
from email.mime.text import MIMEText
from email.utils import formataddr
from email.header import Header
from datetime import datetime, timezone, timedelta

# ========== 配置 ==========
REPO = "5cfjcztgkf-ctrl/campus-recruitment-monitor"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
QQ_MAIL = "972549902@qq.com"
QQ_AUTH = os.environ.get("QQ_MAIL_AUTH", "")
BJ = timezone(timedelta(hours=8))

# ========== 时间 ==========
now_bj = datetime.now(BJ)
today_str = now_bj.strftime("%Y-%m-%d")
today_date = now_bj.date()

# ========== GitHub API ==========
def gh_api(path):
    url = f"https://api.github.com/repos/{REPO}/{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "python",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

# ========== 1. 读取数据文件 ==========
with open("data/universities.json", encoding="utf-8") as f:
    uni_data = json.load(f)
with open("data/companies.json", encoding="utf-8") as f:
    comp_data = json.load(f)

# 高校看板
uni_last_raw = uni_data.get("last_updated", "")
uni_list = uni_data.get("universities", [])
published = sum(1 for u in uni_list if u.get("status") == "published")
partial = sum(1 for u in uni_list if u.get("status") == "partial")
pending = sum(1 for u in uni_list if u.get("status") == "pending")

# 友商看板
comp_last_raw = comp_data.get("last_updated", "")
comp_unis = comp_data.get("universities", [])
huawei_events = sum(len(u.get("huawei", {}).get("events", [])) for u in comp_unis)
cxmt_events = sum(len(u.get("cxmt", {}).get("events", [])) for u in comp_unis)
huawei_found = sum(1 for u in comp_unis if u.get("huawei", {}).get("status") == "found")
cxmt_found = sum(1 for u in comp_unis if u.get("cxmt", {}).get("status") == "found")

# ========== 2. 解析更新时间 ==========
def parse_time(t):
    if not t or t == "N/A":
        return None
    try:
        return datetime.fromisoformat(t).astimezone(BJ)
    except:
        return None

uni_last_dt = parse_time(uni_last_raw)
comp_last_dt = parse_time(comp_last_raw)
uni_updated_today = uni_last_dt and uni_last_dt.date() == today_date
comp_updated_today = comp_last_dt and comp_last_dt.date() == today_date

def fmt_time(dt):
    if not dt:
        return "N/A"
    return dt.strftime("%m/%d %H:%M")

# ========== 3. 查询今日 workflow 运行 ==========
runs = gh_api("actions/runs?per_page=100")
uni_runs = []
comp_runs = []
for r in runs.get("workflow_runs", []):
    dt = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).astimezone(BJ)
    if dt.date() != today_date:
        continue
    name = r.get("name", "")
    if name == "目标高校进校信息监控":
        uni_runs.append(r)
    elif name == "友商宣讲行程监控":
        comp_runs.append(r)

def count_runs(runs):
    total = len(runs)
    success = sum(1 for r in runs if r.get("conclusion") == "success")
    fail = sum(1 for r in runs if r.get("conclusion") in ("failure", "cancelled"))
    in_progress = total - success - fail
    return total, success, fail, in_progress

uni_total, uni_ok, uni_fail, uni_prog = count_runs(uni_runs)
comp_total, comp_ok, comp_fail, comp_prog = count_runs(comp_runs)

# ========== 4. 生成邮件 ==========
uni_icon = "✅" if uni_updated_today else "⬜"
comp_icon = "✅" if comp_updated_today else "⬜"

html = f"""\
<html><body style="font-family: -apple-system, 'PingFang SC', sans-serif; color: #333; max-width: 600px; margin: 0 auto;">

<h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 8px;">
  📡 校招看板日报 | {today_str}
</h2>

<h3 style="color: #333;">📊 数据更新</h3>
<table style="border-collapse: collapse; width: 100%; font-size: 14px;">
<tr style="background: #f5f5f5;">
  <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">看板</th>
  <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">今日更新</th>
  <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">最后更新时间</th>
</tr>
<tr>
  <td style="padding: 10px; border: 1px solid #ddd;">高校进校信息 ({len(uni_list)}校)</td>
  <td style="padding: 10px; border: 1px solid #ddd; text-align: center; font-size: 18px;">{uni_icon}</td>
  <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{fmt_time(uni_last_dt)}</td>
</tr>
<tr>
  <td style="padding: 10px; border: 1px solid #ddd;">友商宣讲行程 (华为&长鑫)</td>
  <td style="padding: 10px; border: 1px solid #ddd; text-align: center; font-size: 18px;">{comp_icon}</td>
  <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{fmt_time(comp_last_dt)}</td>
</tr>
</table>

<h3 style="color: #333;">⚙️ 监控运行</h3>
<table style="border-collapse: collapse; width: 100%; font-size: 14px;">
<tr style="background: #f5f5f5;">
  <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">看板</th>
  <th style="padding: 10px; border: 1px solid #ddd;">运行</th>
  <th style="padding: 10px; border: 1px solid #ddd;">成功</th>
  <th style="padding: 10px; border: 1px solid #ddd;">失败</th>
  <th style="padding: 10px; border: 1px solid #ddd;">进行中</th>
</tr>
<tr>
  <td style="padding: 10px; border: 1px solid #ddd;">高校检查</td>
  <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{uni_total}</td>
  <td style="padding: 10px; border: 1px solid #ddd; text-align: center; color: #1a73e8; font-weight: bold;">{uni_ok}</td>
  <td style="padding: 10px; border: 1px solid #ddd; text-align: center; color: {'#d93025' if uni_fail else '#999'};">{uni_fail}</td>
  <td style="padding: 10px; border: 1px solid #ddd; text-align: center; color: #999;">{uni_prog}</td>
</tr>
<tr>
  <td style="padding: 10px; border: 1px solid #ddd;">友商检查</td>
  <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{comp_total}</td>
  <td style="padding: 10px; border: 1px solid #ddd; text-align: center; color: #1a73e8; font-weight: bold;">{comp_ok}</td>
  <td style="padding: 10px; border: 1px solid #ddd; text-align: center; color: {'#d93025' if comp_fail else '#999'};">{comp_fail}</td>
  <td style="padding: 10px; border: 1px solid #ddd; text-align: center; color: #999;">{comp_prog}</td>
</tr>
</table>

<h3 style="color: #333;">📋 数据概览</h3>
<div style="background: #f9f9f9; padding: 12px; border-radius: 6px; font-size: 14px; line-height: 1.8;">
  <b>高校进校</b>：{published} 所已发布 / {partial} 所部分信息 / {pending} 所未发布<br>
  <b>友商宣讲</b>：华为 {huawei_events} 条宣讲（{huawei_found}校有记录）/ 长鑫存储 {cxmt_events} 条（{cxmt_found}校有记录）
</div>

<hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
<p style="color: #888; font-size: 12px;">
  📱 <a href="https://5cfjcztgkf-ctrl.github.io/campus-recruitment-monitor/">高校进校看板</a> | 
  <a href="https://5cfjcztgkf-ctrl.github.io/campus-recruitment-monitor/company-monitor/">友商宣讲看板</a><br>
  本邮件由 GitHub Actions 每日 22:00 自动发送
</p>
</body></html>
"""

# ========== 5. 发送邮件 ==========
msg = MIMEText(html, "html", "utf-8")
msg["From"] = formataddr((str(Header("校招看板", "utf-8")), QQ_MAIL))
msg["To"] = QQ_MAIL
msg["Subject"] = f"📡 校招看板日报 | {today_str}"

if not QQ_AUTH:
    print("WARNING: QQ_MAIL_AUTH not set, skipping email send")
    print("Email content preview:")
    print(html[:500])
else:
    smtp = smtplib.SMTP_SSL("smtp.qq.com", 465)
    smtp.login(QQ_MAIL, QQ_AUTH)
    smtp.sendmail(QQ_MAIL, QQ_MAIL, msg.as_string())
    smtp.quit()
    print(f"✅ 日报已发送至 {QQ_MAIL}")
