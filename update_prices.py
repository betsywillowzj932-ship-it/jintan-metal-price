from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36"
SMM_BASE = "https://hq.smm.cn"
COPPER_LIST = f"{SMM_BASE}/metal-scraps/list/14096"
STEEL_LIST = f"{SMM_BASE}/metal-scraps/list/12722"


def fetch(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    return raw.decode("utf-8", errors="replace")


def strip_tags(value: str) -> str:
    value = re.sub(r"<script[\s\S]*?</script>", "", value, flags=re.I)
    value = re.sub(r"<style[\s\S]*?</style>", "", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def find_latest_link(list_html: str, keyword: str) -> tuple[str | None, str | None]:
    pattern = re.compile(
        r'<a[^>]+href="(?P<href>/metal-scraps/content/\d+)"[^>]*>(?P<title>[\s\S]*?)</a>',
        re.I,
    )
    candidates = []
    for match in pattern.finditer(list_html):
        title = strip_tags(match.group("title"))
        if keyword in title:
            candidates.append((f"{SMM_BASE}{match.group('href')}", title))
    return candidates[0] if candidates else (None, None)


def parse_publish_datetime(page_html: str) -> str | None:
    match = re.search(r"发布时间：\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", page_html)
    if match:
        return match.group(1)
    return None


def parse_copper(today: dt.date) -> tuple[list[dict], dict]:
    try:
        list_html = fetch(COPPER_LIST)
        url, title = find_latest_link(list_html, "江苏废铜价格")
        if not url:
            raise RuntimeError("没有找到江苏废铜价格文章")
        page = fetch(url)
        publish_time = parse_publish_datetime(page)
        source_date = publish_time[:10] if publish_time else ""
        updated_today = source_date == today.isoformat()

        rows = []
        for block in re.findall(r'<tr class="table-tbody-row">([\s\S]*?)</tr>', page):
            cells = [strip_tags(cell) for cell in re.findall(r'<div class="cell[^"]*">([\s\S]*?)</div>', block)]
            if len(cells) < 6:
                continue
            name, price_range, average, change, unit, mmdd = cells[:6]
            if "江苏" not in name and "缆粗" not in name and "火烧线" not in name:
                continue
            rows.append(
                {
                    "name": name,
                    "spec": f"SMM江苏废铜价格，{name}",
                    "range": price_range,
                    "price": int(round(float(average))),
                    "change": float(change),
                    "unit": unit,
                    "source": "SMM江苏废铜价格",
                    "sourceUrl": url,
                    "sourceDate": source_date,
                    "updatedToday": updated_today,
                }
            )

        note = f"已读取{source_date}江苏废铜价格。" if updated_today else f"暂未更新，公开来源最新为{source_date or '未知日期'}江苏废铜价格。"
        return rows, {"updatedToday": updated_today, "message": "今日已更新" if updated_today else "暂未更新", "note": note}
    except Exception as exc:
        old = load_old_data()
        rows = old.get("copper", [])
        for item in rows:
            item["updatedToday"] = False
        return rows, {"updatedToday": False, "message": "暂未更新", "note": f"抓取失败：{exc}"}


def parse_steel(today: dt.date) -> tuple[list[dict], dict]:
    try:
        list_html = fetch(STEEL_LIST)
        links = []
        for match in re.finditer(r'<a[^>]+href="(?P<href>/metal-scraps/content/\d+)"[^>]*>(?P<title>[\s\S]*?)</a>', list_html, re.I):
            title = strip_tags(match.group("title"))
            if "废钢" not in title:
                continue
            if not any(key in title for key in ["沙钢", "南钢", "永钢", "江苏", "华东"]):
                continue
            url = f"{SMM_BASE}{match.group('href')}"
            links.append({"title": title, "url": url})
            if len(links) >= 8:
                break

        updated = False
        for item in links[:3]:
            try:
                page = fetch(item["url"])
                publish_time = parse_publish_datetime(page)
                item["publishTime"] = publish_time or ""
                if publish_time and publish_time[:10] == today.isoformat():
                    updated = True
            except Exception as exc:
                item["publishTime"] = ""
                item["error"] = str(exc)

        note = "已发现今日钢厂废钢报价更新；详细料型如为图片表，页面保留沙钢常州基地参考价。" if updated else "暂未发现今日钢厂废钢报价更新；下方显示沙钢常州基地参考价。"
        return links, {"updatedToday": updated, "message": "今日已更新" if updated else "暂未更新", "note": note}
    except Exception as exc:
        return [], {"updatedToday": False, "message": "暂未更新", "note": f"抓取失败：{exc}"}


def load_old_data() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def main() -> int:
    now = dt.datetime.now(ZoneInfo("Asia/Shanghai"))
    today = now.date()
    copper, copper_status = parse_copper(today)
    steel_sources, steel_status = parse_steel(today)

    data = {
        "generatedAt": now.isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "status": {"copper": copper_status, "steel": steel_status},
        "copper": copper,
        "steelSources": steel_sources,
    }
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {DATA_FILE}")
    print(json.dumps(data["status"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
