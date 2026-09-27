"""Cấu hình chain: factory, quote token, stablecoin, fee tier.

Muốn thêm DEX mới -> chỉ cần thêm 1 dòng vào FACTORIES của chain đó.
Sai địa chỉ factory cũng không gây lỗi: nó chỉ trả về 0 pool.
"""

# ---------------------------------------------------------------- BSC (56)
BSC = {
    "name": "bsc",
    "chain_id": 56,
    "dexscreener_id": "bsc",
    "geckoterminal_id": "bsc",
    "native_symbol": "BNB",
    "wnative": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",  # WBNB
    "explorer": "https://bscscan.com",
    "public_rpcs": [
        "https://bsc-dataseed.bnbchain.org",
        "https://bsc-dataseed1.defibit.io",
        "https://bsc-dataseed1.ninicoin.io",
        "https://rpc.ankr.com/bsc",
        "https://binance.llamarpc.com",
    ],
    # ký hiệu: v2 = UniswapV2-style, v3 = UniswapV3-style, solidly = Velodrome-style
    "factories": [
        ("PancakeSwap V2",   "v2", "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"),
        ("PancakeSwap V1",   "v2", "0xBCfCcbde45cE874adCB698cC183deBcF17952812"),
        ("PancakeSwap V3",   "v3", "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865"),
        ("Uniswap V2 (BSC)", "v2", "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6"),
        ("Uniswap V3 (BSC)", "v3", "0xdB1d10011AD0Ff90774D0C6Bb92e5C5c8b4461F7"),
        ("Biswap",           "v2", "0x858E3312ed3A876947EA49d572A7C42DE08af7EE"),
        ("ApeSwap",          "v2", "0x0841BD0B734E4F5853f0dD8d7Ea041c241fb0Da6"),
        ("BakerySwap",       "v2", "0x01bF7C66c6BD861915CdaaE475042d3c4BaE16A7"),
        ("MDEX",             "v2", "0x3CD1C46068dAEa5Ebb0d3f55F6915B10648062B8"),
        ("SushiSwap V2",     "v2", "0xc35DADB65012eC5796536bD9864eD8773aBc74C4"),
        ("SushiSwap V3",     "v3", "0x126555dd55a39328F69400d6aE4F782Bd4C34ABb"),
        ("BabySwap",         "v2", "0x86407bEa2078ea5f5EB5A52B2caA963bC1F889Da"),
        ("Nomiswap",         "v2", "0xd6715A8be3944ec72738F0BFDC739d48C3c29349"),
        ("Squadswap V2",     "v2", "0x918d7e714243F7d9d463C37e106235dCde294ffC"),
        ("Squadswap V3",     "v3", "0xB456A2D1eCb1bC9a58D0C55C7d4B9be7C97e5Ba0"),
    ],
    # PancakeSwap Infinity (kiến trúc singleton như Uniswap V4)
    "singletons": [
        ("PancakeSwap Infinity CL",  "0xa0FfB9c1CE1Fe56963B0321B32E7A0302114058b"),
        ("PancakeSwap Infinity Bin", "0xC697d2898e0D09264376196696c51D7aBbbAA4a9"),
    ],
    "vault": "0x238a358808379702088667322f80aC48bAd5e6c4",  # Infinity Vault giữ token
    # (tên hiển thị, subgraph id tren The Graph, kieu pool)
    # Đây là nguồn DUY NHẤT tách được số dư theo từng pool của Infinity.
    # Chạy `python poolscan.py <token> --graph-probe` để kiểm tra từng subgraph.
    "subgraphs": [
        ("PancakeSwap Infinity CL", "8jFYxwKP8tNGSDisucpHRK1ojUchZd7ELd8zh2ugHGDN", "singleton"),
        # exchange-v3-bsc: da ngung sync (tra ve 0 pool cho token moi) -> tat.
        # V3 van doc duoc on-chain o lop brute nen khong thieu gi.
        # ("PancakeSwap V3 (subgraph)", "Hv1GncLY5docZoGtXjo4kwbTvxm3MAhVZqBZE4sUT9eZ", "v3"),
    ],
    "stables": {
        "0x55d398326f99059fF775485246999027B3197955": "USDT",
        "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d": "USDC",
        "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56": "BUSD",
        "0x8d0D000Ee44948FC98c9B98A4FA4921476f08B0d": "USD1",
        "0xc5f0f7b66764F6ec8C8Dff7BA683102295E16409": "FDUSD",
        "0x1AF3F329e8BE154074D8769D1FFa4eE058B1DBc3": "DAI",
        "0x14016E85a25aeb13065688cAFB43044C2ef86784": "TUSD",
    },
    # các token thường được dùng làm "vế kia" của pool
    "quotes": [
        "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",  # WBNB
        "0x55d398326f99059fF775485246999027B3197955",  # USDT
        "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",  # USDC
        "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",  # BUSD
        "0x8d0D000Ee44948FC98c9B98A4FA4921476f08B0d",  # USD1
        "0xc5f0f7b66764F6ec8C8Dff7BA683102295E16409",  # FDUSD
        "0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c",  # BTCB
        "0x2170Ed0880ac9A755fd29B2688956BD959F933F8",  # ETH
        "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82",  # CAKE
        "0x1AF3F329e8BE154074D8769D1FFa4eE058B1DBc3",  # DAI
        "0x14016E85a25aeb13065688cAFB43044C2ef86784",  # TUSD
    ],
    "fee_tiers": [100, 200, 400, 500, 1500, 2500, 3000, 10000, 20000],
}

# ---------------------------------------------------------- Ethereum (1)
ETHEREUM = {
    "name": "ethereum",
    "chain_id": 1,
    "dexscreener_id": "ethereum",
    "geckoterminal_id": "eth",
    "native_symbol": "ETH",
    "wnative": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "explorer": "https://etherscan.io",
    "public_rpcs": ["https://eth.llamarpc.com", "https://rpc.ankr.com/eth"],
    "factories": [
        ("Uniswap V2",     "v2", "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"),
        ("Uniswap V3",     "v3", "0x1F98431c8aD98523631AE4a59f267346ea31F984"),
        ("SushiSwap V2",   "v2", "0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac"),
        ("PancakeSwap V2", "v2", "0x1097053Fd2ea711dad45caCcc45EfF7548fCB362"),
        ("PancakeSwap V3", "v3", "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865"),
    ],
    "singletons": [("Uniswap V4", "0x000000000004444c5dc75cB358380D2e3dE08A90")],
    "vault": None,
    "subgraphs": [
        ("Uniswap V4", "6XvRX3WHSvzBVTiPdF66XSBVbxWuHqijWANbjJxRDyzr", "singleton"),
    ],
    "stables": {
        "0xdAC17F958D2ee523a2206206994597C13D831ec7": "USDT",
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48": "USDC",
        "0x6B175474E89094C44Da98b954EedeAC495271d0F": "DAI",
    },
    "quotes": [
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",  # WBTC
    ],
    "fee_tiers": [100, 500, 2500, 3000, 10000],
}

# --------------------------------------------------------------- Base (8453)
BASE = {
    "name": "base",
    "chain_id": 8453,
    "dexscreener_id": "base",
    "geckoterminal_id": "base",
    "native_symbol": "ETH",
    "wnative": "0x4200000000000000000000000000000000000006",
    "explorer": "https://basescan.org",
    "public_rpcs": ["https://mainnet.base.org", "https://base.llamarpc.com"],
    "factories": [
        ("Uniswap V2",     "v2", "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6"),
        ("Uniswap V3",     "v3", "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"),
        ("PancakeSwap V3", "v3", "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865"),
        ("Aerodrome",  "solidly", "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"),
    ],
    "singletons": [("Uniswap V4", "0x498581fF718922c3f8e6A244956aF099B2652b2b")],
    "vault": None,
    "subgraphs": [
        ("Uniswap V4 Base", "2L6yxqUZ7dT6GWoTy9qxNBkf9kEk65me3XPMvbGsmJUZ", "singleton"),
    ],
    "stables": {
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913": "USDC",
        "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA": "USDbC",
        "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb": "DAI",
    },
    "quotes": [
        "0x4200000000000000000000000000000000000006",
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA",
        "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
        "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf",  # cbBTC
    ],
    "fee_tiers": [100, 500, 2500, 3000, 10000],
}

CHAINS = {"bsc": BSC, "ethereum": ETHEREUM, "eth": ETHEREUM, "base": BASE}


def get_chain(name: str) -> dict:
    key = name.lower()
    if key not in CHAINS:
        raise SystemExit(f"Chain khong ho tro: {name}. Cho phep: {sorted(set(CHAINS))}")
    return CHAINS[key]
