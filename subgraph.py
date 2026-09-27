"""Lớp subgraph (The Graph) — dùng cho pool singleton kiểu PancakeSwap Infinity.

Vì sao cần: Infinity/V4 không có địa chỉ pool riêng, token nằm chung trong Vault,
nên không đọc được số dư từng pool bằng balanceOf. Subgraph là nơi duy nhất có
số dư tách theo từng poolId.

Script LẤY SỐ LƯỢNG TOKEN từ subgraph rồi TỰ ĐỊNH GIÁ bằng bảng giá on-chain của
mình, không lấy con số USD của subgraph — để nhất quán với các pool khác.

Toàn bộ tên entity/field được dò bằng GraphQL introspection, không hard-code:
Infinity gọi hai vế là currency0/currency1, Uniswap gọi là token0/token1, và mỗi
subgraph lại đặt tên field TVL một kiểu.
"""
from __future__ import annotations

import json

import requests

GATEWAY = "https://gateway.thegraph.com/api"

# các cách đặt tên hai vế của pool, thử lần lượt
TOKEN_PAIR_NAMES = [("token0", "token1"), ("currency0", "currency1"),
                    ("tokenA", "tokenB"), ("asset0", "asset1")]
CAND_TVL_USD = ["totalValueLockedUSD", "tvlUSD", "liquidityUSD", "reserveUSD",
                "totalValueLockedUSDUntracked"]
CAND_AMT0 = ["totalValueLockedToken0", "totalValueLockedCurrency0", "tvlToken0",
             "reserve0", "balance0", "amount0"]
CAND_AMT1 = ["totalValueLockedToken1", "totalValueLockedCurrency1", "tvlToken1",
             "reserve1", "balance1", "amount1"]
CAND_FEE = ["feeTier", "fee", "swapFee", "lpFee"]

INTROSPECT = """
{
  __schema {
    queryType { fields { name } }
    types {
      name
      kind
      fields { name type { kind name ofType { kind name } } }
    }
  }
}
"""


class SubgraphError(RuntimeError):
    pass


def _base_kind(tp: dict) -> tuple[str, str]:
    """Bóc NON_NULL/LIST để lấy kind + tên thật của kiểu field."""
    while tp and tp.get("kind") in ("NON_NULL", "LIST") and tp.get("ofType"):
        tp = tp["ofType"]
    return (tp or {}).get("kind") or "", (tp or {}).get("name") or ""


class Subgraph:
    def __init__(self, api_key: str, subgraph_id: str, verbose: bool = False):
        self.api_key = api_key
        self.subgraph_id = subgraph_id
        self.verbose = verbose
        self.session = requests.Session()
        self.schema: dict | None = None      # kết quả dò được
        self.diag: dict = {}                 # thông tin để chẩn đoán khi hỏng

    # --- hai kiểu xác thực mà gateway chấp nhận, thử lần lượt ---
    def _endpoints(self):
        yield f"{GATEWAY}/{self.api_key}/subgraphs/id/{self.subgraph_id}", {}
        yield (f"{GATEWAY}/subgraphs/id/{self.subgraph_id}",
               {"Authorization": f"Bearer {self.api_key}"})

    def query(self, gql: str, variables: dict | None = None) -> dict:
        last = None
        for url, headers in self._endpoints():
            try:
                r = self.session.post(url, json={"query": gql, "variables": variables or {}},
                                      headers=headers, timeout=60)
                if r.status_code in (401, 403, 404):
                    last = f"HTTP {r.status_code}: {r.text[:160]}"
                    continue
                r.raise_for_status()
                js = r.json()
                if js.get("errors"):
                    txt = json.dumps(js["errors"])
                    if "bad indexers" in txt or "indexing_error" in txt:
                        raise SubgraphError(
                            "subgraph dang HONG phia The Graph (indexer bao indexing_error) "
                            "— khong phai loi cua script, khong sua duoc tu day. "
                            "Doi no duoc index lai, hoac thay subgraph id khac trong config.json")
                    raise SubgraphError(txt[:400])
                return js.get("data") or {}
            except SubgraphError:
                raise
            except Exception as e:  # noqa: BLE001
                last = str(e)[:200]
        raise SubgraphError(last or "khong goi duoc gateway")

    # ------------------------------------------------------------ schema
    def discover_schema(self) -> dict:
        """Dò entity pool + tên field. Trả về dict mô tả cách truy vấn."""
        if self.schema:
            return self.schema

        data = self.query(INTROSPECT)
        sch = (data or {}).get("__schema") or {}
        root_fields = {f["name"] for f in (sch.get("queryType") or {}).get("fields") or []}
        types = [t for t in sch.get("types") or []
                 if t.get("kind") == "OBJECT" and t.get("fields")
                 and not (t.get("name") or "").startswith("__")]

        self.diag = {
            "type_count": len(types),
            "pool_like": [t["name"] for t in types
                          if "pool" in t["name"].lower() or "pair" in t["name"].lower()][:20],
        }

        best = None
        for t in types:
            fields = {f["name"]: f for f in t["fields"]}
            for a, b in TOKEN_PAIR_NAMES:
                if a not in fields or b not in fields:
                    continue
                root = self._root_for(t["name"], root_fields)
                if not root:
                    continue
                names = set(fields)
                pick = lambda cands: next((c for c in cands if c in names), None)  # noqa: E731
                kind0, _ = _base_kind(fields[a].get("type") or {})
                cand = {
                    "entity": t["name"], "root": root,
                    "tok0": a, "tok1": b,
                    "tok_is_object": kind0 == "OBJECT",
                    "tvl_usd": pick(CAND_TVL_USD),
                    "amt0": pick(CAND_AMT0), "amt1": pick(CAND_AMT1),
                    "fee": pick(CAND_FEE),
                    "all_fields": sorted(names),
                }
                # ưu tiên entity có đủ số lượng token của cả hai vế
                score = (2 if cand["amt0"] and cand["amt1"] else 0) \
                    + (1 if cand["tvl_usd"] else 0) \
                    + (1 if t["name"].lower() in ("pool", "clpool") else 0)
                if best is None or score > best[0]:
                    best = (score, cand)
                break

        if not best:
            raise SubgraphError(
                "khong tim thay entity pool. Cac type giong pool: "
                + (", ".join(self.diag["pool_like"]) or "(khong co)"))
        self.schema = best[1]
        if self.verbose:
            print(f"      schema: {self.schema['entity']} qua {self.schema['root']}")
        return self.schema

    @staticmethod
    def _root_for(entity: str, root_fields: set[str]) -> str | None:
        lower = entity[0].lower() + entity[1:]
        for cand in (lower + "s", entity.lower() + "s", lower + "es",
                     lower, entity.lower()):
            if cand in root_fields:
                return cand
        # dự phòng: root field nào bắt đầu bằng tên entity viết thường
        for rf in sorted(root_fields):
            if rf.lower().rstrip("s") == entity.lower():
                return rf
        return None

    # ------------------------------------------------------------- pools
    def pools_of_token(self, token: str, limit: int = 500) -> list[dict]:
        f = self.discover_schema()
        tok0, tok1 = f["tok0"], f["tok1"]

        if f["tok_is_object"]:
            sel = [f"{tok0} {{ id symbol decimals }}", f"{tok1} {{ id symbol decimals }}"]
        else:
            sel = [tok0, tok1]
        sel = ["id"] + sel
        for role in ("tvl_usd", "amt0", "amt1", "fee"):
            if f.get(role):
                sel.append(f[role])
        body = "\n      ".join(sel)

        order = f", orderBy: {f['tvl_usd']}, orderDirection: desc" if f.get("tvl_usd") else ""
        gql = f"""
        query($tok: String!) {{
          a: {f['root']}(first: {limit}, where: {{{tok0}: $tok}}{order}) {{
            {body}
          }}
          b: {f['root']}(first: {limit}, where: {{{tok1}: $tok}}{order}) {{
            {body}
          }}
        }}"""
        data = self.query(gql, {"tok": token.lower()})

        out = {}
        for row in (data.get("a") or []) + (data.get("b") or []):
            v0, v1 = row.get(tok0), row.get(tok1)
            if isinstance(v0, dict):
                a0, s0 = (v0.get("id") or "").lower(), v0.get("symbol") or "?"
                a1, s1 = (v1 or {}).get("id", "").lower(), (v1 or {}).get("symbol") or "?"
            else:
                a0, s0 = str(v0 or "").lower(), "?"
                a1, s1 = str(v1 or "").lower(), "?"
            pid = (row.get("id") or "").lower()
            if not pid:
                continue
            out[pid] = {
                "id": pid, "token0": a0, "token1": a1, "symbol0": s0, "symbol1": s1,
                "amount0": _f(row.get(f["amt0"])) if f.get("amt0") else None,
                "amount1": _f(row.get(f["amt1"])) if f.get("amt1") else None,
                "tvl_usd": _f(row.get(f["tvl_usd"])) if f.get("tvl_usd") else None,
                "fee": _i(row.get(f["fee"])) if f.get("fee") else None,
            }
        return list(out.values())


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
