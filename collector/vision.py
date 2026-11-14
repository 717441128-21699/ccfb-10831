"""轻量视觉工具：二值化、墨迹裁切、空白列切分、归一化模板匹配。

不依赖 tesseract 等外部 OCR——仿真站的字形来自系统字体，
用 PIL 渲染标准模板即可稳定识别，也更可控。
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

DIGITS = "0123456789"
SYSTEM_FONTS = [
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
]
NORM_W, NORM_H = 28, 36


def to_binary(img: Image.Image, threshold: int = 160) -> np.ndarray:
    gray = img.convert("L")
    arr = np.asarray(gray)
    return (arr < threshold).astype(np.uint8)


def crop_ink(bin_img: np.ndarray) -> np.ndarray:
    """裁掉四周空白，返回墨迹包围盒区域；空图返回原样。"""
    cols = np.where(bin_img.sum(axis=0) > 0)[0]
    rows = np.where(bin_img.sum(axis=1) > 0)[0]
    if len(cols) == 0 or len(rows) == 0:
        return bin_img
    return bin_img[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]


def normalize(bin_img: np.ndarray) -> np.ndarray:
    cropped = crop_ink(bin_img)
    img = Image.fromarray((cropped * 255).astype(np.uint8))
    img = img.resize((NORM_W, NORM_H), Image.BILINEAR)
    return (np.asarray(img) > 127).astype(np.uint8)


def diff_score(a: np.ndarray, b: np.ndarray) -> float:
    """归一化汉明距离，0 完全一致，1 完全不同。"""
    if a.shape != b.shape:
        raise ValueError("shape mismatch")
    return float(np.mean(a != b))


def segment_by_blank_columns(bin_img: np.ndarray) -> list[tuple[int, int, tuple[int, int]]]:
    """按全空白列切分字符，返回 [(左列, 右列, (顶行, 底行)), ...]。

    不做相邻组件合并——数字间即使只有 1px 空隙也是两个字。
    """
    ink_cols = bin_img.sum(axis=0) > 0
    comps: list[tuple[int, int, tuple[int, int]]] = []
    in_comp = False
    start = 0
    for x, has_ink in enumerate(ink_cols):
        if has_ink and not in_comp:
            in_comp, start = True, x
        elif not has_ink and in_comp:
            seg = bin_img[:, start:x]
            rows = np.where(seg.sum(axis=1) > 0)[0]
            comps.append((start, x - 1, (int(rows[0]), int(rows[-1]))))
            in_comp = False
    if in_comp:
        seg = bin_img[:, start:]
        rows = np.where(seg.sum(axis=1) > 0)[0]
        comps.append((start, bin_img.shape[1] - 1, (int(rows[0]), int(rows[-1]))))
    return comps


def render_template(char: str, font_path: str, size: int = 26) -> np.ndarray:
    font = ImageFont.truetype(font_path, size)
    img = Image.new("L", (size * 2, size * 2), 255)
    draw = ImageDraw.Draw(img)
    draw.text((size // 2, size // 4), char, fill=0, font=font)
    return normalize(to_binary(img))


def build_digit_templates() -> dict[str, list[np.ndarray]]:
    """每个数字在多套系统字体下的模板，匹配时任取最佳。"""
    templates: dict[str, list[np.ndarray]] = {d: [] for d in DIGITS}
    for fp in SYSTEM_FONTS:
        for d in DIGITS:
            templates[d].append(render_template(d, fp))
    return templates


def classify_digit(bin_img: np.ndarray, templates: dict[str, list[np.ndarray]]) -> tuple[str, float]:
    norm = normalize(bin_img)
    best_digit, best_score = "?", 1.0
    for d, tpls in templates.items():
        score = min(diff_score(norm, t) for t in tpls)
        if score < best_score:
            best_digit, best_score = d, score
    return best_digit, best_score


def ocr_digits(img: Image.Image, templates: dict[str, list[np.ndarray]] | None = None) -> tuple[str, float]:
    """识别一张只含数字与一个小数点的图，返回 (文本, 最差单字置信距离)。

    小数点判定：高度明显小于数字中位高度，且位于数字基线附近（图像下半部）。
    """
    if templates is None:
        templates = build_digit_templates()
    binarized = to_binary(img)
    comps = segment_by_blank_columns(binarized)
    if not comps:
        return "", 1.0

    heights = sorted(bottom - top + 1 for _l, _r, (top, bottom) in comps)
    median_h = heights[len(heights) // 2]
    total_h = binarized.shape[0]

    chars: list[str] = []
    worst = 0.0
    for l, r, (top, bottom) in comps:
        h = bottom - top + 1
        w = r - l + 1
        # 小数点：矮、小、垂直位置落在基线一带
        if h < median_h * 0.55 and w <= median_h * 0.7 and top > total_h * 0.45:
            chars.append(".")
            continue
        seg = binarized[:, l:r + 1]
        digit, score = classify_digit(seg, templates)
        worst = max(worst, score)
        chars.append(digit)
    return "".join(chars), worst
