#!/usr/bin/env python3
"""
poolscan — quét TOÀN BỘ pool thanh khoản của một token và quy đổi ra USD.

    python poolscan.py 0xTokenAddress --chain bsc --deep

Nguồn dữ liệu được gộp lại rồi khử trùng lặp; con số USD cuối cùng luôn do
script tự tính từ số dư token thật trong pool, không lấy của bên thứ ba.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import requests

from chains import get_chain
from discovery import (Etherscan, discover_brute, discover_dexscreener,
                       discover_geckoterminal, discover_logs,
                       discover_singleton, discover_subgraph, merge_all)
from evm import Rpc, dec_uint, enc, fetch_token_meta
from valuation import (PriceBook, collect_tokens, derive_token_price,
                       hydrate_pools, value_pools)

HERE = Path(__file__).resolve().parent
ALPHA_TOKEN_LIST = ("https://www.binance.com/bapi/defi/v1/public/wallet-direct"
                    "/buw/wallet/cex/alpha/all/token/list")


# ------------------------------------------------------------------ config
def load_config() -> dict:
    cfg = {"etherscan_api_key": "", "thegraph_api_key": "", "rpc": {}}
    for path in (Path.cwd() / "config.json", HERE / "config.json"):
        if path.exists():
            try:
                cfg.update(json.loads(path.read_text(encoding="utf-8")))
            except Exception as e:  # noqa: BLE001
                print(f"! config.json loi: {e}", file=sys.stderr)
            break
    if os.getenv("ETHERSCAN_API_KEY"):
        cfg["etherscan_api_key"] = os.environ["ETHERSCAN_API_KEY"]
    if os.getenv("THEGRAPH_API_KEY"):
        cfg["thegraph_api_key"] = os.environ["THEGRAPH_API_KEY"]
    if os.getenv("BSC_RPC"):
        cfg.setdefault("rpc", {})["bsc"] = [u.strip() for u in os.environ["BSC_RPC"].split(",")]
    return cfg


# ------------------------------------------------------------------ format
def fmt_usd(v) -> str:
    if v is None:
        return "-"
    if v >= 1_000_000:
        return f"${v/1_000_000:,.2f}M"
    if v >= 1_000:
        return f"${v/1_000:,.1f}K"
    return f"${v:,.2f}"


def fmt_amt(v) -> str:
    if v is None:
        return "-"
    if v >= 1_000_000:
        return f"{v/1_000_000:,.2f}M"
    if v >= 1_000:
        return f"{v/1_000:,.1f}K"
    if v >= 1:
        return f"{v:,.2f}"
    return f"{v:.6g}"


def table(rows: list[list[str]], headers: list[str], aligns: str = "") -> str:
    cols = len(headers)
    aligns = (aligns + "l" * cols)[:cols]
    widths = [len(h) for h in headers]
    for r in rows:
        for i in range(cols):
            widths[i] = max(widths[i], len(str(r[i])))

    def fmt_row(cells):
        out = []
        for i, c in enumerate(cells):
            c = str(c)
            out.append(c.rjust(widths[i]) if aligns[i] == "r" else c.ljust(widths[i]))
        return " │ ".join(out)

    sep = "─┼─".join("─" * w for w in widths)
    body = [fmt_row(headers), sep] + [fmt_row(r) for r in rows]
    return "\n".join(body)


# ------------------------------------------------------- Binance Alpha ref
def fetch_alpha_entry(token: str, verbose: bool = False) -> dict | None:
    try:
        r = requests.get(ALPHA_TOKEN_LIST, timeout=30,
                         headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        r.raise_for_status()
        data = r.json().get("data") or []
    except Exception as e:  # noqa: BLE001
        if verbose:
            print(f"   ! khong lay duoc Binance Alpha list: {e}")
        return None
    t = token.lower()
    for item in data:
        if not isinstance(item, dict):
            continue
        for v in item.values():
            if isinstance(v, str) and v.lower() == t:
                return item
    return None


def alpha_summary(entry: dict) -> list[tuple[str, str]]:
    keys = ("liquidity", "price", "marketcap", "mcap", "volume24h", "volume",
            "holders", "symbol", "name", "chainname", "alphaid")
    out = []
    for k, v in entry.items():
        kl = k.lower()
        if any(kl == x or kl.startswith(x) for x in keys):
            out.append((k, str(v)))
    return out


# --------------------------------------------------------- kiem tra subgraph
def graph_probe(chain: dict, token: str, api_key: str) -> int:
    """Thu tung subgraph mot: ket noi duoc khong, schema ra sao, tra ve may pool."""
    from subgraph import Subgraph, SubgraphError

    subs = chain.get("subgraphs") or []
    print(f"\nKiem tra {len(subs)} subgraph cua chain {chain['name']}")
    print(f"Token thu: {token}")
    print("API key  : " + (f"CO ({api_key[:6]}…)" if api_key
                           else "KHONG — dien thegraph_api_key vao config.json"))
    print()
    if not api_key or not subs:
        return 1

    okc = 0
    for dex, sid, kind in subs:
        print(f"── {dex}  ({kind})")
        print(f"   id: {sid}")
        sg = Subgraph(api_key, sid, verbose=False)
        try:
            f = sg.discover_schema()
        except SubgraphError as e:
            print(f"   ✗ schema: {e}")
            if sg.diag:
                print(f"     tong so type: {sg.diag.get('type_count')}")
                print(f"     type giong pool: {sg.diag.get('pool_like')}")
            print()
            continue
        except Exception as e:  # noqa: BLE001
            print(f"   ✗ ket noi: {str(e)[:250]}")
            print()
            continue

        print(f"   schema OK: entity={f['entity']}  root={f['root']}")
        print(f"     hai ve   -> {f['tok0']} / {f['tok1']}"
              f"  ({'object' if f['tok_is_object'] else 'chuoi dia chi'})")
        for role in ("tvl_usd", "amt0", "amt1", "fee"):
            print(f"     {role:<8} -> {f.get(role) or '(KHONG CO)'}")
        if not (f.get("amt0") and f.get("amt1")):
            print("     ! thieu field so luong token -> se phai dung so USD uoc luong.")
            print(f"     Danh sach field cua {f['entity']} (gui lai de sua):")
            flds = f.get("all_fields") or []
            for i in range(0, len(flds), 6):
                print("       " + ", ".join(flds[i:i + 6]))

        try:
            rows = sg.pools_of_token(token)
        except Exception as e:  # noqa: BLE001
            print(f"   ✗ query pool: {str(e)[:250]}")
            print()
            continue
        print(f"   tra ve {len(rows)} pool")
        for r in sorted(rows, key=lambda x: x.get("tvl_usd") or 0, reverse=True)[:3]:
            print(f"     · {r['symbol0']}/{r['symbol1']}  tvl_usd={r['tvl_usd']}  "
                  f"amt0={r['amount0']}  amt1={r['amount1']}")
            print(f"       {r['id']}")
        if not rows:
            print("     (subgraph khong co pool nao cua token nay — co the no da ngung sync)")
        okc += 1
        print()
    print(f"=> {okc}/{len(subs)} subgraph dung duoc.")
    return 0 if okc else 1


# -------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Quet toan bo pool thanh khoan cua 1 token")
    ap.add_argument("token", help="dia chi contract token")
    ap.add_argument("--chain", default="bsc", help="bsc | ethereum | base (mac dinh bsc)")
    ap.add_argument("--deep", action="store_true",
                    help="quet event tao pool tren TOAN chain (bat ca DEX chua co trong list)")
    ap.add_argument("--no-api", action="store_true", help="bo qua DexScreener/GeckoTerminal")
    ap.add_argument("--no-alpha", action="store_true", help="bo qua doi chieu Binance Alpha")
    ap.add_argument("--no-graph", action="store_true", help="bo qua lop subgraph (The Graph)")
    ap.add_argument("--graph-probe", action="store_true",
                    help="chi kiem tra ket noi + schema cua tung subgraph roi thoat")
    ap.add_argument("--min-usd", type=float, default=50_000.0,
                    help="chi hien pool co TVL tu nguong nay tro len (mac dinh 50000)")
    ap.add_argument("--quote", action="append", default=[],
                    help="them token doi ung de do brute-force (lap lai duoc)")
    ap.add_argument("--top", type=int, default=0,
                    help="gioi han so dong o khoi ket qua cuoi (mac dinh 0 = hien HET "
                         "moi cap/pool dat nguong --min-usd)")
    ap.add_argument("--out", default="out", help="thu muc xuat CSV/JSON")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    token = args.token.strip()
    if not (token.startswith("0x") and len(token) == 42):
        print("Dia chi token khong hop le (can dang 0x + 40 ky tu hex).")
        return 2
    token = token.lower()

    cfg = load_config()
    chain = get_chain(args.chain)
    # config.json co the ghi de danh sach subgraph, khong can sua code:
    #   "subgraphs": { "bsc": [["Ten hien thi", "<subgraph id>", "singleton"]] }
    ov = (cfg.get("subgraphs") or {}).get(chain["name"])
    if ov:
        chain = {**chain, "subgraphs": [tuple(x) for x in ov]}

    if args.graph_probe:
        return graph_probe(chain, token, cfg.get("thegraph_api_key") or "")
    rpc_urls = (cfg.get("rpc", {}).get(chain["name"]) or []) + chain["public_rpcs"]
    rpc = Rpc(rpc_urls, verbose=args.verbose)
    es_key = cfg.get("etherscan_api_key") or ""
    es = None
    if es_key:
        try:
            head = rpc.block_number()
        except Exception:  # noqa: BLE001
            head = "latest"
        es = Etherscan(es_key, chain["chain_id"], args.verbose, to_block=head)

    t0 = time.time()
    print(f"\n╭─ poolscan · chain={chain['name']} · token={token}")
    print(f"╰─ RPC: {rpc_urls[0]}   Etherscan key: {'CO' if es else 'KHONG (bo qua lop log)'}")

    # 1. metadata token chính
    meta = fetch_token_meta(rpc, [token] + chain["quotes"] + [chain["wnative"]])
    tmeta = meta.get(token)
    if not tmeta:
        print("! Khong doc duoc token. Kiem tra lai dia chi/chain.")
        return 1
    supply_raw = rpc.call(token, enc("totalSupply()"))
    supply = tmeta.amount(dec_uint(supply_raw or "0x0") or 0)
    print(f"\nToken: {tmeta.symbol}  (decimals={tmeta.decimals}, supply={fmt_amt(supply)})\n")

    # 2. tìm pool
    stores = []
    print("[1/5] Do thang factory (brute-force getPair/getPool)…")
    brute = discover_brute(rpc, chain, token, args.quote)
    print(f"      -> {len(brute)} pool")
    stores.append(brute)

    if es:
        print("[2/5] Quet event tao pool tren explorer…" + (" (che do --deep)" if args.deep else ""))
        logs = discover_logs(es, chain, token, args.deep, args.verbose)
        print(f"      -> {len(logs)} pool")
        stores.append(logs)
        sing = discover_singleton(es, rpc, chain, token, args.verbose)
        if sing:
            print(f"      -> {len(sing)} pool singleton (PancakeSwap Infinity / Uniswap V4)")
        stores.append(sing)
    else:
        print("[2/5] Bo qua (chua co etherscan_api_key trong config.json)")

    graph_key = cfg.get("thegraph_api_key") or ""
    if graph_key and not args.no_graph and chain.get("subgraphs"):
        print("[3/5] Hoi subgraph (The Graph) — nguon tach duoc pool Infinity/V4…")
        stores.append(discover_subgraph(chain, token, graph_key, args.verbose))
    elif not args.no_graph and chain.get("subgraphs"):
        print("[3/5] Bo qua subgraph (chua co thegraph_api_key trong config.json)")

    if not args.no_api:
        print("[4/5] Doi chieu DexScreener + GeckoTerminal…")
        ds = discover_dexscreener(chain, token, args.verbose)
        gt = discover_geckoterminal(chain, token, args.verbose)
        print(f"      -> DexScreener {len(ds)} | GeckoTerminal {len(gt)}")
        stores += [ds, gt]
    else:
        print("[4/5] Bo qua nguon API")

    cands = merge_all(*stores)
    print(f"\nTong cong {len(cands)} pool ung vien sau khi khu trung lap.")

    # 3. đọc on-chain + định giá
    print("[5/5] Doc so du on-chain va quy doi USD…")
    pools = hydrate_pools(rpc, cands, args.verbose)
    all_tokens = collect_tokens(pools)
    meta.update(fetch_token_meta(rpc, [a for a in all_tokens if a not in meta]))

    book = PriceBook(rpc, chain, meta)
    native_px = book.price(chain["wnative"])
    print(f"      Gia {chain['native_symbol']}: {fmt_usd(native_px)}")

    tpx = derive_token_price(pools, token, book, meta)
    if tpx:
        book.set(token, tpx)
        print(f"      Gia {tmeta.symbol}: ${tpx:,.10g}")
    else:
        print(f"      ! Khong suy duoc gia {tmeta.symbol} (pool qua nong hoac token la)")

    value_pools(pools, book, meta)

    # 4. sắp xếp + in — pool singleton cũng được tính, không bị loại như trước
    onchain = list(pools)
    singles = [p for p in pools if p.kind == "singleton"]
    onchain.sort(key=lambda p: (p.tvl_usd or -1), reverse=True)

    shown = [p for p in onchain if (p.tvl_usd or 0) >= args.min_usd]
    hidden = len(onchain) - len(shown)

    # để cặp đọc từ nhãn API ("DEBIT / USDT") gộp chung nhóm với cặp đọc được
    # on-chain, quy symbol về lại địa chỉ token khi biết
    sym2addr = {m.symbol.upper(): a for a, m in meta.items() if m.symbol}
    # V4 dung dia chi 0x0 cho coin goc -> nhan hien ra la "BNB"/"ETH".
    # Quy ve wrapped token de B2/BNB va B2/WBNB khong tach thanh hai cap.
    sym2addr.setdefault(chain["native_symbol"].upper(), chain["wnative"].lower())

    def pair_of(p) -> tuple[str, str, float | None, float | None]:
        """-> (nhan cap, khoa gom nhom, luong token, luong ve kia)"""
        if p.token0 and p.token1 and token in (p.token0, p.token1):
            other = p.token1 if p.token0 == token else p.token0
            m_other = meta.get(other)
            return (f"{tmeta.symbol}/{m_other.symbol if m_other else '?'}", other,
                    p.amt0 if p.token0 == token else p.amt1,
                    p.amt1 if p.token0 == token else p.amt0)
        # pool singleton: không đọc được on-chain, lấy tên cặp từ nguồn API
        if p.api_pair_label:
            parts = [x.strip() for x in p.api_pair_label.replace(" / ", "/").split("/")]
            parts = [x.split()[0] for x in parts if x]
            if len(parts) >= 2:
                oth = parts[1] if parts[0].upper() == tmeta.symbol.upper() else parts[0]
                key = sym2addr.get(oth.upper())
                if key:
                    m = meta.get(key)
                    if m and m.symbol:
                        oth = m.symbol          # BNB -> WBNB, gop dung cap
                else:
                    key = f"sym:{oth.upper()}"
                return f"{tmeta.symbol}/{oth}", key, None, None
        if p.token0 and p.token1:
            m0, m1 = meta.get(p.token0), meta.get(p.token1)
            return (f"{m0.symbol if m0 else '?'}/{m1.symbol if m1 else '?'}",
                    "khac", None, None)
        return "?/?", "khac", None, None

    rows = []
    for i, p in enumerate(shown, 1):
        pair, _, tok_amt, oth_amt = pair_of(p)
        kind = p.kind + (f" {p.fee/10000:g}%" if p.kind == "v3" and p.fee else "")
        ident = p.pool_id or p.address
        rows.append([
            i, p.dex[:26], kind, pair,
            fmt_usd(p.tvl_usd),
            fmt_amt(tok_amt), fmt_amt(oth_amt),
            ident if len(ident) <= 42 else ident[:20] + "…" + ident[-6:],
            ",".join(sorted(p.sources)),
        ])

    print()
    print("── CHI TIET TUNG POOL " + "─" * 40)
    if rows:
        print(table(rows,
                    ["#", "DEX", "Loai", "Cap", "TVL (USD)", tmeta.symbol, "Ve kia",
                     "Pool", "Nguon"],
                    aligns="rlllrrrll"))
    else:
        print(f"(khong co pool nao dat {fmt_usd(args.min_usd)} — ha nguong bang --min-usd)")
    # Tổng luôn tính trên TOÀN BỘ pool, không phụ thuộc bộ lọc hiển thị —
    # có vậy mới so sánh đúng với con số của Binance Alpha.
    total_all = sum(p.tvl_usd or 0 for p in onchain)
    total_shown = sum(p.tvl_usd or 0 for p in shown)
    if hidden:
        print(f"(an {hidden} pool duoi {fmt_usd(args.min_usd)}, cong lai "
              f"{fmt_usd(total_all - total_shown)} — dung --min-usd 0 de xem het)")

    # ---- tổng hợp theo CẶP: gộp mọi pool của cùng một cặp lại
    groups: dict[str, list] = {}
    labels: dict[str, str] = {}
    for p in onchain:
        label, key, _, _ = pair_of(p)
        groups.setdefault(key, []).append(p)
        labels.setdefault(key, label)

    pairs = []
    for key, ps in groups.items():
        tvl = sum(p.tvl_usd or 0 for p in ps)
        tok_amt = sum((pair_of(p)[2] or 0) for p in ps)
        by_dex: dict[str, float] = {}
        for p in ps:
            by_dex[p.dex] = by_dex.get(p.dex, 0) + (p.tvl_usd or 0)
        dexes = [d for d, _ in sorted(by_dex.items(), key=lambda kv: kv[1], reverse=True)]
        pairs.append({
            "pair": labels[key],
            "quote_token": key if key.startswith("0x") else None,
            "tvl_usd": tvl, "pool_count": len(ps),
            "token_amount": tok_amt, "dexes": dexes,
        })
    pairs.sort(key=lambda x: x["tvl_usd"], reverse=True)
    pairs_shown = [x for x in pairs if x["tvl_usd"] >= args.min_usd]

    if pairs_shown:
        prow = []
        for i, x in enumerate(pairs_shown, 1):
            dex_txt = ", ".join(x["dexes"])
            if len(dex_txt) > 44:
                dex_txt = dex_txt[:41] + "…"
            pct = (x["tvl_usd"] / total_all * 100) if total_all else 0
            prow.append([i, x["pair"], fmt_usd(x["tvl_usd"]), f"{pct:5.1f}%",
                         x["pool_count"], fmt_amt(x["token_amount"]), dex_txt])
        print()
        print("── TONG HOP THEO CAP " + "─" * 41)
        print(table(prow,
                    ["#", "Cap", "Tong TVL", "%", "So pool", tmeta.symbol, "Nam tren DEX"],
                    aligns="rlrrrrl"))
        hidden_pairs = len(pairs) - len(pairs_shown)
        if hidden_pairs:
            print(f"(an {hidden_pairs} cap duoi {fmt_usd(args.min_usd)})")

    exact = [p for p in onchain if p.kind != "singleton" and p.tvl_usd is not None]
    est = [p for p in onchain if p.kind == "singleton" and p.tvl_usd is not None]
    total_exact = sum(p.tvl_usd for p in exact)
    total_est = sum(p.tvl_usd for p in est)

    print(f"\n►  TONG THANH KHOAN: {fmt_usd(total_all)}  tren {len(onchain)} pool")
    print(f"   ├ tu tinh tu so du on-chain : {fmt_usd(total_exact)} ({len(exact)} pool)")
    if est:
        sg_pools = [p for p in est if "subgraph" in p.sources]
        sg_usd = sum(p.tvl_usd for p in sg_pools)
        print(f"   └ pool singleton (Infinity/V4): {fmt_usd(total_est)} ({len(est)} pool)")
        if sg_pools:
            print(f"       · {fmt_usd(sg_usd)} tu subgraph — so luong token that, gia tu tinh")
        if len(est) > len(sg_pools):
            print(f"       · {fmt_usd(total_est - sg_usd)} uoc luong theo GeckoTerminal "
                  f"({len(est) - len(sg_pools)} pool subgraph khong co)")
    if hidden:
        print(f"   Trong do tu {fmt_usd(args.min_usd)} tro len: "
              f"{fmt_usd(total_shown)} tren {len(shown)} pool")

    # đối chiếu nguồn API (chỉ có ý nghĩa khi thực sự đã gọi DexScreener)
    if not args.no_api:
        ds_total = sum(p.api_liquidity_usd or 0 for p in onchain if "dexscreener" in p.sources)
        n_ds = len([p for p in onchain if "dexscreener" in p.sources])
        print(f"   DexScreener bao cao : {fmt_usd(ds_total)} ({n_ds} pool)")
        missed = [p for p in onchain if "dexscreener" not in p.sources and (p.tvl_usd or 0) >= 1000]
        if missed:
            miss_usd = sum(p.tvl_usd or 0 for p in missed)
            print(f"   ⚠ {len(missed)} pool (tong {fmt_usd(miss_usd)}) KHONG co tren DexScreener:")
            for p in missed[:10]:
                print(f"     · {p.dex:<22} {fmt_usd(p.tvl_usd):>12}  {p.address}")

    # Pancake Infinity / Uniswap V4
    if singles:
        top = sorted(singles, key=lambda p: (p.tvl_usd or 0), reverse=True)
        n_sg = len([p for p in singles if "subgraph" in p.sources])
        print(f"\n   Pool singleton (Infinity/V4): {len(singles)} pool, {fmt_usd(total_est)}")
        print(f"   {n_sg} pool co so luong token tu subgraph (gia tu tinh), "
              f"{len(singles)-n_sg} pool chi co so uoc luong cua GeckoTerminal.")
        for p in top[:5]:
            pid = p.pool_id or p.address
            tag = "subgraph" if "subgraph" in p.sources else "geckoterminal"
            print(f"     · {p.dex:<26} {fmt_usd(p.tvl_usd):>12}  [{tag}]  {pid[:22]}…")
    if chain.get("vault"):
        raw = rpc.call(token, enc("balanceOf(address)", chain["vault"]))
        vbal = tmeta.amount(dec_uint(raw or "0x0") or 0)
        if vbal > 0:
            vusd = vbal * tpx if tpx else None
            print(f"\n   KIEM CHUNG ON-CHAIN cho phan Infinity:")
            print(f"     Vault {chain['vault'][:10]}… dang giu {fmt_amt(vbal)} {tmeta.symbol}"
                  + (f" = {fmt_usd(vusd)}" if vusd else ""))
            inf = [p for p in singles if "infinity" in p.dex.lower()]
            inf_usd = sum(p.tvl_usd or 0 for p in inf)
            if vusd and inf_usd:
                other = inf_usd - vusd
                print(f"     So bao cao cho pool Infinity: {fmt_usd(inf_usd)}"
                      f"  ->  ve kia ≈ {fmt_usd(other)}")
                if other < -1:
                    print(f"     ⚠ SAI: so bao cao NHO HON gia tri {tmeta.symbol} that su nam "
                          f"trong Vault. Nguon ngoai dang loi thoi hoac thieu pool.")
                else:
                    print(f"     ✓ Hop ly (ve {tmeta.symbol} khop voi so du that trong Vault)")
            elif vusd:
                print(f"     (chua co nguon nao bao TVL pool Infinity de doi chieu)")

    # Binance Alpha
    alpha = None
    if not args.no_alpha:
        print("\n[+] Doi chieu voi Binance Alpha…")
        alpha = fetch_alpha_entry(token, args.verbose)
        if alpha:
            for k, v in alpha_summary(alpha):
                print(f"     {k:<18} {v}")
        else:
            print("     (khong thay token nay trong danh sach Alpha, hoac API bi chan IP)")

    # 5. xuất file
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = outdir / f"{tmeta.symbol}_{token[:10]}_{stamp}"

    with open(f"{base}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["dex", "kind", "fee", "pair", "pool_address", "token0", "token1",
                    "amount0", "amount1", "value0_usd", "value1_usd", "tvl_usd",
                    "dexscreener_usd", "sources", "note"])
        for p in onchain:
            m0, m1 = meta.get(p.token0 or ""), meta.get(p.token1 or "")
            w.writerow([p.dex, p.kind, p.fee,
                        f"{m0.symbol if m0 else '?'}/{m1.symbol if m1 else '?'}",
                        p.address, p.token0, p.token1,
                        f"{p.amt0:.10f}", f"{p.amt1:.10f}",
                        "" if p.val0 is None else f"{p.val0:.2f}",
                        "" if p.val1 is None else f"{p.val1:.2f}",
                        "" if p.tvl_usd is None else f"{p.tvl_usd:.2f}",
                        "" if p.api_liquidity_usd is None else f"{p.api_liquidity_usd:.2f}",
                        ",".join(sorted(p.sources)), p.note])

    payload = {
        "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S%z"),
        "chain": chain["name"],
        "token": {"address": token, "symbol": tmeta.symbol,
                  "decimals": tmeta.decimals, "price_usd": tpx, "total_supply": supply},
        "native_price_usd": native_px,
        "total_liquidity_usd": total_all,
        "pool_count": len(onchain),
        "min_usd_filter": args.min_usd,
        "total_liquidity_usd_above_filter": total_shown,
        "pool_count_above_filter": len(shown),
        "pairs": pairs,
        "binance_alpha": alpha,
        "infinity_pool_ids": sorted({p.pool_id for p in singles if p.pool_id}),
        "pools": [
            {"dex": p.dex, "kind": p.kind, "fee": p.fee, "address": p.address,
             "token0": p.token0, "token1": p.token1,
             "amount0": p.amt0, "amount1": p.amt1,
             "value0_usd": p.val0, "value1_usd": p.val1, "tvl_usd": p.tvl_usd,
             "dexscreener_usd": p.api_liquidity_usd,
             "sources": sorted(p.sources), "note": p.note}
            for p in onchain
        ],
    }
    Path(f"{base}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    with open(f"{base}_pairs.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["pair", "tvl_usd", "pct_of_total", "pool_count",
                    f"amount_{tmeta.symbol}", "quote_token", "dexes"])
        for x in pairs:
            w.writerow([x["pair"], f"{x['tvl_usd']:.2f}",
                        f"{(x['tvl_usd']/total_all*100) if total_all else 0:.2f}",
                        x["pool_count"], f"{x['token_amount']:.10f}",
                        x["quote_token"] or "", ", ".join(x["dexes"])])

    # ---------------------------------------------------------------- KẾT QUẢ
    # Khối này in cuối cùng, sát dấu nhắc lệnh, ID đầy đủ để bôi đen copy thẳng.
    def pool_link(p) -> str:
        pid = p.pool_id or p.address
        if p.kind == "singleton":
            return f"https://www.geckoterminal.com/{chain['geckoterminal_id']}/pools/{pid}"
        return f"{chain['explorer']}/address/{pid}"

    alq = None
    if alpha:
        for k, v in alpha.items():
            if k.lower() == "liquidity":
                try:
                    alq = float(v)
                except (TypeError, ValueError):
                    alq = None

    bar = "═" * 74
    print(f"\n{bar}")
    print(f"  {tmeta.symbol}   gia ${tpx:,.8g}" if tpx else f"  {tmeta.symbol}")
    # So tu tinh va so di muon KHONG cong chung khi doi chieu — Alpha chi tinh
    # pool doc duoc on-chain, nen phai so voi dung phan do.
    print(f"  Tu tinh tu on-chain    : {fmt_usd(total_exact):>12}   ({len(exact)} pool)")
    if alq:
        diff = (total_exact - alq) / alq * 100
        print(f"  Binance Alpha bao      : {fmt_usd(alq):>12}   (lech {diff:+.2f}%)")
    if est:
        print(f"  + uoc luong V4/Infinity: {fmt_usd(total_est):>12}   ({len(est)} pool — "
              f"so cua GeckoTerminal, Alpha thuong khong tinh)")
    print(f"  = TONG CONG            : {fmt_usd(total_all):>12}   ({len(onchain)} pool)")
    print(bar)

    cap = args.top if args.top and args.top > 0 else None
    pair_list = pairs_shown[:cap] if cap else pairs_shown
    print(f"\n  CAC CAP TU {fmt_usd(args.min_usd)} TRO LEN — {len(pair_list)} cap"
          + (f" (gioi han --top {cap}, con {len(pairs_shown)})" if cap and
             len(pairs_shown) > cap else "") + ":\n")
    for i, x in enumerate(pair_list, 1):
        pct = (x["tvl_usd"] / total_all * 100) if total_all else 0
        print(f"  {i}. {x['pair']:<16} ${x['tvl_usd']:>16,.2f}   {pct:5.1f}%   "
              f"{x['pool_count']} pool   {', '.join(x['dexes'][:3])}")
    if not pair_list:
        print(f"  (khong co cap nao dat {fmt_usd(args.min_usd)})")

    top_pools = shown[:cap] if cap else shown
    print(f"\n  CAC POOL TU {fmt_usd(args.min_usd)} TRO LEN — {len(top_pools)} pool"
          + (f" (gioi han --top {cap}, con {len(shown)})" if cap and
             len(shown) > cap else "") + ":\n")
    for i, p in enumerate(top_pools, 1):
        pair, _, tok_amt, oth_amt = pair_of(p)
        kind = p.kind + (f" {p.fee/10000:g}%" if p.kind == "v3" and p.fee else "")
        print(f"  {i}. ${p.tvl_usd:>16,.2f}   {pair:<14} {p.dex} ({kind})")
        if tok_amt is not None and oth_amt is not None:
            print(f"     {fmt_amt(tok_amt)} {tmeta.symbol} + {fmt_amt(oth_amt)} "
                  f"{pair.split('/')[-1]}")
        print(f"     {p.pool_id or p.address}")
        print(f"     {pool_link(p)}")
        if p.note:
            print(f"     ! {p.note}")
        print()
    if not top_pools:
        print(f"  (khong co pool nao dat {fmt_usd(args.min_usd)})\n")

    print(f"\nDa luu: {base}.csv        (chi tiet tung pool)")
    print(f"        {base}_pairs.csv  (gop theo cap)")
    print(f"        {base}.json")
    print(f"Xong trong {time.time()-t0:.1f}s ({rpc.calls} eth_call).\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nDa huy.")
        sys.exit(130)
