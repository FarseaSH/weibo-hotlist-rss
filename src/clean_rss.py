#!/usr/bin/env python3
"""
Clean and aggregate a Weibo hotlist RSS into a single-item RSS.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
from urllib.parse import parse_qs, quote, urlparse
from xml.etree import ElementTree as ET

import pytz


BEIJING_TZ = pytz.timezone("Asia/Shanghai")
UTC_TZ = timezone.utc


def parse_last_build_date(value: str | None) -> tuple[datetime, datetime]:
    """解析 lastBuildDate，并返回北京时间与对应 GMT 时间。"""
    if not value:
        bj_now = datetime.now(BEIJING_TZ)
        return bj_now, bj_now.astimezone(UTC_TZ)

    text = value.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S GMT", "%a, %d %b %Y %H:%M:%S"):
        try:
            naive_dt = datetime.strptime(text, fmt)
            # 输入里的 GMT 字样不可信，统一按北京时间理解。
            bj_dt = naive_dt.replace(tzinfo=BEIJING_TZ)
            return bj_dt, bj_dt.astimezone(UTC_TZ)
        except ValueError:
            continue

    bj_now = datetime.now(BEIJING_TZ)
    return bj_now, bj_now.astimezone(UTC_TZ)


def get_text(elem: ET.Element | None) -> str:
    """安全获取元素文本，自动拼接子节点并去掉首尾空白。"""
    if elem is None:
        return ""
    return "".join(elem.itertext()).strip()


def normalize_weibo_link(title: str, raw_link: str) -> str:
    """将原始链接规范成可打开的移动端搜索链接。"""
    # 原始 RSS 里常见换行/空白，先清理。
    cleaned_link = "".join(raw_link.split())
    parsed = urlparse(cleaned_link)
    query = parse_qs(parsed.query)
    # 优先使用链接里的 q 参数，否则退回到标题。
    keyword = query.get("q", [""])[0].strip() if query else ""
    if not keyword:
        keyword = title.strip()
    encoded_keyword = quote(keyword, safe="")
    return f"https://m.weibo.cn/search?containerid=100103type%3D1%26q%3D{encoded_keyword}"


def build_description(items: list[tuple[str, str]], capture_time: datetime) -> str:
    """构建聚合条目的 HTML 描述正文。"""
    lines: list[str] = ["<h2>微博热搜榜</h2>", "<ol>"]
    for title, link in items:
        # 统一链接格式，保证 RSS 阅读器里可打开。
        link = normalize_weibo_link(title, link)
        safe_title = html.escape(title, quote=True)
        safe_link = html.escape(link, quote=True)
        lines.append(
            f'<li><a href="{safe_link}" target="_blank">{safe_title}</a></li>'
        )
    lines.append("</ol>")
    lines.append(f'<p><small>采集时间: {capture_time.strftime("%Y-%m-%d %H:%M:%S")}</small></p>')
    return "\n".join(lines)


def indent(elem: ET.Element, level: int = 0) -> None:
    """为 xml.etree 输出添加缩进，使结果更易读。"""
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        for child in elem:
            indent(child, level + 1)
        if not elem[-1].tail or not elem[-1].tail.strip():
            elem[-1].tail = i
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = i


def aggregate_rss(input_path: str, output_path: str) -> None:
    """读取原始 RSS，聚合为单条 item 并写入新 RSS。"""
    tree = ET.parse(input_path)
    root = tree.getroot()
    channel = root.find("channel")
    if channel is None:
        raise ValueError("Missing channel in RSS input.")

    last_build_text = get_text(channel.find("lastBuildDate"))
    # 输入 lastBuildDate 视为北京时间，同时生成 GMT 用于标准字段。
    capture_time_bj, capture_time_gmt = parse_last_build_date(last_build_text)

    items: list[tuple[str, str]] = []
    for item in channel.findall("item"):
        title = get_text(item.find("title")) or "无标题"
        link = get_text(item.find("link")) or "#"
        items.append((title, link))

    # 构建新的 RSS 结构。
    rss = ET.Element("rss", {"version": "2.0", "xmlns:atom": "http://www.w3.org/2005/Atom"})
    out_channel = ET.SubElement(rss, "channel")

    ET.SubElement(out_channel, "title").text = "微博热搜榜 - 聚合版"
    ET.SubElement(out_channel, "link").text = "https://tophub.today/n/KqndgxeLl9"
    ET.SubElement(out_channel, "description").text = "每个条目包含一个时刻的所有热搜"
    ET.SubElement(out_channel, "language").text = "zh-cn"
    # 频道构建时间要求 GMT。
    ET.SubElement(out_channel, "lastBuildDate").text = capture_time_gmt.strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )

    agg_item = ET.SubElement(out_channel, "item")
    ET.SubElement(agg_item, "title").text = (
        f"微博热搜 - {capture_time_bj.strftime('%Y年%m月%d日 %H:%M')}"
    )
    ET.SubElement(agg_item, "link").text = "https://tophub.today/n/KqndgxeLl9"
    # item 内容展示用北京时间。
    ET.SubElement(agg_item, "description").text = build_description(
        items, capture_time_bj
    )
    # pubDate 按 GMT 输出。
    ET.SubElement(agg_item, "pubDate").text = capture_time_gmt.strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )
    ET.SubElement(agg_item, "guid", {"isPermaLink": "false"}).text = (
        f"weibo-hot-{capture_time_bj.strftime('%Y%m%d%H%M%S')}"
    )

    indent(rss)
    tree_out = ET.ElementTree(rss)
    tree_out.write(output_path, encoding="utf-8", xml_declaration=True)


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description="Aggregate a Weibo hotlist RSS into a single item."
    )
    parser.add_argument(
        "--input",
        default="demo_input.rss",
        help="Path to source RSS file.",
    )
    parser.add_argument(
        "--output",
        default="demo_output.rss",
        help="Path to write aggregated RSS file.",
    )
    args = parser.parse_args()

    aggregate_rss(args.input, args.output)


if __name__ == "__main__":
    main()
