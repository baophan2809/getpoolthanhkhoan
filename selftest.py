#!/usr/bin/env python3
"""Self-test offline: kiểm tra phần encode/decode/parse mà không cần mạng."""
from keccak import selector, event_topic, keccak256
from evm import enc, dec_addr, dec_uint, dec_int, dec_string, words, topic_addr
from discovery import (_pool_from_log, TOPIC_PAIR_CREATED, TOPIC_POOL_CREATED_V3,
                       TOPIC_POOL_CREATED_SOLIDLY, Candidate, _merge)
from valuation import Pool, spot_price_1_per_0
from evm import TokenMeta
from poolscan import fmt_usd, fmt_amt, table, alpha_summary

ok = 0


def check(name, cond):
    global ok
    assert cond, f"FAIL: {name}"
    ok += 1
    print(f"  ok  {name}")


# ---- keccak / selector
check("keccak rong", keccak256(b"").hex().startswith("c5d24601"))
check("selector transfer", selector("transfer(address,uint256)") == "0xa9059cbb")
check("topic PairCreated",
      TOPIC_PAIR_CREATED == "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9")
check("topic PoolCreated v3",
      TOPIC_POOL_CREATED_V3 == "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118")
check("topic PoolCreated solidly khac v3", TOPIC_POOL_CREATED_SOLIDLY != TOPIC_POOL_CREATED_V3)

# ---- encode
A = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
B = "0x55d398326f99059fF775485246999027B3197955"
d = enc("getPair(address,address)", A, B)
check("encode getPair do dai", len(d) == 2 + 8 + 128)
check("encode getPair selector", d.startswith(selector("getPair(address,address)")))
check("encode getPair chua addr A", A.lower()[2:] in d)
d3 = enc("getPool(address,address,uint24)", A, B, 2500)
check("encode getPool fee", d3.endswith(hex(2500)[2:].rjust(64, "0")))
check("encode balanceOf", enc("balanceOf(address)", A) ==
      "0x70a08231" + "000000000000000000000000" + A.lower()[2:])

# ---- decode
raw = "0x" + "0" * 24 + B.lower()[2:]
check("dec_addr", dec_addr(raw) == B.lower())
check("dec_uint", dec_uint("0x" + hex(123456)[2:].rjust(64, "0")) == 123456)
neg = (1 << 256) - 5
check("dec_int am", dec_int("0x" + hex(neg)[2:].rjust(64, "0")) == -5)

# symbol() dạng string động
s = ("0x"
     + hex(32)[2:].rjust(64, "0")
     + hex(4)[2:].rjust(64, "0")
     + b"CAKE".hex().ljust(64, "0"))
check("dec_string dong", dec_string(s) == "CAKE")
# symbol() dạng bytes32 (token đời cũ)
b32 = "0x" + b"MKR".hex().ljust(64, "0")
check("dec_string bytes32", dec_string(b32) == "MKR")

# ---- parse log tạo pool
pair = "0x0ed7e52944161450477ee417de9cd3a859b14fd0"
log_v2 = {"address": "0xca143ce32fe78f1f7019d7d551a6402fc5350c73",
          "topics": [TOPIC_PAIR_CREATED, topic_addr(A), topic_addr(B)],
          "data": "0x" + "0" * 24 + pair[2:] + hex(4211)[2:].rjust(64, "0")}
got, fee = _pool_from_log("v2", log_v2)
check("parse log v2", got == pair and fee is None)

pool_v3 = "0x36696169c63e42cd08ce11f5deebbcebae652050"
log_v3 = {"address": "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865",
          "topics": [TOPIC_POOL_CREATED_V3, topic_addr(A), topic_addr(B),
                     "0x" + hex(500)[2:].rjust(64, "0")],
          "data": "0x" + hex(10)[2:].rjust(64, "0") + "0" * 24 + pool_v3[2:]}
got, fee = _pool_from_log("v3", log_v3)
check("parse log v3 (bo qua tickSpacing)", got == pool_v3)
check("parse log v3 fee", fee == 500)

# ---- merge / khử trùng lặp
store = {}
_merge(store, Candidate(pair, "PancakeSwap V2", "v2", None, {"brute"}))
_merge(store, Candidate(pair.upper(), "?", "unknown", None, {"dexscreener"}))
check("merge 1 pool", len(store) == 1)
check("merge gop nguon", store[pair]. sources == {"brute", "dexscreener"})
check("merge giu ten dex tot", store[pair].dex == "PancakeSwap V2")

# ---- spot price
meta = {"0xaa": TokenMeta("0xaa", "TKN", 18), "0xbb": TokenMeta("0xbb", "USDT", 18)}
p = Pool("0xp", "x", "v2", None, set(), token0="0xaa", token1="0xbb")
p.reserves = (1000 * 10**18, 2500 * 10**18)
check("spot v2 = 2.5", abs(spot_price_1_per_0(p, meta) - 2.5) < 1e-9)

# v3: sqrtPriceX96 ứng với giá token1/token0 = 4 (cùng decimals)
import math
sq = int(math.isqrt(4) * (2**96))
p3 = Pool("0xp3", "x", "v3", 500, set(), token0="0xaa", token1="0xbb")
p3.sqrt_price_x96 = sq
check("spot v3 = 4", abs(spot_price_1_per_0(p3, meta) - 4.0) < 1e-6)

# decimals lệch: token0 6 decimals, token1 18 decimals, giá thật 1.0
meta2 = {"0xaa": TokenMeta("0xaa", "USDC", 6), "0xbb": TokenMeta("0xbb", "DAI", 18)}
sq2 = int((10 ** ((18 - 6) / 2)) * (2**96))
p4 = Pool("0xp4", "x", "v3", 100, set(), token0="0xaa", token1="0xbb")
p4.sqrt_price_x96 = sq2
val = spot_price_1_per_0(p4, meta2)
check(f"spot v3 lech decimals ~1.0 (duoc {val:.6f})", abs(val - 1.0) < 1e-6)

# ---- pool singleton (Infinity / V4) phai duoc tinh TVL, khong bi vut di
from valuation import value_pools, PriceBook

class _FakeRpc:
    def call(self, *a, **k): return None
    def call_many(self, calls, **k): return [None] * len(list(calls))

chain_stub = {"stables": {"0xbb": "USDT"}, "wnative": "0xcc", "factories": []}
book = PriceBook(_FakeRpc(), chain_stub, meta)

sp = Pool("0x" + "ab" * 32, "pancakeswap-infinity-clmm", "singleton", None, set())
sp.api_liquidity_usd = 2_000_000.0
value_pools([sp], book, meta)
check("singleton duoc tinh TVL", sp.tvl_usd == 2_000_000.0)
check("singleton co ghi chu uoc luong", "uoc luong" in sp.note)

sp2 = Pool("0x" + "cd" * 32, "uniswap-v4-bsc", "singleton", None, set())
value_pools([sp2], book, meta)
check("singleton khong co nguon -> tvl None", sp2.tvl_usd is None)

# ---- chi biet gia 1 ve -> suy ve kia tu ty gia spot cua pool
meta3 = {"0xaa": TokenMeta("0xaa", "TKN", 18), "0xbb": TokenMeta("0xbb", "USDT", 18)}
book3 = PriceBook(_FakeRpc(), {"stables": {"0xbb": "USDT"}, "wnative": "0xzz",
                               "factories": []}, meta3)
p5 = Pool("0xp5", "x", "v2", None, set(), token0="0xaa", token1="0xbb")
p5.bal0, p5.bal1 = 1000 * 10**18, 2500 * 10**18
p5.reserves = (p5.bal0, p5.bal1)
value_pools([p5], book3, meta3)
# USDT = $1 -> 2500 USDT; ty gia 2.5 USDT/TKN -> 1000 TKN = $2500 -> tong $5000
check(f"suy gia ve kia tu ty gia pool (duoc {p5.tvl_usd})", abs(p5.tvl_usd - 5000) < 1e-6)
check("co ghi chu suy gia", "suy tu ty gia pool" in p5.note)

# ---- do schema subgraph (khong can mang)
from subgraph import Subgraph, SubgraphError


def fake_schema(types, roots):
    return {"__schema": {"queryType": {"fields": [{"name": r} for r in roots]},
                         "types": types}}


def obj(name, fields):
    out = []
    for f in fields:
        if isinstance(f, tuple):
            out.append({"name": f[0], "type": {"kind": "OBJECT", "name": f[1],
                                               "ofType": None}})
        else:
            out.append({"name": f, "type": {"kind": "SCALAR", "name": "String",
                                            "ofType": None}})
    return {"name": name, "kind": "OBJECT", "fields": out}


def sg_with(types, roots):
    sg = Subgraph("k", "id")
    sg.query = lambda gql, variables=None: fake_schema(types, roots)
    return sg


# kieu Uniswap V3: token0/token1 la object
u = sg_with([obj("Pool", [("token0", "Token"), ("token1", "Token"),
                          "totalValueLockedUSD", "totalValueLockedToken0",
                          "totalValueLockedToken1", "feeTier"])], ["pools", "pool"])
f = u.discover_schema()
check("schema uniswap: entity Pool", f["entity"] == "Pool" and f["root"] == "pools")
check("schema uniswap: hai ve token0/token1", (f["tok0"], f["tok1"]) == ("token0", "token1"))
check("schema uniswap: token la object", f["tok_is_object"] is True)
check("schema uniswap: amt0", f["amt0"] == "totalValueLockedToken0")

# kieu Infinity/V4: currency0/currency1, lai la CHUOI dia chi chu khong phai object
i = sg_with([obj("Bundle", ["ethPriceUSD"]),
             obj("CLPool", ["currency0", "currency1", "tvlUSD",
                            "totalValueLockedCurrency0", "totalValueLockedCurrency1",
                            "lpFee"])],
            ["clPools", "bundles"])
f2 = i.discover_schema()
check("schema infinity: bat duoc CLPool", f2["entity"] == "CLPool")
check("schema infinity: root clPools", f2["root"] == "clPools")
check("schema infinity: currency0/1", (f2["tok0"], f2["tok1"]) == ("currency0", "currency1"))
check("schema infinity: token la chuoi", f2["tok_is_object"] is False)
check("schema infinity: tvl tvlUSD", f2["tvl_usd"] == "tvlUSD")
check("schema infinity: amt currency", f2["amt0"] == "totalValueLockedCurrency0")
check("schema infinity: fee lpFee", f2["fee"] == "lpFee")

# uu tien entity co du so luong ca hai ve
m = sg_with([obj("Pair", [("token0", "Token"), ("token1", "Token")]),
             obj("Pool", [("token0", "Token"), ("token1", "Token"),
                          "reserve0", "reserve1", "reserveUSD"])],
            ["pairs", "pools"])
check("uu tien entity co so luong token", m.discover_schema()["entity"] == "Pool")

# khong co entity nao hop le -> bao loi kem goi y
bad = sg_with([obj("Bundle", ["ethPriceUSD"]), obj("PoolDayData", ["date"])],
              ["bundles", "poolDayDatas"])
try:
    bad.discover_schema()
    check("schema hong phai nem loi", False)
except SubgraphError as e:
    check("schema hong phai nem loi", "khong tim thay entity pool" in str(e))
    check("loi co liet ke type giong pool", "PoolDayData" in str(e))

# ---- chuan hoa ten DEX: cung mot san khong duoc dem thanh nhieu san
from discovery import norm_dex
check("norm pancakeswap v2 (3 cach viet)",
      norm_dex("PancakeSwap V2") == norm_dex("pancakeswap v2") == norm_dex("pancakeswap_v2")
      == "PancakeSwap V2")
check("norm bo hau to chain", norm_dex("pancakeswap-v3-bsc") == "PancakeSwap V3")
check("norm uniswap v4", norm_dex("uniswap-v4-bsc") == "Uniswap V4")
check("norm infinity clmm", norm_dex("pancakeswap-infinity-clmm") == "PancakeSwap Infinity CL")
check("norm giu nguyen ten la", norm_dex("sanlaxyz") == "sanlaxyz")
check("norm khong lam hong '?'", norm_dex("?") == "?")

# ---- format
check("fmt_usd trieu", fmt_usd(2_500_000) == "$2.50M")
check("fmt_usd nghin", fmt_usd(1500) == "$1.5K")
check("fmt_usd none", fmt_usd(None) == "-")
check("fmt_amt nho", fmt_amt(0.000123) == "0.000123")

t = table([[1, "PancakeSwap V3", "$1.2M"]], ["#", "DEX", "TVL"], aligns="rlr")
check("table co header", "DEX" in t and "─┼─" in t)

# ---- alpha summary chịu được đổi tên field
entry = {"symbol": "X", "liquidity": "123456.78", "liquidityUsd": "1", "price": "0.5",
         "marketCap": "9", "holders": 100, "randomField": "bo qua"}
keys = [k for k, _ in alpha_summary(entry)]
check("alpha_summary bat liquidity", "liquidity" in keys and "liquidityUsd" in keys)
check("alpha_summary bo field la", "randomField" not in keys)

print(f"\n{ok} kiem tra deu PASS.")
