"""字体解码器（对应需求 1：映射每天换，自动重新解）。

思路完全在浏览器侧完成，不读取仿真站私有映射、不解析字体二进制：
1. 打开行情页，收集价格单元格里出现的所有 PUA 字符；
2. 在页面 DOM 里注入探针，让每个 PUA 字符按页面自带的 @font-face
   单独渲染成小图并截图；
3. 用系统字体渲染 0-9 / . / - 的标准模板，做归一化像素匹配；
4. 得到 {PUA 字符: 真实字符}，再回填整条价格。
每次采集都重新解码一次，天然适配每日更换的字体。
"""
from __future__ import annotations

import io
from datetime import date

import numpy as np
from PIL import Image
from playwright.sync_api import Page

from collector.vision import (
    build_digit_templates, classify_digit, crop_ink, normalize, to_binary,
)

PROBE_JS = """
(uniqueChars) => {
  const probes = [];
  const host = document.createElement('div');
  host.dataset.probeHost = '1';
  host.style.cssText = 'position:fixed;left:0;top:0;z-index:99999;background:#fff;';
  document.body.appendChild(host);
  const sample = document.querySelector('.price');
  const fam = sample ? getComputedStyle(sample).fontFamily : '';
  for (const ch of uniqueChars) {
    const el = document.createElement('span');
    el.textContent = ch;
    el.style.cssText = 'font-size:30px;padding:4px 8px;display:inline-block;color:#000;';
    if (fam) el.style.fontFamily = fam;
    host.appendChild(el);
    probes.push(el);
  }
  return probes.map(el => {
    const r = el.getBoundingClientRect();
    return {x: r.x, y: r.y, w: r.width, h: r.height};
  });
}
"""


def _looks_like_minus(norm: np.ndarray) -> bool:
    rows = np.where(norm.sum(axis=1) > 0)[0]
    cols = np.where(norm.sum(axis=0) > 0)[0]
    if len(rows) == 0 or len(cols) == 0:
        return False
    h = rows[-1] - rows[0] + 1
    w = cols[-1] - cols[0] + 1
    return h <= 6 and w >= 14


def decode_page_font(page: Page, selector: str = ".price") -> dict[str, str]:
    """返回当前页面 PUA 字符 -> 真实字符的映射。"""
    cells = page.locator(selector)
    count = cells.count()
    unique: set[str] = set()
    for i in range(count):
        unique.update(cells.nth(i).inner_text().strip())
    if not unique:
        return {}

    rects = page.evaluate(PROBE_JS, list(unique))
    templates = build_digit_templates()

    # 先取每个探针的二值图与墨迹裁切（保留原始几何尺寸，不做拉伸归一化）
    probes: list[tuple[str, np.ndarray]] = []
    for ch, rect in zip(unique, rects):
        shot = page.screenshot(
            clip={
                "x": max(rect["x"], 0),
                "y": max(rect["y"], 0),
                "width": max(rect["w"], 8),
                "height": max(rect["h"], 10),
            }
        )
        img = Image.open(io.BytesIO(shot))
        cropped = crop_ink(to_binary(img))
        probes.append((ch, cropped))

    # 数字字形高度接近，用中位字高作为点/减号的几何基准
    heights = sorted(p.shape[0] for _ch, p in probes)
    median_h = heights[len(heights) // 2]

    mapping: dict[str, str] = {}
    for ch, cropped in probes:
        h, w = cropped.shape
        # 小数点：又矮又窄；减号：矮但横向拉长
        if h < median_h * 0.45 and w < median_h * 0.7:
            mapping[ch] = "."
            continue
        if h < median_h * 0.4 and w >= median_h * 0.9:
            mapping[ch] = "-"
            continue
        norm = normalize(cropped)
        digit, _score = classify_digit(norm, templates)
        mapping[ch] = digit

    page.evaluate(
        """() => { const h = document.querySelector('[data-probe-host]');
                   if (h) h.remove(); }"""
    )
    return mapping


def decode_price(raw: str, mapping: dict[str, str]) -> str:
    return "".join(mapping.get(ch, "?") for ch in raw)


def save_mapping(con, market_id: str, day: date, mapping: dict[str, str]) -> None:
    con.execute("DELETE FROM font_mappings WHERE market_id=? AND day=?", (market_id, day.isoformat()))
    con.executemany(
        "INSERT INTO font_mappings(market_id,day,pua_char,real_char,method) VALUES(?,?,?,?,?)",
        [
            (market_id, day.isoformat(), pua, real, "browser_probe_template_match")
            for pua, real in mapping.items()
        ],
    )
    con.commit()
