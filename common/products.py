"""商品目录：4 个市场各自经营的蔬果品类。"""
from __future__ import annotations

# (product_code, 名称, 单位)
PRODUCTS: dict[str, list[tuple[str, str, str]]] = {
    "m1": [
        ("bj", "白菜", "元/公斤"),
        ("lh", "黄瓜", "元/公斤"),
        ("fqh", "番茄", "元/公斤"),
        ("tudou", "土豆", "元/公斤"),
        ("yangcong", "洋葱", "元/公斤"),
        ("luobo", "白萝卜", "元/公斤"),
        ("qiezi", "茄子", "元/公斤"),
        ("jiazi", "尖椒", "元/公斤"),
        ("xhs", "西红柿", "元/公斤"),
        ("suanmiao", "蒜苗", "元/公斤"),
    ],
    "m2": [
        ("pg", "苹果", "元/公斤"),
        ("xiangjiao", "香蕉", "元/公斤"),
        ("juzi", "蜜橘", "元/公斤"),
        ("pu", "葡萄", "元/公斤"),
        ("li", "梨", "元/公斤"),
        ("xigua", "西瓜", "元/公斤"),
        ("caomei", "草莓", "元/公斤"),
        ("mihoutao", "猕猴桃", "元/公斤"),
    ],
    "m3": [
        ("huolongguo", "火龙果", "元/公斤"),
        ("shiliu", "石榴", "元/公斤"),
        ("mangguo", "芒果", "元/公斤"),
        ("boluo", "菠萝", "元/公斤"),
        ("yemao", "椰子", "元/个"),
        ("ganzhe", "甘蔗", "元/公斤"),
    ],
    "m4": [
        ("tudou", "土豆", "元/公斤"),
        ("luobo", "白萝卜", "元/公斤"),
        ("ganlan", "甘蓝", "元/公斤"),
        ("huluobo", "胡萝卜", "元/公斤"),
        ("baocai", "包菜", "元/公斤"),
        ("shanyao", "山药", "元/公斤"),
        ("yumi", "鲜玉米", "元/穗"),
        ("digua", "红薯", "元/公斤"),
    ],
}


def product_name(market_id: str, code: str) -> str:
    for c, n, _u in PRODUCTS[market_id]:
        if c == code:
            return n
    raise KeyError(code)


def product_unit(market_id: str, code: str) -> str:
    for c, _n, u in PRODUCTS[market_id]:
        if c == code:
            return u
    raise KeyError(code)
