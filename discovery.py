"""Các lớp tìm pool. Mỗi lớp trả về dict {pool_address_lower: Candidate}.

Triết lý: gộp nhiều nguồn rồi khử trùng lặp theo địa chỉ pool.
- brute   : hỏi thẳng factory.getPair/getPool  -> chắc chắn đúng, không cần API key
- logs    : quét event tạo pool trên explorer  -> bắt được pool ghép với token lạ
- deep    : quét event KHÔNG lọc factory       -> bắt được cả DEX chưa có trong list
- singleton: PancakeSwap Infinity / Uniswap V4 -> kiến trúc vault chung
- api     : DexScreener + GeckoTerminal        -> phủ phần đuôi dài
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import requests

import re

from evm import Rpc, dec_addr, dec_uint, enc, topic_addr, words, ZERO
from keccak import event_topic

TOPIC_PAIR_CREATED = event_topic("PairCreated(address,address,address,uint256)")
TOPIC_POOL_CREATED_V3 = event_topic("PoolCreated(address,address,uint24,int24,address)")
TOPIC_POOL_CREATED_SOLIDLY = event_topic("PoolCreated(address,address,bool,address,uint256)")

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"


# Mỗi nguồn gọi cùng một sàn một kiểu: "PancakeSwap V2" / "pancakeswap v2" /
# "pancakeswap_v2" / "pancakeswap-v2-bsc". Quy về một tên để khỏi đếm thành 3 sàn.
_DEX_CANON = {
    "pancakeswapv1": "PancakeSwap V1", "pancakeswapv2": "PancakeSwap V2",
    "pancakeswapv3": "PancakeSwap V3", "pancakeswapstableswap": "PancakeSwap StableSwap",
    "pancakeswapinfinity": "PancakeSwap Infinity", "pancakeswapv4": "PancakeSwap Infinity",
    "pancakeswapinfinitycl": "PancakeSwap Infinity CL",
    "pancakeswapinfinityclmm": "PancakeSwap Infinity CL",
    "pancakeswapinfinitybin": "PancakeSwap Infinity Bin",
    "pancakeswapinfinitylbamm": "PancakeSwap Infinity Bin",
    "uniswapv2": "Uniswap V2", "uniswapv3": "Uniswap V3", "uniswapv4": "Uniswap V4",
    "sushiswapv2": "SushiSwap V2", "sushiswapv3": "SushiSwap V3",
    "biswap": "Biswap", "apeswap": "ApeSwap", "bakeryswap": "BakerySwap",
    "mdex": "MDEX", "babyswap": "BabySwap", "nomiswap": "Nomiswap",
    "squadswapv2": "Squadswap V2", "squadswapv3": "Squadswap V3",
    "thena": "THENA", "fourmeme": "four.meme",
}


def norm_dex(name: str) -> str:
    if not name or name in ("?", "unknown"):
        return name
    k = re.sub(r"[^a-z0-9]", "", name.lower())
    for suf in ("bsc", "bnb", "bnbchain", "ethereum", "base"):
        if k.endswith(suf) and len(k) > len(suf):
            k = k[: -len(suf)]
    return _DEX_CANON.get(k, name)


@dataclass
class Candidate:
    address: str
    dex: str = "?"
    kind: str = "v2"          # v2 | v3 | solidly | singleton | unknown
    fee: int | None = None
    sources: set[str] = field(default_factory=set)
    # chỉ dùng cho nguồn API (để đối chiếu, KHÔNG dùng làm số cuối)
    api_liquidity_usd: float | None = None
    api_pair_label: str | None = None
    pool_id: str | None = None  # Infinity / V4
    # dữ liệu lấy từ subgraph (số lượng token thật của pool singleton)
    sg_token0: str | None = None
    sg_token1: str | None = None
    sg_amt0: float | None = None
    sg_amt1: float | None = None
    sg_usd: float | None = None


def _merge(store: dict[str, Candidate], cand: Candidate):
    cand.dex = norm_dex(cand.dex)
    key = (cand.pool_id or cand.address).lower()
    if key in store:
        old = store[key]
        old.sources |= cand.sources
        if old.dex in ("?", "unknown") and cand.dex not in ("?", "unknown"):
            old.dex = cand.dex
        if old.kind in ("unknown",) and cand.kind != "unknown":
            old.kind = cand.kind
        if old.fee is None:
            old.fee = cand.fee
        if old.api_liquidity_usd is None:
            old.api_liquidity_usd = cand.api_liquidity_usd
        if old.api_pair_label is None:
            old.api_pair_label = cand.api_pair_label
        for f_ in ("sg_token0", "sg_token1", "sg_amt0", "sg_amt1", "sg_usd"):
            if getattr(old, f_) is None:
                setattr(old, f_, getattr(cand, f_))
    else:
        store[key] = cand


# --------------------------------------------------------------- 1. BRUTE
def discover_brute(rpc: Rpc, chain: dict, token: str, extra_quotes: list[str]) -> dict[str, Candidate]:
    """Hỏi thẳng từng factory xem có pool giữa token và từng quote token không."""
    quotes = list(dict.fromkeys([q.lower() for q in chain["quotes"] + extra_quotes]))
    quotes = [q for q in quotes if q != token.lower()]

    calls, meta = [], []
    for dex, kind, factory in chain["factories"]:
        for q in quotes:
            if kind in ("v2",):
                calls.append((factory, enc("getPair(address,address)", token, q)))
                meta.append((dex, kind, None))
            elif kind == "v3":
                for fee in chain["fee_tiers"]:
                    calls.append((factory, enc("getPool(address,address,uint24)", token, q, fee)))
                    meta.append((dex, kind, fee))
            elif kind == "solidly":
                for stable in (0, 1):
                    calls.append((factory, enc("getPool(address,address,bool)", token, q, stable)))
                    meta.append((dex, kind, stable))

    res = rpc.call_many(calls)
    out: dict[str, Candidate] = {}
    for (dex, kind, fee), raw in zip(meta, res):
        if not raw:
            continue
        addr = dec_addr(raw)
        if not addr or addr == ZERO:
            continue
        _merge(out, Candidate(addr.lower(), dex, kind, fee, {"brute"}))
    return out


# ---------------------------------------------------------------- 2. LOGS
class Etherscan:
    def __init__(self, api_key: str, chain_id: int, verbose: bool = False,
                 to_block: int | str = "latest"):
        self.key = api_key
        self.chain_id = chain_id
        self.verbose = verbose
        self.to_block = to_block   # số block cụ thể an toàn hơn chuỗi "latest"
        self.session = requests.Session()
        self._last = 0.0
        self.errors: list[str] = []
        self.chain_unsupported = False

    def _get(self, params: dict) -> list[dict]:
        params = {**params, "chainid": self.chain_id, "apikey": self.key}
        gap = time.time() - self._last
        if gap < 0.25:
            time.sleep(0.25 - gap)
        self._last = time.time()
        r = self.session.get(ETHERSCAN_V2, params=params, timeout=40)
        r.raise_for_status()
        js = r.json()
        if js.get("status") == "1":
            return js.get("result") or []
        msg = str(js.get("result") or js.get("message") or "")
        if "No records found" in msg or "No logs found" in msg:
            return []
        if "not supported for this chain" in msg or "upgrade your apiplan" in msg.lower():
            self.chain_unsupported = True
            raise RuntimeError("CHAIN_UNSUPPORTED")
        raise RuntimeError(f"Etherscan: {msg[:200]}")

    def logs(self, topic0: str, token_topic: str, position: int, address: str | None = None) -> list[dict]:
        """Lấy toàn bộ log khớp topic0 và token nằm ở topic{position}."""
        out = []
        for page in range(1, 11):
            params = {
                "module": "logs", "action": "getLogs",
                "fromBlock": 0, "toBlock": self.to_block,
                "topic0": topic0,
                f"topic{position}": token_topic,
                f"topic0_{position}_opr": "and",
                "page": page, "offset": 1000,
            }
            if address:
                params["address"] = address
            batch = self._get(params)
            out.extend(batch)
            if len(batch) < 1000:
                break
        return out

    def logs_by_topic_only(self, address: str, token_topic: str, position: int) -> list[dict]:
        """Không lọc topic0 — dùng cho singleton (Infinity/V4) để khỏi đoán signature."""
        out = []
        for page in range(1, 6):
            params = {
                "module": "logs", "action": "getLogs",
                "fromBlock": 0, "toBlock": self.to_block,
                "address": address,
                f"topic{position}": token_topic,
                "page": page, "offset": 1000,
            }
            batch = self._get(params)
            out.extend(batch)
            if len(batch) < 1000:
                break
        return out


def _pool_from_log(kind: str, log: dict) -> tuple[str | None, int | None]:
    """Rút địa chỉ pool + fee ra khỏi log tạo pool."""
    data_words = words(log.get("data") or "0x")
    topics = log.get("topics") or []

    def as_addr(w: str) -> str | None:
        a = "0x" + w[24:]
        if a == ZERO:
            return None
        # loại các word thực ra là số nhỏ (tickSpacing, uint...)
        if int(w[:24] or "0", 16) != 0:
            return None
        if sum(c != "0" for c in w[24:]) < 8:
            return None
        return a

    fee = None
    if kind == "v3":
        if len(topics) > 3:
            try:
                fee = int(topics[3], 16)
            except ValueError:
                fee = None
        for w in data_words[::-1]:
            a = as_addr(w)
            if a:
                return a.lower(), fee
        return None, fee

    for w in data_words:
        a = as_addr(w)
        if a:
            return a.lower(), fee
    return None, fee


def discover_logs(es: Etherscan, chain: dict, token: str, deep: bool = False,
                  verbose: bool = False) -> dict[str, Candidate]:
    tt = topic_addr(token)
    out: dict[str, Candidate] = {}

    factory_by_addr = {f.lower(): (dex, kind) for dex, kind, f in chain["factories"]}

    jobs = []
    for dex, kind, factory in chain["factories"]:
        topic0 = {"v2": TOPIC_PAIR_CREATED, "v3": TOPIC_POOL_CREATED_V3,
                  "solidly": TOPIC_POOL_CREATED_SOLIDLY}[kind]
        for pos in (1, 2):
            jobs.append((dex, kind, factory, topic0, pos))

    if deep:
        # không lọc factory -> bắt được cả DEX chưa biết
        for topic0, kind in ((TOPIC_PAIR_CREATED, "v2"),
                             (TOPIC_POOL_CREATED_V3, "v3"),
                             (TOPIC_POOL_CREATED_SOLIDLY, "solidly")):
            for pos in (1, 2):
                jobs.append((None, kind, None, topic0, pos))

    for n, (dex, kind, factory, topic0, pos) in enumerate(jobs, 1):
        label = dex or f"DEEP/{kind}"
        if verbose:
            print(f"   … log scan {n}/{len(jobs)}  {label} (topic{pos})", end="\r")
        try:
            logs = es.logs(topic0, tt, pos, factory)
        except Exception as e:  # noqa: BLE001
            if es.chain_unsupported:
                if "CHAIN_UNSUPPORTED" not in es.errors:
                    es.errors.append("CHAIN_UNSUPPORTED")
                    print(f"\n   ! Etherscan free khong ho tro chain nay — bo qua lop log."
                          f"\n     (lop subgraph thay the duoc, xem muc 4 trong README)")
                break
            msg = str(e)[:180]
            if msg not in es.errors:
                es.errors.append(msg)
                print(f"\n   ! loi khi quet {label}: {msg}")
            continue
        for log in logs:
            addr, fee = _pool_from_log(kind, log)
            if not addr:
                continue
            emitter = (log.get("address") or "").lower()
            d, k = factory_by_addr.get(emitter, (dex or f"Unknown ({emitter[:10]}…)", kind))
            _merge(out, Candidate(addr, d, k, fee, {"deep" if factory is None else "logs"}))
    if verbose:
        print(" " * 70, end="\r")
    return out


# ----------------------------------------------------------- 3. SINGLETON
def discover_singleton(es: Etherscan | None, rpc: Rpc, chain: dict, token: str,
                       verbose: bool = False) -> dict[str, Candidate]:
    """PancakeSwap Infinity / Uniswap V4: pool không có địa chỉ riêng, chỉ có poolId."""
    out: dict[str, Candidate] = {}
    if not es:
        return out
    tt = topic_addr(token)
    for dex, manager in chain.get("singletons", []):
        for pos in (1, 2, 3):
            try:
                logs = es.logs_by_topic_only(manager, tt, pos)
            except Exception as e:  # noqa: BLE001
                if verbose:
                    print(f"   ! {dex} topic{pos}: {e}")
                continue
            for log in logs:
                topics = log.get("topics") or []
                if not topics:
                    continue
                pool_id = topics[1] if len(topics) > 1 else None
                if not pool_id or len(pool_id) != 66:
                    continue
                c = Candidate(manager.lower(), dex, "singleton", None, {"singleton"})
                c.pool_id = pool_id.lower()
                _merge(out, c)
    return out


# ----------------------------------------------------------------- 4. API
def discover_dexscreener(chain: dict, token: str, verbose: bool = False) -> dict[str, Candidate]:
    url = f"https://api.dexscreener.com/token-pairs/v1/{chain['dexscreener_id']}/{token}"
    out: dict[str, Candidate] = {}
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        if verbose:
            print(f"   ! DexScreener loi: {e}")
        return out
    if isinstance(data, dict):
        data = data.get("pairs") or []
    for p in data or []:
        addr = (p.get("pairAddress") or "").lower()
        if not addr:
            continue
        labels = p.get("labels") or []
        dex = p.get("dexId", "?")
        if labels:
            dex = f"{dex} {'/'.join(labels)}"
        c = Candidate(addr, dex, "unknown", None, {"dexscreener"})
        liq = (p.get("liquidity") or {}).get("usd")
        c.api_liquidity_usd = float(liq) if liq is not None else None
        base = (p.get("baseToken") or {}).get("symbol", "?")
        quote = (p.get("quoteToken") or {}).get("symbol", "?")
        c.api_pair_label = f"{base}/{quote}"
        _merge(out, c)
    return out


def discover_geckoterminal(chain: dict, token: str, verbose: bool = False) -> dict[str, Candidate]:
    out: dict[str, Candidate] = {}
    net = chain["geckoterminal_id"]
    for page in range(1, 11):
        url = (f"https://api.geckoterminal.com/api/v2/networks/{net}"
               f"/tokens/{token}/pools?page={page}")
        try:
            r = requests.get(url, timeout=30, headers={"Accept": "application/json"})
            if r.status_code == 404:
                break
            r.raise_for_status()
            data = (r.json() or {}).get("data") or []
        except Exception as e:  # noqa: BLE001
            if verbose and page == 1:
                print(f"   ! GeckoTerminal loi: {e}")
            break
        if not data:
            break
        for p in data:
            attrs = p.get("attributes") or {}
            addr = (attrs.get("address") or "").lower()
            if not addr:
                continue
            dex = ((p.get("relationships") or {}).get("dex") or {}).get("data", {}).get("id", "?")
            c = Candidate(addr, dex, "unknown", None, {"geckoterminal"})
            rv = attrs.get("reserve_in_usd")
            c.api_liquidity_usd = float(rv) if rv is not None else None
            c.api_pair_label = attrs.get("name")
            _merge(out, c)
        if len(data) < 20:
            break
        time.sleep(2.1)  # free tier ~30 req/phút
    return out


# ----------------------------------------------------------- 5. SUBGRAPH
def discover_subgraph(chain: dict, token: str, api_key: str,
                      verbose: bool = False) -> dict[str, Candidate]:
    """Hỏi các subgraph đã cấu hình. Đây là nguồn DUY NHẤT tách được số dư
    theo từng pool của PancakeSwap Infinity / Uniswap V4."""
    from subgraph import Subgraph, SubgraphError

    out: dict[str, Candidate] = {}
    for dex, sid, kind in chain.get("subgraphs", []):
        try:
            sg = Subgraph(api_key, sid, verbose)
            rows = sg.pools_of_token(token)
        except SubgraphError as e:
            print(f"   ! subgraph {dex}: {str(e)[:150]}")
            continue
        except Exception as e:  # noqa: BLE001
            print(f"   ! subgraph {dex}: {str(e)[:150]}")
            continue
        n = 0
        for r in rows:
            if not r["id"]:
                continue
            c = Candidate(r["id"], dex, kind, r.get("fee"), {"subgraph"})
            if kind == "singleton":
                c.pool_id = r["id"]
            c.sg_token0, c.sg_token1 = r["token0"], r["token1"]
            c.sg_amt0, c.sg_amt1 = r["amount0"], r["amount1"]
            c.sg_usd = r["tvl_usd"]
            c.api_pair_label = f"{r['symbol0']}/{r['symbol1']}"
            _merge(out, c)
            n += 1
        print(f"      {dex}: {n} pool")
    return out


def merge_all(*stores: dict[str, Candidate]) -> dict[str, Candidate]:
    out: dict[str, Candidate] = {}
    for s in stores:
        for c in s.values():
            _merge(out, c)
    return out
