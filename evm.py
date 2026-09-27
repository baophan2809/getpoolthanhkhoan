"""Lớp giao tiếp EVM: JSON-RPC batch + encode/decode ABI tối giản.

Chỉ phụ thuộc `requests`. Không cần web3.py.
"""
from __future__ import annotations

import json
import time
from typing import Iterable

import requests

from keccak import selector

ZERO = "0x0000000000000000000000000000000000000000"


# ------------------------------------------------------------------ encode
def pad_addr(addr: str) -> str:
    return addr.lower().replace("0x", "").rjust(64, "0")


def pad_uint(n: int) -> str:
    return hex(n)[2:].rjust(64, "0")


def topic_addr(addr: str) -> str:
    return "0x" + pad_addr(addr)


def enc(sig: str, *args) -> str:
    """enc('getPair(address,address)', a, b) -> calldata hex"""
    data = selector(sig)
    for a in args:
        if isinstance(a, int):
            data += pad_uint(a)
        elif isinstance(a, str) and a.startswith("0x") and len(a) == 42:
            data += pad_addr(a)
        else:
            raise ValueError(f"Khong encode duoc tham so: {a!r}")
    return data


# ------------------------------------------------------------------ decode
def words(hexdata: str) -> list[str]:
    h = hexdata[2:] if hexdata.startswith("0x") else hexdata
    return [h[i:i + 64] for i in range(0, len(h) - len(h) % 64, 64)]


def dec_uint(hexdata: str, index: int = 0) -> int | None:
    w = words(hexdata)
    if index >= len(w):
        return None
    return int(w[index], 16)


def dec_int(hexdata: str, index: int = 0) -> int | None:
    v = dec_uint(hexdata, index)
    if v is None:
        return None
    return v - (1 << 256) if v >= (1 << 255) else v


def dec_addr(hexdata: str, index: int = 0) -> str | None:
    w = words(hexdata)
    if index >= len(w):
        return None
    return "0x" + w[index][24:]


def dec_string(hexdata: str) -> str:
    """Giải mã string ABI; fallback sang bytes32 (token đời cũ như MKR)."""
    if not hexdata or hexdata in ("0x", "0x0"):
        return ""
    w = words(hexdata)
    try:
        if len(w) >= 3:
            offset = int(w[0], 16)
            if offset == 32:
                length = int(w[1], 16)
                raw = bytes.fromhex("".join(w[2:]))[:length]
                return raw.decode("utf-8", "replace").strip("\x00")
    except Exception:
        pass
    try:
        return bytes.fromhex(w[0]).decode("utf-8", "replace").strip("\x00").strip()
    except Exception:
        return ""


# ------------------------------------------------------------------- client
class Rpc:
    def __init__(self, urls: list[str], batch_size: int = 60, verbose: bool = False):
        self.urls = [u for u in urls if u]
        if not self.urls:
            raise SystemExit("Chua co RPC url nao.")
        self.i = 0
        self.batch_size = batch_size
        self.verbose = verbose
        self.session = requests.Session()
        self.calls = 0

    def _post(self, payload):
        last_err = None
        for attempt in range(len(self.urls) * 2):
            url = self.urls[self.i % len(self.urls)]
            try:
                r = self.session.post(url, json=payload, timeout=45)
                if r.status_code == 429:
                    self.i += 1
                    time.sleep(0.8)
                    continue
                r.raise_for_status()
                return r.json()
            except Exception as e:  # noqa: BLE001
                last_err = e
                self.i += 1
                time.sleep(0.4)
        raise RuntimeError(f"RPC that bai sau nhieu lan thu: {last_err}")

    def call_many(self, calls: Iterable[tuple[str, str]], block: str = "latest") -> list[str | None]:
        """calls = [(to, data), ...] -> ['0x...', None nếu revert]"""
        calls = list(calls)
        out: list[str | None] = [None] * len(calls)
        for start in range(0, len(calls), self.batch_size):
            chunk = calls[start:start + self.batch_size]
            payload = [
                {"jsonrpc": "2.0", "id": start + k, "method": "eth_call",
                 "params": [{"to": to, "data": data}, block]}
                for k, (to, data) in enumerate(chunk)
            ]
            self.calls += len(chunk)
            resp = self._post(payload)
            if isinstance(resp, dict):
                resp = [resp]
            for item in resp:
                idx = item.get("id")
                if idx is None:
                    continue
                if "result" in item and item["result"] not in (None, "0x"):
                    out[idx] = item["result"]
            if self.verbose:
                print(f"   … eth_call {min(start + len(chunk), len(calls))}/{len(calls)}", end="\r")
        if self.verbose and calls:
            print(" " * 60, end="\r")
        return out

    def call(self, to: str, data: str) -> str | None:
        return self.call_many([(to, data)])[0]

    def block_number(self) -> int:
        resp = self._post({"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []})
        return int(resp["result"], 16)

    def get_logs(self, params: dict) -> list[dict]:
        resp = self._post({"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": [params]})
        if "error" in resp:
            raise RuntimeError(json.dumps(resp["error"])[:300])
        return resp.get("result") or []


# --------------------------------------------------------------- ERC20 view
SEL_BALANCE_OF = "balanceOf(address)"
SEL_DECIMALS = "decimals()"
SEL_SYMBOL = "symbol()"
SEL_TOTAL_SUPPLY = "totalSupply()"


class TokenMeta:
    __slots__ = ("address", "symbol", "decimals")

    def __init__(self, address: str, symbol: str = "?", decimals: int = 18):
        self.address = address
        self.symbol = symbol
        self.decimals = decimals

    def amount(self, raw: int) -> float:
        return raw / (10 ** self.decimals)

    def __repr__(self):
        return f"<{self.symbol} {self.address[:8]}…>"


def fetch_token_meta(rpc: Rpc, addresses: list[str]) -> dict[str, TokenMeta]:
    addresses = list(dict.fromkeys(a.lower() for a in addresses if a and a != ZERO))
    calls = []
    for a in addresses:
        calls.append((a, enc(SEL_SYMBOL)))
        calls.append((a, enc(SEL_DECIMALS)))
    res = rpc.call_many(calls)
    out = {}
    for k, a in enumerate(addresses):
        sym = dec_string(res[2 * k] or "") or a[:8]
        dec = dec_uint(res[2 * k + 1] or "") if res[2 * k + 1] else None
        out[a] = TokenMeta(a, sym[:20], 18 if dec is None or dec > 36 else dec)
    return out
