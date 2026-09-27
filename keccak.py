"""Keccak-256 thuần Python (không cần web3/pycryptodome).

Dùng để tính selector hàm và topic0 của event từ chuỗi signature,
nhờ vậy không phải hard-code hash nào cả.
"""

_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]

# r[x][y]
_ROT = [
    [0, 36, 3, 41, 18],
    [1, 44, 10, 45, 2],
    [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39, 8, 14],
]

_MASK = (1 << 64) - 1


def _rol(v, n):
    n %= 64
    return ((v << n) | (v >> (64 - n))) & _MASK


def _keccak_f1600(state: bytearray) -> bytearray:
    A = [int.from_bytes(state[8 * i:8 * i + 8], "little") for i in range(25)]
    for rnd in range(24):
        # theta
        C = [A[x] ^ A[x + 5] ^ A[x + 10] ^ A[x + 15] ^ A[x + 20] for x in range(5)]
        D = [C[(x - 1) % 5] ^ _rol(C[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                A[x + 5 * y] ^= D[x]
        # rho + pi
        B = [0] * 25
        for x in range(5):
            for y in range(5):
                B[y + 5 * ((2 * x + 3 * y) % 5)] = _rol(A[x + 5 * y], _ROT[x][y])
        # chi
        for x in range(5):
            for y in range(5):
                A[x + 5 * y] = B[x + 5 * y] ^ ((B[(x + 1) % 5 + 5 * y] ^ _MASK) & B[(x + 2) % 5 + 5 * y])
        # iota
        A[0] ^= _RC[rnd]
    out = bytearray()
    for i in range(25):
        out += A[i].to_bytes(8, "little")
    return out


def keccak256(data: bytes) -> bytes:
    rate = 136
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate != 0:
        padded.append(0x00)
    padded[-1] |= 0x80

    state = bytearray(200)
    for off in range(0, len(padded), rate):
        for i in range(rate):
            state[i] ^= padded[off + i]
        state = _keccak_f1600(state)
    return bytes(state[:32])


def keccak_hex(text: str) -> str:
    return "0x" + keccak256(text.encode()).hex()


def selector(signature: str) -> str:
    """selector('balanceOf(address)') -> '0x70a08231'"""
    return "0x" + keccak256(signature.encode())[:4].hex()


def event_topic(signature: str) -> str:
    """event_topic('PairCreated(address,address,address,uint256)') -> '0x0d36...'"""
    return keccak_hex(signature)


if __name__ == "__main__":
    assert keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert selector("transfer(address,uint256)") == "0xa9059cbb"
    assert selector("balanceOf(address)") == "0x70a08231"
    assert event_topic("PairCreated(address,address,address,uint256)") == (
        "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"
    )
    assert event_topic("PoolCreated(address,address,uint24,int24,address)") == (
        "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118"
    )
    print("keccak self-test OK")
