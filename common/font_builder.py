"""自定义字体构造器（仿真站 m1 使用）。

每天基于系统字体生成一份新 TTF：数字 0-9、小数点、减号被映射到
Unicode 私用区（PUA, U+E000 起）的随机码位，且码位顺序每天洗牌。
页面 HTML 里写的是 PUA 字符，源码层面完全是「乱码」，只有加载当天
字体才能看到真实数字。

采集端不依赖这里的映射表（映射表也不会对外暴露），而是通过浏览器
探针渲染自行解码，见 collector/font_decoder.py。
"""
from __future__ import annotations

import json
import random
from datetime import date
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

# 页面价格里只会出现这些字符
GLYPH_CHARS = "0123456789.-"
PUA_BASE = 0xE000

# 每天轮换不同的源字体，模拟「字体文件本身也在变」
SOURCE_FONTS = [
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
]


def build_daily_font(day: date, out_dir: Path) -> dict:
    """生成当日字体，返回 {pua_char: real_char} 映射（仅仿真站私有使用）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    seed = int(day.strftime("%Y%m%d"))
    rng = random.Random(seed)
    source = SOURCE_FONTS[seed % len(SOURCE_FONTS)]

    font = TTFont(source)
    # 只保留需要的字形，得到一个干净的小字体
    options = subset.Options()
    options.name_IDs = ["*"]
    options.recalc_bounds = True
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=GLYPH_CHARS)
    subsetter.subset(font)

    # 取每个真实字符当前对应的字形名
    cmap = font.getBestCmap()
    glyph_of = {ch: cmap[ord(ch)] for ch in GLYPH_CHARS}

    # 洗牌 PUA 码位：真实字符 -> 随机 PUA 码位
    pua_codes = [PUA_BASE + i for i in range(len(GLYPH_CHARS))]
    rng.shuffle(pua_codes)
    char_to_pua = {ch: pua for ch, pua in zip(GLYPH_CHARS, pua_codes)}

    # 重写 cmap：PUA 码位 -> 原真实字形；删掉真实码位，确保源码里看不到数字
    for table in font["cmap"].tables:
        table.cmap = {}
    for table in font["cmap"].tables:
        for ch, pua in char_to_pua.items():
            table.cmap[pua] = glyph_of[ch]
    font["cmap"].tables = [t for t in font["cmap"].tables if t.isUnicode()]
    # name 表改成伪装名称
    for record in font["name"].names:
        if record.nameID in (1, 4, 6):
            record.string = f"AgriQuote{seed}".encode("utf-16-be")

    font_path = out_dir / f"agriquote-{day.isoformat()}.ttf"
    font.save(str(font_path))

    mapping = {chr(pua): ch for ch, pua in char_to_pua.items()}
    meta = {
        "day": day.isoformat(),
        "source_font": source,
        "char_to_pua": char_to_pua,
        "pua_to_char": mapping,
        "font_file": font_path.name,
    }
    (out_dir / f"agriquote-{day.isoformat()}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def encode_text(text: str, char_to_pua: dict[str, int]) -> str:
    """把真实价格文本转成页面上显示的 PUA 乱码文本。"""
    return "".join(chr(char_to_pua[ch]) for ch in text)
