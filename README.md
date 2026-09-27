# poolscan — quét toàn bộ pool thanh khoản của một token

Nhập contract token → script quét **tất cả** pool trên chain, đọc số dư thật trong từng
pool và tự quy đổi ra USD. Không lấy con số USD của DexScreener làm kết quả cuối.

---

## 1. Vì sao DexScreener thiếu pool

DexScreener là **indexer** chứ không phải nguồn on-chain. Nó chỉ hiện những pool mà nó
đã index và vượt qua bộ lọc nội bộ của nó. Bốn trường hợp hay bị sót:

1. **Pool ghép với token "lạ"** — DexScreener ưu tiên các cặp với WBNB/USDT/USDC.
   Pool ghép với USD1, FDUSD, BTCB hay một token dự án khác dễ bị bỏ hoặc index trễ.
2. **DEX chưa được hỗ trợ** — một factory mới (fork của Pancake/Uniswap) có thể mất
   nhiều ngày mới được thêm vào.
3. **PancakeSwap Infinity (kiến trúc như Uniswap V4)** — pool không có địa chỉ riêng,
   toàn bộ token nằm trong một Vault chung, index kiểu cũ không bắt được.
4. **Bộ lọc chống spam** — pool mới, thanh khoản lệch một chiều, hoặc token bị gắn cờ
   có thể bị ẩn khỏi kết quả.

Binance Alpha chạy indexer riêng của họ và gộp thanh khoản của tất cả các venue mà bộ
định tuyến của họ đi qua → nên số của Alpha thường cao hơn.

**Cách duy nhất chuẩn 100% là đọc thẳng on-chain.** Đó là việc script này làm.

---

## 2. Cách script làm việc

Bốn lớp tìm pool chạy song song rồi gộp lại, khử trùng lặp theo địa chỉ pool:

| Lớp | Cách làm | Bắt được gì | Cần key? |
|---|---|---|---|
| `brute` | Gọi thẳng `factory.getPair()` / `getPool()` với ~11 token đối ứng × 9 mức phí | Toàn bộ pool của các DEX đã biết | Không |
| `logs` | Quét event `PairCreated` / `PoolCreated` từ block 0, lọc theo token | Pool ghép với token lạ không có trong danh sách quote | Etherscan V2 |
| `deep` | Quét event trên **toàn chain, không lọc factory** (`--deep`) | Pool trên cả DEX chưa có trong config | Etherscan V2 |
| `subgraph` | Hỏi subgraph PancakeSwap Infinity / V3 trên The Graph | **Pool Infinity/V4** — nguồn duy nhất tách được số dư theo từng poolId | The Graph |
| `api` | DexScreener + GeckoTerminal | Phần đuôi dài, DEX ngoại lai | Không |

Sau đó với **mọi** pool tìm được, script đọc on-chain:

- `token0()`, `token1()` → xác định cặp
- `balanceOf(token, pool)` cho cả hai vế → số dư **thật** (chuẩn hơn `getReserves()`
  vì tính cả phí V3 chưa thu)
- `slot0()` / `getReserves()` → giá spot

Rồi tự dựng bảng giá: stablecoin = $1 → giá BNB lấy từ pool WBNB/USDT →
giá token cần quét suy ra từ pool sâu nhất có vế kia đã biết giá.

`TVL = số_dư_vế_A × giá_A + số_dư_vế_B × giá_B`

---

## 3. Cài đặt

```bash
pip install -r requirements.txt
cp config.example.json config.json     # rồi điền key vào
```

Kiểm tra script chạy đúng (không cần mạng):

```bash
python selftest.py     # 36 test encode/decode/parse/dinh gia
python mocktest.py     # chạy full luồng trên một BSC giả lập
```

---

## 4. API key

**Quan trọng nhất — The Graph** (miễn phí): https://thegraph.com/studio/apikeys/
Điền vào `thegraph_api_key` trong `config.json`. Đây là nguồn DUY NHẤT tách được số dư
theo từng pool của PancakeSwap Infinity — loại pool thường chiếm phần lớn thanh khoản
của token Binance Alpha và bị DexScreener bỏ sót.

Kiểm tra key và subgraph chạy được không:

```bash
python poolscan.py 0xTokenAddress --graph-probe
```

Lệnh này in ra từng subgraph: kết nối được không, schema tên field là gì, trả về bao
nhiêu pool. Nếu có subgraph nào báo lỗi, gửi nguyên output đó để sửa lại ID/field.

**RPC riêng** — NodeReal / dRPC / Ankr, điền vào `config.json` theo thứ tự ưu tiên.
Script tự xoay vòng sang RPC khác khi gặp lỗi hoặc 429. Public RPC vẫn chạy được nhưng
hay bị rate-limit vì một lần quét tốn ~500-900 `eth_call` (đã gom thành JSON-RPC batch
60 call/request).

**Etherscan V2 — KHÔNG dùng được cho BSC.** Free tier chỉ hỗ trợ Ethereum; với BSC nó
trả về *"Free API access is not supported for this chain. Please upgrade your apiplan"*.
Muốn dùng lớp `logs` / `--deep` trên BSC thì phải mua gói trả phí. Cứ để
`etherscan_api_key` rỗng — script tự bỏ qua lớp đó và báo một dòng, ba lớp còn lại vẫn
chạy đủ. Trên Ethereum thì key free vẫn dùng được bình thường.

**Không bắt buộc:** Arkham — dùng để lấy top holder có gắn nhãn của token, là cách chéo
để phát hiện pool của DEX lạ.

---

## 5. Dùng

```bash
# quét cơ bản
python poolscan.py 0xTokenAddress

# quét kỹ nhất (khuyên dùng khi nghi ngờ thiếu pool)
python poolscan.py 0xTokenAddress --chain bsc --deep

# xem cả những pool nhỏ (mặc định chỉ hiện pool >= $50K)
python poolscan.py 0xTokenAddress --min-usd 0

# thêm token đối ứng lạ vào phép dò brute-force
python poolscan.py 0xTokenAddress --quote 0xTokenKhac
```

| Tham số | Ý nghĩa |
|---|---|
| `--chain` | `bsc` (mặc định), `ethereum`, `base` |
| `--deep` | Quét event toàn chain — chậm hơn nhưng bắt được DEX chưa biết |
| `--min-usd` | Chỉ hiện pool có TVL từ ngưỡng này trở lên (mặc định **$50,000**). Không ảnh hưởng tới tổng, cũng không ảnh hưởng tới file CSV/JSON — cả hai luôn giữ đủ mọi pool |
| `--no-api` | Bỏ DexScreener/GeckoTerminal, chỉ dùng on-chain |
| `--no-alpha` | Bỏ bước đối chiếu với Binance Alpha |
| `--no-graph` | Bỏ lớp subgraph |
| `--graph-probe` | Chỉ kiểm tra kết nối + schema của từng subgraph rồi thoát |
| `--top` | Giới hạn số **cặp** ở khối kết quả cuối. Mặc định `0` = hiện hết |
| `--pools-per-pair` | Số pool liệt kê trong mỗi cặp (mặc định 10, `0` = hết) |
| `--quote` | Thêm token đối ứng, lặp lại nhiều lần được |
| `-v` | In tiến trình chi tiết |

Terminal in ra hai bảng:

1. **Chi tiết từng pool** — mỗi dòng một pool, có địa chỉ pool và nguồn tìm ra nó.
2. **Tổng hợp theo cặp** — gộp mọi pool của cùng một cặp lại, xếp từ lớn xuống bé,
   kèm % trên tổng, số pool và danh sách DEX mà cặp đó nằm trên. Ví dụ TKN/WBNB có
   pool ở cả PancakeSwap V2 lẫn Biswap thì gộp thành một dòng.

Ngưỡng `--min-usd` áp cho **tổng của cả cặp**, không phải từng pool — nên một cặp rải
trên 3 pool mỗi pool $20K vẫn hiện, vì cộng lại là $60K.

Cuối cùng là **khối KẾT QUẢ** in sát dấu nhắc lệnh: tất cả cặp đạt ngưỡng `--min-usd`,
và **bên trong mỗi cặp là danh sách pool tạo nên nó** — DEX, số tiền, số lượng hai vế,
poolId đầy đủ không cắt, link explorer:

```
  ── 1. B2/WBNB   $729,598.21   84.1% tong   14 pool   1.10M B2
      1) $    727,731.00  PancakeSwap V3 (v3 0.01%)  [tu tinh]
         1.10M B2 + 379.97 WBNB
         0xc1a780989734a0e5df875cebe410748562e1c5e6
         https://bscscan.com/address/0xc1a780989734a0e5df875cebe410748562e1c5e6
      2) $      1,234.00  Uniswap V4 (singleton)  [uoc luong GeckoTerminal]
         …
      … con 4 pool nho hon, tong $633.21   (--pools-per-pair 0 de xem het)
```

Ngưỡng `--min-usd` áp cho **tổng của cả cặp**; pool lẻ bên trong nhỏ hơn ngưỡng vẫn được
liệt kê, vì nó là thành phần của cặp đã đạt. Mỗi pool có nhãn `[tu tinh]` hay
`[uoc luong GeckoTerminal]` để biết ngay số đó tự tính hay đi mượn. Phần bị rút gọn luôn
được nói rõ còn bao nhiêu pool và tổng bao nhiêu, kèm cách xem hết.

Ba file được ghi ra: `out/<SYMBOL>_<addr>_<time>.csv` (chi tiết pool),
`_pairs.csv` (gộp theo cặp) và `.json` (đủ cả hai + dữ liệu Binance Alpha).

Bảng chỉ hiện từ $50,000 trở lên, nhưng **tổng thanh khoản luôn cộng đủ mọi pool** — nếu
tổng bị cắt theo bộ lọc thì phép so với Binance Alpha sẽ sai. File CSV/JSON cũng luôn lưu
đủ, bộ lọc chỉ tác động lên phần in ra màn hình.

Script cũng tự gọi API danh sách token của Binance Alpha và in ra con số `liquidity`
của Alpha để đối chiếu. **Phép so được đặt đúng chỗ:** Alpha chỉ tính pool đọc được
on-chain, nên script so con số của Alpha với **phần tự tính**, không phải với tổng đã
cộng cả phần ước lượng V4/Infinity:

```
  B2   gia $0.41430801
  Tu tinh tu on-chain    :     $729.6K   (37 pool)
  Binance Alpha bao      :     $729.7K   (lech -0.01%)
  + uoc luong V4/Infinity:     $139.0K   (80 pool — so cua GeckoTerminal, Alpha thuong khong tinh)
  = TONG CONG            :     $868.6K   (117 pool)
```

Cộng gộp rồi mới so sẽ ra "lệch +19%" và làm tưởng script sai, trong khi phần tự tính
khớp Alpha tới 0,01%.

---

## 6. Điểm còn hạn chế — cần biết

**PancakeSwap Infinity và Uniswap V4 (pool singleton).** Hai loại này dùng kiến trúc
singleton — pool không có địa chỉ hợp đồng riêng mà chỉ là một `poolId` 32 byte, toàn
bộ token nằm chung trong một Vault. Không thể gọi `token0()` hay `balanceOf()` lên một
poolId, nên không tách được số dư bằng cách đọc chuỗi thông thường.

Script xử lý theo hai mức, ưu tiên từ trên xuống:

1. **Có subgraph** → lấy SỐ LƯỢNG token thật của từng poolId từ subgraph, rồi tự nhân
   với bảng giá on-chain của mình. Con số USD của subgraph bị bỏ qua.
2. **Không có subgraph** → lấy tạm số TVL của GeckoTerminal, ghi rõ là ước lượng.

**Tình trạng hiện tại (BSC): đang chạy ở mức 2.** Subgraph `PancakeSwap Infinity CL Bsc`
(`8jFYxw…ugHGDN`) là bản duy nhất tồn tại trên The Graph và nó đang hỏng — gateway trả
về `bad indexers: BadResponse(no attestation: indexing_error)`. PancakeSwap cũng chưa
công bố subgraph Infinity nào khác; trang subgraph chính thức của họ chỉ có V2, V3 và
StableSwap. Không sửa được từ phía script.

Khi nào có subgraph Infinity dùng được, chỉ cần thêm vào `config.json`, **không phải
sửa code**:

```json
"subgraphs": {
  "bsc": [["PancakeSwap Infinity CL", "<subgraph id moi>", "singleton"]]
}
```

Rồi chạy `--graph-probe` để kiểm tra. Script tự dò tên entity và tên field nên subgraph
nào cũng nhận, miễn nó có hai vế pool.

**Trong lúc đó, phần ước lượng được kiểm chứng bằng on-chain.** Vault Infinity là hợp
đồng thật, đọc `balanceOf` được, nên script so số của GeckoTerminal với lượng token thật
nằm trong Vault:

```
   KIEM CHUNG ON-CHAIN cho phan Infinity:
     Vault 0x238a3588… dang giu 169.9K DEBIT = $553.6K
     So bao cao cho pool Infinity: $2.97M  ->  ve kia ≈ $2.42M
     ✓ Hop ly (ve DEBIT khop voi so du that trong Vault)
```

Nếu nguồn ngoài báo số NHỎ HƠN giá trị token thật trong Vault thì chắc chắn nó sai hoặc
thiếu pool — script sẽ cảnh báo. Phép này không chứng minh vế kia đúng, nhưng bắt được
trường hợp nguồn ngoài lỗi thời nặng.

**Danh sách factory.** Nằm trong `chains.py`, sửa trực tiếp được — thêm một dòng
`("Tên DEX", "v2"|"v3"|"solidly", "0xFactory")` là xong. Điền sai địa chỉ cũng không
gây lỗi, chỉ là không tìm được pool nào từ factory đó. Chế độ `--deep` không phụ thuộc
danh sách này nên vẫn bắt được DEX thiếu.

**Con số TVL của pool V3** tính theo tổng số dư trong pool (giống cách DexScreener và
GeckoTerminal làm), tức bao gồm cả thanh khoản nằm ngoài khoảng giá hiện tại. Nếu anh
cần "thanh khoản thực sự dùng được quanh giá hiện tại" thì đó là phép tính khác — nói
tôi làm thêm.

---

## 7. Cấu trúc file

```
poolscan.py      CLI, điều phối, in bảng, xuất CSV/JSON, đối chiếu Binance Alpha
discovery.py     4 lớp tìm pool
valuation.py     Đọc state pool, dựng bảng giá, quy đổi USD
evm.py           JSON-RPC batch + encode/decode ABI (không cần web3)
keccak.py        Keccak-256 thuần Python → tự tính selector/topic từ signature
chains.py        Cấu hình BSC / Ethereum / Base
selftest.py      36 test offline
mocktest.py      Chạy full luồng trên BSC giả lập
```
