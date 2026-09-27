#!/usr/bin/env python3
"""Chạy thử end-to-end với một BSC giả lập (không cần mạng).

Kịch bản:
  BNB = $600
  TKN/WBNB  (Pancake V2) : 1,000,000 TKN + 100 WBNB   -> TVL $120,000
  TKN/WBNB  (Biswap V2)  :   200,000 TKN +  20 WBNB   -> TVL  $24,000
  TKN/USDT  (Pancake V3) :   500,000 TKN + 30,000 USDT -> TVL  $60,000
  Tong ky vong: $204,000 ; gia TKN = $0.06
  Gop theo cap: TKN/WBNB = $144,000 (2 pool) ; TKN/USDT = $60,000 (1 pool)
"""
from __future__ import annotations

import math
import sys

import evm
import poolscan
from keccak import selector

TKN = "0x1111111111111111111111111111111111111111"
WBNB = "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"
USDT = "0x55d398326f99059ff775485246999027b3197955"
PAIR_TW = "0x2222222222222222222222222222222222222222"
PAIR_WU = "0x3333333333333333333333333333333333333333"
POOL_TU = "0x4444444444444444444444444444444444444444"
PAIR_TW2 = "0x5555555555555555555555555555555555555555"
F_V2 = "0xca143ce32fe78f1f7019d7d551a6402fc5350c73"
F_V3 = "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865"
F_BIS = "0x858e3312ed3a876947ea49d572a7c42de08af7ee"

E18 = 10 ** 18
BALANCES = {
    (TKN, PAIR_TW): 1_000_000 * E18,
    (WBNB, PAIR_TW): 100 * E18,
    (WBNB, PAIR_WU): 1_000 * E18,
    (USDT, PAIR_WU): 600_000 * E18,
    (TKN, PAIR_TW2): 200_000 * E18,
    (WBNB, PAIR_TW2): 20 * E18,
    (TKN, POOL_TU): 500_000 * E18,
    (USDT, POOL_TU): 30_000 * E18,
}
POOL_TOKENS = {PAIR_TW: (TKN, WBNB), PAIR_TW2: (TKN, WBNB),
               PAIR_WU: (WBNB, USDT), POOL_TU: (TKN, USDT)}
RESERVES = {PAIR_TW: (1_000_000 * E18, 100 * E18),
            PAIR_TW2: (200_000 * E18, 20 * E18),
            PAIR_WU: (1_000 * E18, 600_000 * E18)}
SQRT = {POOL_TU: int(math.sqrt(0.06) * (2 ** 96))}
SYMBOLS = {TKN: "TKN", WBNB: "WBNB", USDT: "USDT"}

SEL = {name: selector(name) for name in (
    "symbol()", "decimals()", "totalSupply()", "token0()", "token1()",
    "getReserves()", "slot0()", "balanceOf(address)",
    "getPair(address,address)", "getPool(address,address,uint24)",
    "getPool(address,address,bool)")}


def w_uint(n: int) -> str:
    return hex(n)[2:].rjust(64, "0")


def w_addr(a: str) -> str:
    return a.lower().replace("0x", "").rjust(64, "0")


def w_str(s: str) -> str:
    return w_uint(32) + w_uint(len(s)) + s.encode().hex().ljust(64, "0")


def arg_addr(data: str, i: int) -> str:
    return "0x" + data[10 + i * 64:10 + (i + 1) * 64][24:]


def handle(to: str, data: str):
    to = to.lower()
    sel = data[:10]

    if sel == SEL["symbol()"]:
        return "0x" + w_str(SYMBOLS.get(to, "TK" + to[2:5].upper()))
    if sel == SEL["decimals()"]:
        return "0x" + w_uint(18)
    if sel == SEL["totalSupply()"]:
        return "0x" + w_uint(10_000_000 * E18)

    if sel == SEL["balanceOf(address)"]:
        who = arg_addr(data, 0)
        return "0x" + w_uint(BALANCES.get((to, who), 0))

    if sel == SEL["getPair(address,address)"] and to == F_BIS:
        a, b = arg_addr(data, 0), arg_addr(data, 1)
        if {a, b} == {TKN, WBNB}:
            return "0x" + w_addr(PAIR_TW2)
        return "0x" + w_addr("0x" + "0" * 40)

    if sel == SEL["getPair(address,address)"] and to == F_V2:
        a, b = arg_addr(data, 0), arg_addr(data, 1)
        key = {a, b}
        if key == {TKN, WBNB}:
            return "0x" + w_addr(PAIR_TW)
        if key == {WBNB, USDT}:
            return "0x" + w_addr(PAIR_WU)
        return "0x" + w_addr("0x" + "0" * 40)

    if sel == SEL["getPool(address,address,uint24)"] and to == F_V3:
        a, b = arg_addr(data, 0), arg_addr(data, 1)
        fee = int(data[10 + 128:10 + 192], 16)
        if {a, b} == {TKN, USDT} and fee == 2500:
            return "0x" + w_addr(POOL_TU)
        return "0x" + w_addr("0x" + "0" * 40)

    if to in POOL_TOKENS:
        t0, t1 = POOL_TOKENS[to]
        if sel == SEL["token0()"]:
            return "0x" + w_addr(t0)
        if sel == SEL["token1()"]:
            return "0x" + w_addr(t1)
        if sel == SEL["getReserves()"] and to in RESERVES:
            r0, r1 = RESERVES[to]
            return "0x" + w_uint(r0) + w_uint(r1) + w_uint(1700000000)
        if sel == SEL["slot0()"] and to in SQRT:
            return "0x" + w_uint(SQRT[to]) + w_uint(0) * 6
    return None


class MockRpc(evm.Rpc):
    def __init__(self, *a, **kw):
        super().__init__(["http://mock"], *a[1:], **kw)

    def _post(self, payload):
        single = isinstance(payload, dict)
        items = [payload] if single else payload
        out = []
        for it in items:
            if it["method"] == "eth_call":
                p = it["params"][0]
                res = handle(p["to"], p["data"])
                out.append({"jsonrpc": "2.0", "id": it["id"],
                            **({"result": res} if res else {"error": {"message": "revert"}})})
            elif it["method"] == "eth_blockNumber":
                out.append({"jsonrpc": "2.0", "id": it["id"], "result": hex(40_000_000)})
            else:
                out.append({"jsonrpc": "2.0", "id": it["id"], "error": {"message": "unsupported"}})
        return out[0] if single else out


def run():
    poolscan.Rpc = MockRpc
    evm.Rpc = MockRpc
    import valuation, discovery
    valuation.Rpc = MockRpc
    discovery.Rpc = MockRpc

    sys.argv = ["poolscan.py", TKN, "--chain", "bsc", "--no-api", "--no-alpha",
                "--min-usd", "0", "--out", "out/mock"]
    rc = poolscan.main()
    assert rc == 0, "main() tra ve loi"

    import json
    from pathlib import Path
    files = sorted(Path("out/mock").glob("*.json"))
    data = json.loads(files[-1].read_text(encoding="utf-8"))

    px = data["token"]["price_usd"]
    total = data["total_liquidity_usd"]
    print("\n=== KIEM CHUNG ===")
    print(f"gia TKN   = {px}        (ky vong 0.06)")
    print(f"gia BNB   = {data['native_price_usd']}  (ky vong 600)")
    print(f"tong TVL  = {total}     (ky vong 204000)")
    assert abs(px - 0.06) < 1e-9, f"gia TKN sai: {px}"
    assert abs(data["native_price_usd"] - 600) < 1e-6
    assert abs(total - 204_000) < 1.0, f"tong TVL sai: {total}"
    pools = {p["address"]: p for p in data["pools"]}
    assert abs(pools[PAIR_TW]["tvl_usd"] - 120_000) < 1.0
    assert abs(pools[POOL_TU]["tvl_usd"] - 60_000) < 1.0
    assert pools[POOL_TU]["kind"] == "v3" and pools[POOL_TU]["fee"] == 2500
    assert pools[PAIR_TW]["kind"] == "v2"

    # gop theo cap: TKN/WBNB phai gom ca Pancake lan Biswap
    pr = {x["pair"]: x for x in data["pairs"]}
    print(f"cap TKN/WBNB = {pr['TKN/WBNB']['tvl_usd']} tren "
          f"{pr['TKN/WBNB']['pool_count']} pool  (ky vong 144000 / 2)")
    print(f"cap TKN/USDT = {pr['TKN/USDT']['tvl_usd']} tren "
          f"{pr['TKN/USDT']['pool_count']} pool  (ky vong 60000 / 1)")
    assert abs(pr["TKN/WBNB"]["tvl_usd"] - 144_000) < 1.0
    assert pr["TKN/WBNB"]["pool_count"] == 2
    assert set(pr["TKN/WBNB"]["dexes"]) == {"PancakeSwap V2", "Biswap"}
    assert pr["TKN/WBNB"]["dexes"][0] == "PancakeSwap V2", "phai xep DEX lon truoc"
    assert abs(pr["TKN/USDT"]["tvl_usd"] - 60_000) < 1.0
    assert abs(pr["TKN/WBNB"]["token_amount"] - 1_200_000) < 1.0
    assert [x["tvl_usd"] for x in data["pairs"]] == sorted(
        [x["tvl_usd"] for x in data["pairs"]], reverse=True), "cap phai xep giam dan"

    # lượt 2: bật bộ lọc 100k (chỉ pool 120k lọt) — tổng phải GIỮ NGUYÊN, chỉ phần hiển thị bị lọc
    sys.argv = ["poolscan.py", TKN, "--chain", "bsc", "--no-api", "--no-alpha",
                "--min-usd", "100000", "--out", "out/mock2"]
    assert poolscan.main() == 0
    d2 = json.loads(sorted(Path("out/mock2").glob("*.json"))[-1].read_text(encoding="utf-8"))
    print(f"\nLoc 100k: tong van = {d2['total_liquidity_usd']} (ky vong 204000), "
          f"hien {d2['pool_count_above_filter']}/{d2['pool_count']} pool")
    assert abs(d2["total_liquidity_usd"] - 204_000) < 1.0, "bo loc lam sai tong!"
    assert d2["pool_count"] == 3 and d2["pool_count_above_filter"] == 1
    assert abs(d2["total_liquidity_usd_above_filter"] - 120_000) < 1.0
    assert len(d2["pools"]) == 3, "CSV/JSON phai luu het pool, khong bi bo loc cat"
    assert len(d2["pairs"]) == 2, "JSON phai luu het cap"

    # lượt 3: giả lập GeckoTerminal trả về 1 pool PancakeSwap Infinity (poolId 66 ký tự)
    # — đây đúng là loại pool từng bị script vứt đi và làm thiếu $2.97M của DEBIT.
    from discovery import Candidate
    POOL_ID = "0x" + "ab" * 32

    def fake_gt(chain, token, verbose=False):
        c = Candidate(POOL_ID, "pancakeswap-infinity-clmm", "unknown", None, {"geckoterminal"})
        c.api_liquidity_usd = 2_000_000.0
        c.api_pair_label = "TKN / USDT"
        return {POOL_ID: c}

    poolscan.discover_geckoterminal = fake_gt
    poolscan.discover_dexscreener = lambda chain, token, verbose=False: {}
    poolscan.fetch_alpha_entry = lambda token, verbose=False: None
    sys.argv = ["poolscan.py", TKN, "--chain", "bsc", "--no-alpha",
                "--min-usd", "0", "--out", "out/mock3"]
    assert poolscan.main() == 0
    d3 = json.loads(sorted(Path("out/mock3").glob("*.json"))[-1].read_text(encoding="utf-8"))
    sing = [x for x in d3["pools"] if x["address"] == POOL_ID or x.get("pool_id") == POOL_ID]
    print(f"\nPool singleton: tvl={sing[0]['tvl_usd']} kind={sing[0]['kind']!r}")
    assert len(sing) == 1, "pool singleton bi mat!"
    assert sing[0]["kind"] == "singleton"
    assert abs(sing[0]["tvl_usd"] - 2_000_000) < 1.0, "pool singleton khong duoc tinh TVL!"
    assert abs(d3["total_liquidity_usd"] - 2_204_000) < 1.0, \
        f"tong phai gom ca singleton: {d3['total_liquidity_usd']}"

    pr3 = {x["pair"]: x for x in d3["pairs"]}
    print(f"cap TKN/USDT = {pr3['TKN/USDT']['tvl_usd']} tren "
          f"{pr3['TKN/USDT']['pool_count']} pool  (ky vong 2060000 / 2)")
    assert abs(pr3["TKN/USDT"]["tvl_usd"] - 2_060_000) < 1.0, \
        "pool singleton phai gop chung cap voi pool V3 doc tu on-chain"
    assert pr3["TKN/USDT"]["pool_count"] == 2
    assert pr3["TKN/USDT"]["tvl_usd"] > pr3["TKN/WBNB"]["tvl_usd"], "phai xep lai thu tu"

    # lượt 4: subgraph trả về SỐ LƯỢNG TOKEN của pool Infinity -> script phải TỰ định giá
    SG_ID = "0x" + "cd" * 32

    def fake_sg(chain, token, api_key, verbose=False):
        c = Candidate(SG_ID, "PancakeSwap Infinity CL", "singleton", 2500, {"subgraph"})
        c.pool_id = SG_ID
        c.sg_token0, c.sg_token1 = TKN, USDT
        c.sg_amt0, c.sg_amt1 = 300_000.0, 40_000.0
        c.sg_usd = 999_999.0          # số USD của subgraph — script phải BỎ QUA
        c.api_pair_label = "TKN/USDT"
        return {SG_ID: c}

    poolscan.discover_subgraph = fake_sg
    poolscan.discover_geckoterminal = lambda chain, token, verbose=False: {}
    poolscan.load_config = lambda: {"etherscan_api_key": "", "thegraph_api_key": "k", "rpc": {}}
    sys.argv = ["poolscan.py", TKN, "--chain", "bsc", "--no-alpha",
                "--min-usd", "0", "--out", "out/mock4"]
    assert poolscan.main() == 0
    d4 = json.loads(sorted(Path("out/mock4").glob("*.json"))[-1].read_text(encoding="utf-8"))
    sg = [x for x in d4["pools"] if x["address"] == SG_ID][0]
    # 300k TKN x $0.06 = $18,000  +  40k USDT x $1 = $40,000  ->  $58,000
    print(f"\nPool Infinity tu dinh gia: {sg['tvl_usd']} (ky vong 58000, KHONG phai 999999)")
    print(f"  ghi chu: {sg['note']}")
    assert abs(sg["tvl_usd"] - 58_000) < 1.0, \
        f"phai tu tinh tu so luong subgraph, khong lay USD cua subgraph: {sg['tvl_usd']}"
    assert abs(sg["value0_usd"] - 18_000) < 1.0 and abs(sg["value1_usd"] - 40_000) < 1.0
    assert "subgraph" in sg["note"]
    assert abs(sg["amount0"] - 300_000) < 1e-6

    pr4 = {x["pair"]: x for x in d4["pairs"]}
    assert abs(pr4["TKN/USDT"]["tvl_usd"] - 118_000) < 1.0, "phai gop voi pool V3 60k"
    assert abs(pr4["TKN/USDT"]["token_amount"] - 800_000) < 1.0, \
        "so luong token phai cong ca pool Infinity (500k V3 + 300k Infinity)"

    print("\nEnd-to-end PASS: so lieu khop tuyet doi voi ky vong.")


if __name__ == "__main__":
    run()
