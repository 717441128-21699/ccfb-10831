"""仿真市场 m3：临港果批 —— 接口参数带前端现算签名。

- 页面脚本里挂了多个「看起来像签名」的函数，只有一个是当前生效的；
- 生效算法按日期在 MD5 / HMAC-SHA256 两套之间轮换，函数名也每天变；
- 服务端用同样规则验签，签名错误返回 401。
采集端不允许写死算法或函数名，必须在页面环境里发现并试跑（见
collector/sign_finder.py）。
"""
from __future__ import annotations

import hashlib
import hmac
import sqlite3
from datetime import date, datetime

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from common.calendar_def import close_reason
from common.config import MARKETS, MOCK_DB

app = FastAPI(title="临港果品批发市场（仿真）")
SPEC = MARKETS["m3"]

SECRET = b"lingang-secret-2026"
# 两套算法的当日函数名（名字本身也无规律，采集端不能靠名字猜）
FUNC_NAMES = {
    "md5": ("buildXToken", "q9f2"),
    "hmac": ("mkSecSign", "z3k7"),
}


def _algo_for(day: date) -> str:
    return "md5" if day.toordinal() % 2 == 0 else "hmac"


def server_sign(day: date, params: dict[str, str]) -> str:
    algo = _algo_for(day)
    base = "&".join(f"{k}={params[k]}" for k in sorted(params))
    if algo == "md5":
        return hashlib.md5(f"{base}#{day.isoformat()}".encode()).hexdigest()
    return hmac.new(SECRET, base.encode(), hashlib.sha256).hexdigest()


@app.get("/", response_class=HTMLResponse)
def index(day: str | None = Query(default=None)):
    target = date.fromisoformat(day) if day else datetime.now().date()
    reason = close_reason("m3", target)
    if reason:
        return HTMLResponse(
            f"<html><body><h1>临港果品批发市场</h1><p>{target} {reason}，今日休市。</p></body></html>"
        )
    algo = _algo_for(target)
    md5_name, hmac_name = FUNC_NAMES["md5"][0], FUNC_NAMES["hmac"][0]
    active_name = md5_name if algo == "md5" else hmac_name
    # 另一套算法的函数也在页面里（过期但仍可调用），外加两个纯诱饵函数
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>临港果批 行情接口</title></head>
<body><h1>临港果品批发市场 · 数据服务</h1>
<p>报价日期：{target}。行情数据通过 /api/quotes 提供，需携带前端签名。</p>
<script>
const SECRET = "lingang-secret-2026";
function _sorted(p) {{ return Object.keys(p).sort().map(k => k + "=" + p[k]).join("&"); }}
// 算法 A：MD5（与日期盐拼接）
function {md5_name}(params, day) {{
  return md5hex(_sorted(params) + "#" + day);
}}
// 算法 B：HMAC-SHA256
function {hmac_name}(params, day) {{
  return hmacSha256Hex(SECRET, _sorted(params));
}}
// —— 以下为页面历史遗留 / 监控用函数，与行情接口无关（诱饵）——
function makeTrafficSign(params) {{ return md5hex(JSON.stringify(params)).slice(0, 16); }}
function signForTracker(uid) {{ return "tk_" + md5hex(uid + SECRET).slice(0, 12); }}
function {FUNC_NAMES['md5'][1]}() {{ return Math.floor(Date.now() / 1000); }}
function {FUNC_NAMES['hmac'][1]}(s) {{ return s.split("").reverse().join(""); }}

// 最小 MD5 / HMAC-SHA256 实现（页面自带，仿真真实站点把加密库打进前端包）
// 标准 MD5（RFC 1321），输入按 UTF-8 编码
function md5hex(s) {{
  function rl(x,c){{return (x<<c)|(x>>>(32-c));}}
  function add32(a,b){{return (a+b)&0xffffffff;}}
  const bytes=Array.from(new TextEncoder().encode(s));
  const bitLen=bytes.length*8;
  bytes.push(0x80);
  while(bytes.length%64!==56)bytes.push(0);
  const lo=bitLen>>>0, hi=Math.floor(bitLen/0x100000000)>>>0;
  bytes.push(lo&0xff,lo>>>8&0xff,lo>>>16&0xff,lo>>>24&0xff);
  bytes.push(hi&0xff,hi>>>8&0xff,hi>>>16&0xff,hi>>>24&0xff);
  let a0=0x67452301,b0=0xefcdab89,c0=0x98badcfe,d0=0x10325476;
  const K=[0xd76aa478,0xe8c7b756,0x242070db,0xc1bdceee,0xf57c0faf,0x4787c62a,0xa8304613,0xfd469501,
    0x698098d8,0x8b44f7af,0xffff5bb1,0x895cd7be,0x6b901122,0xfd987193,0xa679438e,0x49b40821,
    0xf61e2562,0xc040b340,0x265e5a51,0xe9b6c7aa,0xd62f105d,0x02441453,0xd8a1e681,0xe7d3fbc8,
    0x21e1cde6,0xc33707d6,0xf4d50d87,0x455a14ed,0xa9e3e905,0xfcefa3f8,0x676f02d9,0x8d2a4c8a,
    0xfffa3942,0x8771f681,0x6d9d6122,0xfde5380c,0xa4beea44,0x4bdecfa9,0xf6bb4b60,0xbebfbc70,
    0x289b7ec6,0xeaa127fa,0xd4ef3085,0x04881d05,0xd9d4d039,0xe6db99e5,0x1fa27cf8,0xc4ac5665,
    0xf4292244,0x432aff97,0xab9423a7,0xfc93a039,0x655b59c3,0x8f0ccc92,0xffeff47d,0x85845dd1,
    0x6fa87e4f,0xfe2ce6e0,0xa3014314,0x4e0811a1,0xf7537e82,0xbd3af235,0x2ad7d2bb,0xeb86d391];
  const S=[7,12,17,22,7,12,17,22,7,12,17,22,7,12,17,22,
    5,9,14,20,5,9,14,20,5,9,14,20,5,9,14,20,
    4,11,16,23,4,11,16,23,4,11,16,23,4,11,16,23,
    6,10,15,21,6,10,15,21,6,10,15,21,6,10,15,21];
  for(let off=0;off<bytes.length;off+=64){{
    const M=[];
    for(let j=0;j<16;j++)
      M[j]=(bytes[off+j*4])|(bytes[off+j*4+1]<<8)|(bytes[off+j*4+2]<<16)|(bytes[off+j*4+3]<<24);
    let a=a0,b=b0,c=c0,d=d0;
    for(let i=0;i<64;i++){{
      let f,g;
      if(i<16){{f=(b&c)|((~b)&d);g=i;}}
      else if(i<32){{f=(b&d)|(c&(~d));g=(5*i+1)%16;}}
      else if(i<48){{f=b^c^d;g=(3*i+5)%16;}}
      else {{f=c^(b|(~d));g=(7*i)%16;}}
      f=add32(f,add32(add32(a,K[i]),M[g]));
      a=d;d=c;c=b;b=add32(b,rl(f,S[i]));
    }}
    a0=add32(a0,a);b0=add32(b0,b);c0=add32(c0,c);d0=add32(d0,d);
  }}
  const words=[a0,b0,c0,d0];
  let h="";
  for(const w of words)
    h+=[0,1,2,3].map(sh=>((w>>>(sh*8))&0xff).toString(16).padStart(2,"0")).join("");
  return h;
}}

async function hmacSha256Hex(keyStr, msg) {{
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(keyStr), {{name:"HMAC",hash:"SHA-256"}}, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(msg));
  return Array.from(new Uint8Array(sig)).map(b=>b.toString(16).padStart(2,"0")).join("");
}}
window.__ACTIVE_SIGNER__ = "{active_name}";
</script>
</body></html>"""
    return HTMLResponse(html)


@app.get("/api/quotes")
def quotes(
    request: Request,
    day: str = Query(...),
    market: str = Query("m3"),
    sign: str = Query(...),
    ts: str = Query(...),
):
    target = date.fromisoformat(day)
    if close_reason("m3", target):
        return JSONResponse({"closed": True}, status_code=409)
    params = {"day": day, "market": market, "ts": ts}
    expected = server_sign(target, params)
    if not hmac.compare_digest(expected, sign):
        return JSONResponse({"error": "bad sign", "expected_algo": _algo_for(target)}, status_code=401)

    con = sqlite3.connect(MOCK_DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM truth_prices WHERE market_id=? AND day=? ORDER BY product_code,price_type",
        ("m3", target.isoformat()),
    ).fetchall()
    con.close()
    return JSONResponse(
        {
            "day": day,
            "algo": _algo_for(target),
            "quotes": [
                {
                    "product_code": r["product_code"],
                    "price_type": r["price_type"],
                    "price": r["price"],
                }
                for r in rows
            ],
        }
    )


@app.get("/health")
def health():
    return JSONResponse({"market": "m3", "ok": True})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8013, log_level="warning")
