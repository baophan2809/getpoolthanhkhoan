"""Đọc trạng thái pool on-chain và quy đổi thanh khoản ra USD.

Nguyên tắc: KHÔNG tin con số USD của DexScreener/GeckoTerminal.
Số cuối cùng luôn tự tính từ số dư token thật trong pool × giá tự suy ra on-chain.
"""
from __future__ import annotations

from dataclasses import dataclass

from evm import (Rpc, TokenMeta, ZERO, dec_addr, dec_uint, enc, fetch_token_meta)

Q96 = 2 ** 96


@dataclass
class Pool:
    address: str
    dex: str
    kind: str               # v2 | v3 | singleton | unknown
    fee: int | None
    sources: set
    token0: str | None = None
    token1: str | None = None
    bal0: int = 0
    bal1: int = 0
    sqrt_price_x96: int | None = None
    reserves: tuple[int, int] | None = None
    amt0: float = 0.0
    amt1: float = 0.0
    val0: float | None = None
    val1: float | None = None
    tvl_usd: float | None = None
    api_liquidity_usd: float | None = None
    api_pair_label: str | None = None
    pool_id: str | None = None
    sg_amt0: float | None = None
    sg_amt1: float | None = None
    sg_usd: float | None = None
    note: str = ""

    @property
    def label(self) -> str:
        return self.api_pair_label or "?/?"


# ------------------------------------------------------------ đọc on-chain
def hydrate_pools(rpc: Rpc, cands: dict, verbose: bool = False) -> list[Pool]:
    pools = [
        Pool(c.address, c.dex, c.kind, c.fee, set(c.sources),
             api_liquidity_usd=c.api_liquidity_usd,
             api_pair_label=c.api_pair_label,
             pool_id=c.pool_id,
             sg_amt0=c.sg_amt0, sg_amt1=c.sg_amt1, sg_usd=c.sg_usd,
             token0=c.sg_token0, token1=c.sg_token1)
        for c in cands.values()
    ]
    # Pool kiểu singleton (PancakeSwap Infinity, Uniswap V4) không có địa chỉ riêng,
    # chỉ có poolId 32 byte. Gọi token0()/balanceOf() vào đó là vô nghĩa.
    for p in pools:
        if p.pool_id or len(p.address) == 66:
            p.kind = "singleton"
            p.pool_id = p.pool_id or p.address

    onchain = [p for p in pools if p.kind != "singleton"]
    if not onchain:
        return pools
    # pool đọc on-chain được thì token0/token1 lấy từ chuỗi, không tin subgraph
    for p in onchain:
        p.token0 = p.token1 = None

    if verbose:
        print(f"   … doc token0/token1/state cua {len(onchain)} pool")
    calls = []
    for p in onchain:
        calls.append((p.address, enc("token0()")))
        calls.append((p.address, enc("token1()")))
        calls.append((p.address, enc("getReserves()")))
        calls.append((p.address, enc("slot0()")))
    res = rpc.call_many(calls)

    alive = []
    for i, p in enumerate(onchain):
        t0, t1, rsv, s0 = res[4 * i:4 * i + 4]
        p.token0 = (dec_addr(t0) or "").lower() if t0 else None
        p.token1 = (dec_addr(t1) or "").lower() if t1 else None
        if not p.token0 or not p.token1 or p.token0 == ZERO or p.token1 == ZERO:
            p.note = "khong doc duoc token0/token1"
            continue
        if rsv:
            r0, r1 = dec_uint(rsv, 0), dec_uint(rsv, 1)
            if r0 is not None and r1 is not None:
                p.reserves = (r0, r1)
                if p.kind in ("unknown", "?"):
                    p.kind = "v2"
        if s0:
            sp = dec_uint(s0, 0)
            if sp:
                p.sqrt_price_x96 = sp
                if p.kind in ("unknown", "?"):
                    p.kind = "v3"
        alive.append(p)

    # số dư thật trong pool (chuẩn hơn reserves vì tính cả phí chưa thu của V3)
    calls = []
    for p in alive:
        calls.append((p.token0, enc("balanceOf(address)", p.address)))
        calls.append((p.token1, enc("balanceOf(address)", p.address)))
    res = rpc.call_many(calls)
    for i, p in enumerate(alive):
        p.bal0 = dec_uint(res[2 * i] or "0x0") or 0
        p.bal1 = dec_uint(res[2 * i + 1] or "0x0") or 0
        if p.bal0 == 0 and p.bal1 == 0 and p.reserves:
            p.bal0, p.bal1 = p.reserves
    return pools


# ------------------------------------------------------------------- giá
class PriceBook:
    def __init__(self, rpc: Rpc, chain: dict, meta: dict[str, TokenMeta]):
        self.rpc = rpc
        self.chain = chain
        self.meta = meta
        self.stables = {a.lower(): s for a, s in chain["stables"].items()}
        self.cache: dict[str, float | None] = {a: 1.0 for a in self.stables}
        self.wnative = chain["wnative"].lower()
        # factory V2 dùng làm oracle phụ trợ
        self.v2_factory = next((f for _, k, f in chain["factories"] if k == "v2"), None)

    def _v2_pair(self, a: str, b: str) -> str | None:
        if not self.v2_factory:
            return None
        raw = self.rpc.call(self.v2_factory, enc("getPair(address,address)", a, b))
        if not raw:
            return None
        addr = dec_addr(raw)
        return None if not addr or addr == ZERO else addr.lower()

    def _pair_price(self, token: str, quote: str) -> tuple[float, float] | None:
        """-> (giá token tính theo quote, quy mô pool tính theo quote)"""
        pair = self._v2_pair(token, quote)
        if not pair:
            return None
        res = self.rpc.call_many([
            (pair, enc("token0()")),
            (token, enc("balanceOf(address)", pair)),
            (quote, enc("balanceOf(address)", pair)),
        ])
        _, bt, bq = res
        bt = dec_uint(bt or "0x0") or 0
        bq = dec_uint(bq or "0x0") or 0
        if bt == 0 or bq == 0:
            return None
        mt, mq = self.meta.get(token), self.meta.get(quote)
        if not mt or not mq:
            return None
        at, aq = mt.amount(bt), mq.amount(bq)
        if at <= 0:
            return None
        return aq / at, aq

    def price(self, token: str, depth: int = 0) -> float | None:
        token = token.lower()
        if token in self.cache:
            return self.cache[token]
        if depth > 2:
            return None
        self.cache[token] = None  # chặn đệ quy vòng

        best: tuple[float, float] | None = None  # (giá usd, quy mô usd)
        for quote in list(self.stables) + [self.wnative]:
            if quote == token:
                continue
            qp = 1.0 if quote in self.stables else self.price(self.wnative, depth + 1)
            if not qp:
                continue
            got = self._pair_price(token, quote)
            if not got:
                continue
            px, size = got
            usd, size_usd = px * qp, size * qp
            if size_usd < 200:
                continue
            if best is None or size_usd > best[1]:
                best = (usd, size_usd)

        self.cache[token] = best[0] if best else None
        return self.cache[token]

    def set(self, token: str, usd: float):
        self.cache[token.lower()] = usd


def spot_price_1_per_0(p: Pool, meta: dict[str, TokenMeta]) -> float | None:
    """Giá token1 tính theo token0, lấy từ state pool."""
    m0, m1 = meta.get(p.token0), meta.get(p.token1)
    if not m0 or not m1:
        return None
    if p.sqrt_price_x96:
        ratio = (p.sqrt_price_x96 / Q96) ** 2  # token1/token0 theo đơn vị raw
        return ratio * (10 ** m0.decimals) / (10 ** m1.decimals)
    if p.reserves and p.reserves[0] > 0:
        a0 = m0.amount(p.reserves[0])
        a1 = m1.amount(p.reserves[1])
        return (a1 / a0) if a0 > 0 else None
    if p.bal0 > 0:
        a0, a1 = m0.amount(p.bal0), m1.amount(p.bal1)
        return (a1 / a0) if a0 > 0 else None
    return None


def derive_token_price(pools: list[Pool], token: str, book: PriceBook,
                       meta: dict[str, TokenMeta]) -> float | None:
    """Suy giá token cần quét từ pool sâu nhất có vế kia đã biết giá."""
    token = token.lower()
    best = None
    for p in pools:
        if p.kind == "singleton" or not p.token0 or not p.token1:
            continue
        if token not in (p.token0, p.token1):
            continue
        other = p.token1 if p.token0 == token else p.token0
        op = book.price(other)
        if not op:
            continue
        m_other = meta.get(other)
        if not m_other:
            continue
        other_bal = p.bal1 if p.token0 == token else p.bal0
        other_usd = m_other.amount(other_bal) * op
        if other_usd < 100:
            continue
        ratio = spot_price_1_per_0(p, meta)
        if not ratio or ratio <= 0:
            continue
        px = (ratio * op) if p.token0 == token else (op / ratio)
        if px <= 0:
            continue
        if best is None or other_usd > best[1]:
            best = (px, other_usd)
    return best[0] if best else None


def _price_both_sides(p: Pool, book: PriceBook, meta: dict[str, TokenMeta],
                      allow_ratio: bool = True) -> None:
    """Định giá hai vế của pool; nếu chỉ biết một vế thì suy vế kia từ tỷ giá pool."""
    p0, p1 = book.price(p.token0), book.price(p.token1)
    if allow_ratio and (p0 is None) != (p1 is None):
        ratio = spot_price_1_per_0(p, meta)
        if ratio and ratio > 0:
            if p0 is not None:
                p1 = p0 / ratio
            else:
                p0 = p1 * ratio
            p.note = (p.note + " | " if p.note else "") + "gia ve kia suy tu ty gia pool"
    p.val0 = p.amt0 * p0 if p0 is not None else None
    p.val1 = p.amt1 * p1 if p1 is not None else None
    if p.val0 is not None and p.val1 is not None:
        p.tvl_usd = p.val0 + p.val1
    elif p.val0 is not None or p.val1 is not None:
        p.tvl_usd = p.val0 if p.val0 is not None else p.val1
        p.note = (p.note + " | " if p.note else "") + "chi dinh gia duoc 1 ve"
    else:
        p.note = (p.note + " | " if p.note else "") + "khong dinh gia duoc"


def value_pools(pools: list[Pool], book: PriceBook, meta: dict[str, TokenMeta]) -> None:
    for p in pools:
        # Pool singleton: không đọc được on-chain theo từng pool, đành lấy số của
        # GeckoTerminal/DexScreener. Ghi chú rõ để không nhầm là số tự tính.
        if p.kind == "singleton":
            # Ưu tiên subgraph: nó cho SỐ LƯỢNG token thật của từng poolId,
            # mình tự nhân với bảng giá của mình -> số tự tính, không đi mượn.
            if (p.token0 and p.token1
                    and p.sg_amt0 is not None and p.sg_amt1 is not None):
                p.amt0, p.amt1 = p.sg_amt0, p.sg_amt1
                p.note = "so luong tu subgraph, gia tu tinh"
                _price_both_sides(p, book, meta, allow_ratio=False)
                if p.tvl_usd is None and p.api_liquidity_usd is not None:
                    p.tvl_usd = p.api_liquidity_usd
                    p.note = "uoc luong theo GeckoTerminal (subgraph khong dinh gia duoc)"
            elif p.api_liquidity_usd is not None:
                p.tvl_usd = p.api_liquidity_usd
                p.note = "uoc luong theo GeckoTerminal/DexScreener (pool singleton)"
            elif p.sg_usd is not None:
                p.tvl_usd = p.sg_usd
                p.note = "uoc luong theo subgraph"
            else:
                p.note = "pool singleton, chua co nguon nao bao TVL"
            continue
        if not p.token0 or not p.token1:
            continue
        m0, m1 = meta.get(p.token0), meta.get(p.token1)
        if not m0 or not m1:
            p.note = p.note or "thieu metadata token"
            continue
        p.amt0, p.amt1 = m0.amount(p.bal0), m1.amount(p.bal1)
        _price_both_sides(p, book, meta)


def collect_tokens(pools: list[Pool]) -> list[str]:
    s = set()
    for p in pools:
        for t in (p.token0, p.token1):
            if t and t != ZERO:
                s.add(t)
    return sorted(s)
