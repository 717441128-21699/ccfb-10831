"""签名发现器（对应需求 3：签名算法从页面脚本里跑出来，不写死）。

页面里同时存在多个候选函数（真实算法 + 过期算法 + 诱饵），采集端：
1. 枚举 window 上所有函数，过滤出参数形态像「签名器」的候选
   （2 个参数：params 对象 + 日期字符串；返回字符串）；
2. 用固定探针参数依次在浏览器内试跑，对 /api/quotes 发试探请求；
3. 返回 200 的即为当前生效签名器，记录函数名与试探过程快照。
整个过程不含任何写死的 md5/hmac 逻辑——算法始终在站点自己的页面里执行。
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from playwright.sync_api import Page

ENUM_JS = """
() => {
  const names = [];
  for (const k of Object.getOwnPropertyNames(window)) {
    try {
      if (typeof window[k] === 'function' && window[k].length === 2) names.push(k);
    } catch (e) {}
  }
  return names;
}
"""

CALL_JS = """
async ([name, params, day]) => {
  try {
    const v = await window[name](params, day);
    return {ok: true, value: String(v)};
  } catch (e) {
    return {ok: false, error: String(e)};
  }
}
"""


def enumerate_signer_candidates(page: Page) -> list[str]:
    return page.evaluate(ENUM_JS)


def try_sign(page: Page, func_name: str, params: dict[str, str], day: str) -> str | None:
    result = page.evaluate(CALL_JS, [func_name, params, day])
    if result.get("ok") and isinstance(result.get("value"), str) and len(result["value"]) >= 8:
        return result["value"]
    return None


def discover_signer(
    page: Page,
    day: date,
    probe_params: dict[str, str],
    probe_url_factory,
) -> dict[str, Any]:
    """在页面中发现生效签名器。

    probe_url_factory(params, sign) 生成试探请求 URL；返回 HTTP 状态码。
    返回 {signer, algo_response, attempts}，找不到时 signer=None。
    """
    candidates = enumerate_signer_candidates(page)
    attempts = []
    day_str = day.isoformat()
    for name in candidates:
        sign = try_sign(page, name, probe_params, day_str)
        if sign is None:
            attempts.append({"func": name, "skipped": "not-callable-or-bad-output"})
            continue
        status, body = probe_url_factory(probe_params, sign)
        attempts.append({"func": name, "http_status": status, "body_head": body[:120]})
        if status == 200:
            return {
                "signer": name,
                "algo_response": json.loads(body).get("algo"),
                "attempts": attempts,
                "candidate_count": len(candidates),
            }
    return {"signer": None, "algo_response": None, "attempts": attempts,
            "candidate_count": len(candidates)}


def sign_with(page: Page, func_name: str, params: dict[str, str], day: str) -> str:
    sign = try_sign(page, func_name, params, day)
    if sign is None:
        raise RuntimeError(f"页面签名函数 {func_name} 执行失败")
    return sign
