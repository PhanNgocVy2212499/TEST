"""
=============================================================================
SCRIPT UNIVERSAL NEWS SCRAPER
=============================================================================
Mô tả:
    Script cào (scrape) dữ liệu tin tức từ BẤT KỲ trang báo Việt Nam nào.
    Người dùng chỉ cần nhập URL trang chủ (ví dụ: tuoitre.vn, znews.vn),
    script sẽ TỰ ĐỘNG:
        1. Quét trang chủ → phát hiện các chuyên mục (Thể thao, Kinh doanh, ...)
        2. Dò mẫu phân trang (pagination) phù hợp của trang đó
        3. Thu thập link bài viết từ từng chuyên mục (nhiều trang)
        4. Cào tiêu đề + nội dung mỗi bài viết
        5. Lưu kết quả ra file CSV

Cách sử dụng:
    python scrape_all.py
    → Nhập: tuoitre.vn, znews.vn      (có thể nhập nhiều trang, cách bằng dấu phẩy)
    → Script tự quét, tìm chuyên mục, cào bài viết

Thư viện sử dụng:
    - requests        : Gửi HTTP request tải trang web
    - BeautifulSoup   : Phân tích cú pháp HTML, trích xuất dữ liệu
    - ThreadPoolExecutor : Cào đa luồng (nhiều bài cùng lúc) để tăng tốc
    - csv             : Đọc/ghi file CSV
    - threading.Lock  : Khóa đồng bộ, đảm bảo ghi file CSV an toàn khi đa luồng
    - urllib.parse     : Phân tích, ghép nối URL
    - re              : Biểu thức chính quy (regex) để lọc URL, kiểm tra bài viết
    - random, time    : Tạo độ trễ ngẫu nhiên giữa các request (chống bị chặn)
=============================================================================
"""

# =============================================================================
# IMPORT THƯ VIỆN
# =============================================================================

import csv          # Thư viện đọc/ghi file CSV (định dạng bảng dữ liệu)
import os           # Tương tác hệ điều hành: kiểm tra file tồn tại, đường dẫn, ...
import random       # Tạo số ngẫu nhiên: chọn User-Agent, tạo thời gian nghỉ ngẫu nhiên
import re           # Regular Expression (biểu thức chính quy): lọc, tìm kiếm mẫu trong chuỗi
import threading    # Hỗ trợ đa luồng: Lock để ghi file an toàn khi nhiều luồng chạy song song
import time         # Đo thời gian, tạo độ trễ (sleep) giữa các request

# ThreadPoolExecutor: Tạo nhóm luồng (thread pool) để chạy song song nhiều tác vụ
# as_completed: Lấy kết quả từ các tác vụ khi chúng hoàn thành (không cần chờ theo thứ tự)
from concurrent.futures import ThreadPoolExecutor, as_completed

# urljoin: Ghép URL tương đối thành URL tuyệt đối (ví dụ: "/the-thao" + "tuoitre.vn" → "https://tuoitre.vn/the-thao")
# urlparse: Tách URL thành các thành phần (scheme, netloc, path, query, ...)
from urllib.parse import urljoin, urlparse

import requests         # Gửi HTTP GET/POST request để tải nội dung trang web
from bs4 import BeautifulSoup  # BeautifulSoup: phân tích HTML, tìm thẻ, trích xuất text


# =============================================================================
# PHẦN 1: CẤU HÌNH CHUNG (CONFIGURATION)
# =============================================================================

# --- DANH SÁCH USER-AGENT GIẢ LẬP ---
# Mỗi khi gửi request tới trang web, trình duyệt sẽ gửi kèm chuỗi User-Agent
# để server biết "ai" đang truy cập (ví dụ: Chrome, Firefox, Safari, ...).
# Nếu dùng 1 User-Agent cố định → server dễ phát hiện là bot → chặn.
# Giải pháp: Xoay vòng (rotate) ngẫu nhiên giữa 5 User-Agent khác nhau giả lập
# các trình duyệt phổ biến: Chrome, Safari, Firefox, Edge.
USER_AGENTS = [
    # Google Chrome trên Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",

    # Safari trên macOS Sonoma (14.4)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",

    # Mozilla Firefox trên Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",

    # Microsoft Edge trên Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",

    # Google Chrome trên macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# --- KHÓA ĐỒNG BỘ CHO VIỆC GHI FILE CSV ---
# Khi nhiều luồng (thread) cùng ghi vào 1 file CSV → dữ liệu có thể bị xen kẽ, hỏng.
# threading.Lock() tạo một "khóa" — chỉ cho phép 1 luồng ghi tại một thời điểm.
# Luồng nào muốn ghi phải "xin khóa" (acquire), ghi xong thì "trả khóa" (release).
csv_lock = threading.Lock()


# --- BẢNG ÁNH XẠ SLUG CHUYÊN MỤC → NHÃN TIẾNG VIỆT ---
# "Slug" là phần đường dẫn URL đại diện cho chuyên mục, ví dụ:
#   https://tuoitre.vn/the-thao → slug = "the-thao"
#   https://dantri.com.vn/kinh-doanh → slug = "kinh-doanh"
#
# Vấn đề: Mỗi trang báo dùng slug khác nhau nhưng cùng 1 chủ đề.
#   Ví dụ: "kinh-te", "tai-chinh", "kinh-doanh" → đều là "Kinh doanh"
#          "bong-da", "the-thao" → đều là "Thể thao"
#
# Giải pháp: Bảng KNOWN_CATEGORY_SLUGS ánh xạ (mapping) từ slug → nhãn chuẩn.
# Khi phát hiện chuyên mục, script dùng bảng này để gán nhãn thống nhất.
# Nếu slug không có trong bảng → tự động capitalize (ví dụ: "xu-huong" → "Xu Huong").
KNOWN_CATEGORY_SLUGS = {
    # --- Thể thao ---
    "the-thao": "Thể thao",          # Slug phổ biến nhất cho thể thao
    "bong-da": "Thể thao",           # Bóng đá cũng xếp vào Thể thao

    # --- Kinh doanh ---
    "kinh-doanh": "Kinh doanh",      # Một số báo dùng "kinh-doanh"
    "kinh-te": "Kinh doanh",         # Một số báo dùng "kinh-te"
    "tai-chinh": "Kinh doanh",       # Tài chính → gom vào Kinh doanh
    "bat-dong-san": "Kinh doanh",    # Bất động sản → gom vào Kinh doanh

    # --- Giáo dục ---
    "giao-duc": "Giáo dục",
    "tuyen-sinh": "Giáo dục",        # Tuyển sinh → Giáo dục
    "du-hoc": "Giáo dục",            # Du học → Giáo dục

    # --- Giải trí ---
    "giai-tri": "Giải trí",
    "sao": "Giải trí",               # Tin sao (ngôi sao) → Giải trí
    "am-nhac": "Giải trí",           # Âm nhạc → Giải trí
    "phim": "Giải trí",              # Phim ảnh → Giải trí

    # --- Sức khỏe & Đời sống ---
    "suc-khoe": "Sức khỏe",
    "doi-song": "Đời sống",

    # --- Thế giới ---
    "the-gioi": "Thế giới",
    "quoc-te": "Thế giới",           # Quốc tế → Thế giới

    # --- Pháp luật ---
    "phap-luat": "Pháp luật",
    "an-ninh-hinh-su": "Pháp luật",  # An ninh hình sự → Pháp luật

    # --- Các chuyên mục khác ---
    "du-lich": "Du lịch",
    "khoa-hoc": "Khoa học",
    "cong-nghe": "Công nghệ",
    "so-hoa": "Công nghệ",           # Số hóa → Công nghệ
    "van-hoa": "Văn hóa",
    "thoi-su": "Thời sự",
    "chinh-tri": "Thời sự",          # Chính trị → Thời sự
    "xa-hoi": "Xã hội",
    "oto-xe-may": "Xe",
    "xe": "Xe",
    "nhip-song-tre": "Nhịp sống trẻ",
    "tam-su": "Đời sống",            # Tâm sự → Đời sống
    "gia-dinh": "Đời sống",          # Gia đình → Đời sống
    "thoi-trang": "Thời trang",
    "lao-dong-viec-lam": "Lao động",
    "moi-truong": "Môi trường",
    "nong-nghiep": "Nông nghiệp",
    "quoc-phong": "Quốc phòng",
    "goc-nhin": "Góc nhìn",
    "su-kien": "Sự kiện",
    "tin-tuc": "Tin tức",
    "chinh-sach": "Chính sách",
}


# --- DANH SÁCH CÁC ĐƯỜNG DẪN CẦN BỎ QUA ---
# Khi quét trang chủ để tìm chuyên mục, có rất nhiều link KHÔNG phải chuyên mục tin tức:
#   - Trang liên hệ, giới thiệu, tuyển dụng, quảng cáo
#   - Trang đăng nhập, đăng ký, tìm kiếm
#   - Mục video, podcast, ảnh (không phải bài viết dạng text)
#   - Trang đặc biệt: longform, megastory, e-paper
# Các slug nằm trong SKIP_PATHS sẽ bị loại → không nhận nhầm là chuyên mục.
SKIP_PATHS = {
    # Trang thông tin, liên hệ
    "lien-he", "contact", "about", "gioi-thieu", "quang-cao",
    "dieu-khoan", "chinh-sach-bao-mat", "tuyen-dung", "rss", "sitemap",

    # Multimedia (không phải bài viết text)
    "video", "podcast", "infographic", "photo", "anh", "multimedia",

    # Trang chức năng (login, search, ...)
    "login", "dang-nhap", "dang-ky", "register", "search", "tim-kiem",

    # Thẻ tag, tác giả, phân trang
    "tag", "tags", "author", "tac-gia", "page", "trang",

    # Trang đặc biệt
    "thu-vien", "brand-voice", "megastory", "longform", "special",
    "english", "e-paper", "e-magazine",
}


# --- CÁC MẪU PHÂN TRANG PHỔ BIẾN (PAGINATION PATTERNS) ---
# Mỗi trang báo có cách phân trang (chia bài ra nhiều trang) khác nhau.
# Script sẽ thử từng mẫu trên trang thứ 2 của chuyên mục.
# Mẫu nào trả về HTTP 200 + nội dung đủ dài (> 5000 ký tự) → đó là mẫu đúng.
#
# Mỗi lambda nhận 2 tham số:
#   - base: URL chuyên mục gốc (ví dụ: "https://tuoitre.vn/the-thao")
#   - page: Số trang cần truy cập (2, 3, 4, ...)
# Trả về: URL trang phân trang tương ứng
PAGINATION_PATTERNS = [
    # Mẫu 1: Tuổi Trẻ — /the-thao/trang-2.htm
    # Nếu URL gốc có đuôi .htm → thay thế, nếu không → nối thêm
    lambda base, page: (
        base.replace(".htm", "") + f"/trang-{page}.htm"
        if ".htm" in base
        else base.rstrip("/") + f"/trang-{page}.htm"
    ),

    # Mẫu 2: Dân Trí — /the-thao/trang-2.htm (cách nối đơn giản hơn)
    lambda base, page: base.rstrip("/") + f"/trang-{page}.htm",

    # Mẫu 3: VnExpress — /the-thao-p2
    lambda base, page: base.rstrip("/") + f"-p{page}",

    # Mẫu 4: VietnamNet — /the-thao-page2
    lambda base, page: base.rstrip("/") + f"-page{page}",

    # Mẫu 5: Zing News, Thanh Niên — /the-thao?page=2 (query parameter)
    lambda base, page: base.rstrip("/") + f"?page={page}",

    # Mẫu 6: WordPress, một số trang blog — /the-thao/page/2
    lambda base, page: base.rstrip("/") + f"/page/{page}",
]


# =============================================================================
# PHẦN 2: CÁC HÀM TIỆN ÍCH (UTILITY FUNCTIONS)
# =============================================================================

def get_headers(referer=None):
    """
    Tạo HTTP headers giả lập trình duyệt thật.

    Tham số:
        referer (str, tùy chọn): URL trang trước đó (giúp request trông tự nhiên hơn,
                                  vì trình duyệt thật luôn gửi Referer).

    Trả về:
        dict: Dictionary chứa các header HTTP.

    Giải thích từng header:
        - User-Agent: Chuỗi nhận dạng trình duyệt (chọn ngẫu nhiên từ danh sách)
        - Accept: Loại nội dung mà "trình duyệt" chấp nhận (HTML, XML, ...)
        - Accept-Language: Ngôn ngữ ưu tiên (tiếng Việt trước, tiếng Anh sau)
        - Connection: Giữ kết nối mở (keep-alive) để tăng tốc
        - Referer: Trang đã truy cập trước đó (tùy chọn)
    """
    headers = {
        "User-Agent": random.choice(USER_AGENTS),    # Chọn ngẫu nhiên 1 User-Agent
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def polite_sleep(min_sec=2, max_sec=4):
    """
    Nghỉ ngẫu nhiên giữa các request (polite crawling).

    Tại sao cần sleep?
        - Nếu gửi request liên tục quá nhanh → server phát hiện là bot → chặn IP.
        - "Polite crawling" = gửi request với tốc độ giống người dùng thật.
        - Nghỉ ngẫu nhiên 2-4 giây giữa mỗi request (không đều nhau → khó bị phát hiện hơn).

    Tham số:
        min_sec (float): Thời gian nghỉ tối thiểu (giây), mặc định = 2
        max_sec (float): Thời gian nghỉ tối đa (giây), mặc định = 4
    """
    time.sleep(random.uniform(min_sec, max_sec))


def fetch_html(url, retries=3, referer=None):
    """
    Tải trang web và chuyển thành đối tượng BeautifulSoup để phân tích HTML.

    Cơ chế retry (thử lại):
        - Lần 1: Tải ngay
        - Nếu lỗi → đợi 3 giây → thử lại (lần 2)
        - Nếu lỗi → đợi 6 giây → thử lại (lần 3)
        - Nếu vẫn lỗi → trả về None
        Thời gian chờ tăng dần (attempt × 3 giây) — gọi là "exponential backoff".

    Tham số:
        url (str): URL trang cần tải
        retries (int): Số lần thử lại tối đa (mặc định = 3)
        referer (str): URL trang trước (tùy chọn)

    Trả về:
        BeautifulSoup: Đối tượng đã parse HTML, hoặc None nếu thất bại
    """
    for attempt in range(1, retries + 1):
        try:
            # Gửi HTTP GET request với headers giả lập, timeout 20 giây
            resp = requests.get(url, headers=get_headers(referer), timeout=20)

            # Nếu status code KHÔNG phải 2xx (200, 201, ...) → ném lỗi HTTPError
            resp.raise_for_status()

            # Parse HTML bằng parser có sẵn của Python (html.parser)
            return BeautifulSoup(resp.text, "html.parser")

        except requests.RequestException as e:
            # Nếu chưa hết số lần thử → đợi rồi thử lại
            if attempt < retries:
                time.sleep(attempt * 3)  # Lần 1: 3s, lần 2: 6s, ...
            else:
                # Hết số lần thử → in lỗi và trả về None
                print(f"  [LỖI] {url} — {e}")
    return None


def normalize_url(base_url, href):
    """
    Chuyển đổi URL tương đối thành URL tuyệt đối (absolute URL).

    Ví dụ:
        base_url = "https://tuoitre.vn"
        href = "/the-thao/bai-viet-123.htm"
        → Kết quả: "https://tuoitre.vn/the-thao/bai-viet-123.htm"

    Cũng lọc bỏ các href không hợp lệ:
        - href rỗng (None, "")
        - href là javascript (javascript:void(0))
        - href là anchor (#section)
        - href là email (mailto:...)

    Tham số:
        base_url (str): URL gốc (trang đang duyệt)
        href (str): Giá trị thuộc tính href của thẻ <a>

    Trả về:
        str: URL tuyệt đối, hoặc None nếu href không hợp lệ
    """
    if not href:
        return None
    href = href.strip()
    # Bỏ qua các link JavaScript, anchor, email
    if href.startswith(("javascript:", "#", "mailto:")):
        return None
    # urljoin ghép base_url với href → tạo URL tuyệt đối
    return urljoin(base_url, href)


def get_domain(url):
    """
    Trích xuất tên miền (domain) từ URL, bỏ tiền tố "www.".

    Ví dụ:
        "https://www.tuoitre.vn/the-thao" → "tuoitre.vn"
        "https://dantri.com.vn" → "dantri.com.vn"

    Dùng để: So sánh domain, kiểm tra link có cùng trang báo không.
    """
    return urlparse(url).netloc.replace("www.", "")


def get_base_url(url):
    """
    Lấy phần gốc của URL (scheme + domain), bỏ path và query.

    Ví dụ:
        "https://tuoitre.vn/the-thao/trang-2.htm?ref=abc" → "https://tuoitre.vn"

    Dùng để: Ghép URL tương đối, tạo referer header.
    """
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def init_csv(filepath):
    """
    Khởi tạo file CSV đầu ra.

    Nếu file chưa tồn tại → tạo mới và ghi dòng header (tiêu đề cột).
    Nếu file đã tồn tại → giữ nguyên, sẽ append (thêm dữ liệu) vào cuối.

    Cột dữ liệu:
        - url     : Đường dẫn bài báo gốc
        - label   : Nhãn chuyên mục (Thể thao, Kinh doanh, ...)
        - title   : Tiêu đề bài báo
        - content : Nội dung toàn bộ bài báo
        - source  : Tên trang báo nguồn (Tuoitre, Dantri, Znews, ...)

    Encoding utf-8-sig: UTF-8 kèm BOM (Byte Order Mark) — giúp Excel mở file đúng
    tiếng Việt (không bị lỗi font khi mở bằng Excel).
    """
    if not os.path.exists(filepath):
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(["url", "label", "title", "content", "source"])
        print(f"[INFO] Đã tạo file: {filepath}")
    else:
        print(f"[INFO] File đã tồn tại, append vào: {filepath}")


def append_row(filepath, row):
    """
    Thêm 1 dòng dữ liệu vào file CSV (thread-safe).

    Sử dụng csv_lock (threading.Lock) để đảm bảo chỉ 1 luồng ghi tại 1 thời điểm.
    Nếu không có Lock → 2 luồng ghi đồng thời → dữ liệu bị xen kẽ, hỏng file.

    Quy trình:
        1. Luồng A xin khóa (acquire) → được → ghi dữ liệu → trả khóa (release)
        2. Luồng B xin khóa → chờ → luồng A trả khóa → luồng B ghi → trả khóa

    Tham số:
        filepath (str): Đường dẫn file CSV
        row (list): Danh sách giá trị 1 dòng [url, label, title, content, source]
    """
    with csv_lock:  # Tự động acquire() khi vào, release() khi ra khỏi with
        with open(filepath, "a", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(row)


# =============================================================================
# PHẦN 3: TỰ ĐỘNG PHÁT HIỆN CHUYÊN MỤC TỪ TRANG CHỦ
# =============================================================================

def slug_to_label(slug):
    """
    Chuyển slug URL thành nhãn (label) tiếng Việt có dấu.

    Quy trình:
        1. Chuẩn hóa slug: bỏ dấu "/", chuyển thường
        2. Tra bảng KNOWN_CATEGORY_SLUGS:
           - Nếu tìm thấy → trả về nhãn chuẩn (ví dụ: "the-thao" → "Thể thao")
           - Nếu không tìm thấy → capitalize từng từ (ví dụ: "xu-huong" → "Xu Huong")

    Tham số:
        slug (str): Slug từ URL (ví dụ: "the-thao", "kinh-doanh")

    Trả về:
        str: Nhãn tiếng Việt (ví dụ: "Thể thao", "Kinh doanh")
    """
    slug_clean = slug.strip("/").lower()

    # Tra bảng slug → label đã biết
    if slug_clean in KNOWN_CATEGORY_SLUGS:
        return KNOWN_CATEGORY_SLUGS[slug_clean]

    # Slug chưa biết → tự tạo label bằng cách capitalize
    # "xu-huong" → ["xu", "huong"] → ["Xu", "Huong"] → "Xu Huong"
    words = slug_clean.replace("-", " ").split()
    return " ".join(w.capitalize() for w in words)


def is_category_path(path):
    """
    Kiểm tra xem một đường dẫn (path) có phải là chuyên mục báo hay không.

    Tiêu chí để là chuyên mục:
        ✓ Chỉ có 1 segment (ví dụ: "/the-thao", KHÔNG phải "/the-thao/bai-viet-123")
        ✓ Không nằm trong SKIP_PATHS (không phải trang liên hệ, video, login, ...)
        ✓ Không chứa 3+ chữ số liên tiếp (tránh nhận nhầm ID bài viết: "/123456")
        ✓ Độ dài slug hợp lý: 2 → 35 ký tự

    Tham số:
        path (str): Đường dẫn URL (ví dụ: "/the-thao", "/kinh-doanh/bai-viet-123.htm")

    Trả về:
        bool: True nếu là chuyên mục, False nếu không phải
    """
    path = path.strip("/")
    # Bỏ đuôi .htm, .html để phân tích
    path_clean = re.sub(r'\.(htm|html)$', '', path)

    if not path_clean:
        return False  # Path rỗng → bỏ qua

    # Tách thành các segment bằng dấu "/"
    segments = path_clean.split("/")

    # Chuyên mục chỉ có 1 segment (ví dụ: "the-thao")
    # Nếu > 1 segment (ví dụ: "the-thao/bai-viet-123") → đó là bài viết, không phải chuyên mục
    if len(segments) > 1:
        return False

    slug = segments[0]

    # Kiểm tra slug có nằm trong danh sách bỏ qua không
    if slug.lower() in SKIP_PATHS:
        return False

    # Nếu slug chứa 3+ chữ số liên tiếp → có thể là ID bài viết (ví dụ: "123456")
    if re.search(r'\d{3,}', slug):
        return False

    # Slug quá ngắn (< 2 ký tự) hoặc quá dài (> 35 ký tự) → không hợp lệ
    if len(slug) < 2 or len(slug) > 35:
        return False

    return True


def discover_categories(homepage_url):
    """
    Quét trang chủ của trang báo → tự động phát hiện các chuyên mục tin tức.

    Đây là hàm QUAN TRỌNG NHẤT — cho phép script hoạt động với BẤT KỲ trang báo nào
    mà không cần cấu hình trước (hardcode) danh sách chuyên mục.

    Quy trình:
        1. Tải HTML trang chủ
        2. Tìm tất cả link (<a href>) trong vùng navigation (nav, header, menu)
           → Dùng 12 CSS selector khác nhau để tương thích nhiều giao diện báo
        3. Nếu không tìm thấy nav → fallback: quét TẤT CẢ link trong trang
        4. Lọc: chỉ giữ link cùng domain, path 1 segment, không nằm trong SKIP_PATHS
        5. Ánh xạ slug → label tiếng Việt bằng slug_to_label()
        6. Loại bỏ trùng lặp (cùng label)

    Tham số:
        homepage_url (str): URL trang chủ (ví dụ: "https://tuoitre.vn")

    Trả về:
        dict: {label: url} — Ví dụ: {"Thể thao": "https://tuoitre.vn/the-thao", ...}
    """
    domain = get_domain(homepage_url)    # Lấy domain: "tuoitre.vn"
    base = get_base_url(homepage_url)    # Lấy base: "https://tuoitre.vn"

    print(f"\n  🔍 Đang quét trang chủ: {homepage_url}")
    soup = fetch_html(homepage_url, referer=homepage_url)
    if soup is None:
        print(f"  [LỖI] Không thể truy cập {homepage_url}")
        return {}

    # --- Bước 1: Tìm link trong vùng navigation/menu ---
    # Thử 12 CSS selector phổ biến — mỗi trang báo có cấu trúc HTML khác nhau,
    # nên cần nhiều selector để tăng tỷ lệ tìm thấy.
    nav_selectors = [
        "nav a[href]",                    # Thẻ <nav> — chuẩn HTML5
        "header a[href]",                 # Thẻ <header>
        "ul.menu a[href]",               # <ul class="menu">
        "ul.nav a[href]",                # <ul class="nav">
        "ul.main-nav a[href]",           # <ul class="main-nav">
        ".main-menu a[href]",            # <div class="main-menu">
        ".navigation a[href]",           # <div class="navigation">
        ".nav-menu a[href]",             # <div class="nav-menu">
        ".header-menu a[href]",          # <div class="header-menu">
        ".top-menu a[href]",             # <div class="top-menu">
        "[class*='menu'] a[href]",       # Bất kỳ class nào chứa "menu"
        "[class*='nav'] a[href]",        # Bất kỳ class nào chứa "nav"
    ]

    # Gom tất cả link tìm được từ các selector
    candidate_links = []
    for selector in nav_selectors:
        candidate_links.extend(soup.select(selector))

    # Nếu không tìm thấy link nào trong nav → fallback: quét TẤT CẢ link
    if not candidate_links:
        candidate_links = soup.find_all("a", href=True)

    # --- Bước 2: Lọc và phân loại link thành chuyên mục ---
    categories = {}       # Kết quả: {label: url}
    seen_labels = set()   # Tập nhãn đã thấy — tránh trùng lặp

    for a_tag in candidate_links:
        href = a_tag.get("href", "")
        full_url = normalize_url(base, href)  # Chuyển thành URL tuyệt đối
        if not full_url:
            continue

        # Kiểm tra: link phải cùng domain với trang báo
        # (loại bỏ link quảng cáo, link ngoài)
        link_domain = get_domain(full_url)
        if domain not in link_domain and link_domain not in domain:
            continue

        # Kiểm tra: path phải là chuyên mục (1 segment, hợp lệ)
        parsed = urlparse(full_url)
        if not is_category_path(parsed.path):
            continue

        # Lấy slug và chuyển thành label
        slug = parsed.path.strip("/").split("/")[0]
        slug = re.sub(r'\.(htm|html)$', '', slug)  # Bỏ đuôi .htm
        label = slug_to_label(slug)

        # Bỏ qua nếu label đã tồn tại (tránh trùng)
        if label in seen_labels:
            continue
        seen_labels.add(label)

        # Tạo URL sạch (bỏ query string, fragment)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        categories[label] = clean_url

    # In kết quả
    print(f"  ✓ Tìm thấy {len(categories)} chuyên mục")
    for label, url in categories.items():
        print(f"    • {label}: {url}")

    return categories


# =============================================================================
# PHẦN 4: TỰ PHÁT HIỆN MẪU PHÂN TRANG
# =============================================================================

def detect_pagination_pattern(category_url):
    """
    Tự động dò tìm mẫu phân trang (pagination) phù hợp cho chuyên mục.

    Cách hoạt động:
        - Lần lượt thử 6 mẫu phân trang (PAGINATION_PATTERNS) với trang số 2
        - Mẫu nào trả về HTTP 200 + nội dung > 5000 ký tự → đó là mẫu đúng
        - Nếu không mẫu nào đúng → trả về None (chỉ cào trang 1)

    Tại sao thử trang 2?
        Trang 1 luôn có nội dung (là trang gốc), nên không dùng để kiểm tra.
        Trang 2 = trang phân trang đầu tiên → nếu trả về nội dung → mẫu đúng.

    Tại sao kiểm tra len(resp.text) > 5000?
        Một số server trả về 200 nhưng nội dung rỗng hoặc trang lỗi (< 5000 ký tự).
        Chỉ chấp nhận khi nội dung đủ lớn (có bài viết thật).

    Tham số:
        category_url (str): URL chuyên mục (ví dụ: "https://tuoitre.vn/the-thao")

    Trả về:
        function: Hàm lambda tạo URL phân trang, hoặc None nếu không tìm thấy
    """
    print(f"  🔎 Đang dò mẫu phân trang...", end="")

    for i, pattern_fn in enumerate(PAGINATION_PATTERNS):
        try:
            # Tạo URL trang 2 theo mẫu đang thử
            test_url = pattern_fn(category_url, 2)

            # Gửi request thử
            resp = requests.get(test_url, headers=get_headers(category_url), timeout=15)

            # Nếu HTTP 200 + nội dung đủ dài → mẫu đúng!
            if resp.status_code == 200 and len(resp.text) > 5000:
                print(f" mẫu #{i+1} OK")
                return pattern_fn

        except Exception:
            # Lỗi mạng, timeout, ... → bỏ qua mẫu này, thử mẫu tiếp theo
            continue

    # Không mẫu nào phù hợp
    print(f" không tìm thấy → chỉ cào trang 1")
    return None


# =============================================================================
# PHẦN 5: THU THẬP LINK BÀI VIẾT
# =============================================================================

def is_article_url(href, domain):
    """
    Kiểm tra xem một URL có phải là bài viết tin tức hay không (dùng heuristic).

    "Heuristic" = quy tắc dựa trên kinh nghiệm (không 100% chính xác nhưng hiệu quả).

    Tiêu chí để là bài viết:
        ✓ Cùng domain với trang báo
        ✓ Không phải multimedia (video, photo, infographic, podcast)
        ✓ Không phải trang phân trang (trang-2, page/2, ...)
        ✓ Slug cuối cùng đủ dài + nhiều dấu gạch ngang (≥ 3 dấu "-")
          Vì bài viết thường có slug dạng: "viet-nam-vo-dich-aff-cup-2025"
          Còn chuyên mục chỉ có: "the-thao"

    Tham số:
        href (str): URL cần kiểm tra
        domain (str): Domain của trang báo (ví dụ: "tuoitre.vn")

    Trả về:
        bool: True nếu là bài viết, False nếu không phải
    """
    if not href:
        return False

    # Kiểm tra cùng domain (loại bỏ link quảng cáo, link ngoài)
    link_domain = get_domain(href)
    if domain not in link_domain and link_domain not in domain:
        return False

    parsed = urlparse(href)
    path = parsed.path.strip("/")
    if not path:
        return False

    # Loại bỏ các URL multimedia
    path_lower = path.lower()
    for skip in ["video", "photo", "infographic", "podcast", "/anh/", "multimedia"]:
        if skip in path_lower:
            return False

    # Loại bỏ URL phân trang (trang-2, /page/2, -page2, -p2)
    if re.search(r'(trang-|/page/|-page\d|-p\d)', path_lower):
        return False

    # Lấy segment cuối cùng trong path (phần slug bài viết)
    segments = path.split("/")
    last_segment = segments[-1]
    last_clean = re.sub(r'\.(htm|html)$', '', last_segment)  # Bỏ đuôi .htm

    # --- Heuristic 1: Slug có ≥ 3 dấu gạch ngang → rất có thể là bài viết ---
    # Ví dụ: "viet-nam-thang-thai-lan-3-0" có 5 dấu "-" → bài viết
    if last_clean.count("-") >= 3:
        return True

    # --- Heuristic 2: Path có ≥ 2 segment + slug dài > 15 ký tự ---
    # Ví dụ: "/the-thao/tong-hop-ket-qua" → 2 segment, slug dài → bài viết
    if len(segments) >= 2 and len(last_clean) > 15:
        return True

    # --- Heuristic 3: Có đuôi .htm/.html + slug có ≥ 2 dấu "-" ---
    if (path.endswith(".htm") or path.endswith(".html")) and last_clean.count("-") >= 2:
        return True

    return False


def extract_article_links(soup, base_url, domain):
    """
    Trích xuất tất cả link bài viết từ 1 trang danh sách chuyên mục.

    Chiến lược 2 bước:
        Bước 1 (Ưu tiên): Tìm link trong các thẻ cấu trúc bài viết
            → article, h2, h3, [class*='article'], [class*='title']
            Vì trang danh sách thường hiển thị bài viết trong thẻ <article>, <h2>, <h3>

        Bước 2 (Fallback): Nếu bước 1 tìm được < 5 link
            → Quét TẤT CẢ thẻ <a> trong trang
            Trường hợp trang có cấu trúc HTML không chuẩn

    Tham số:
        soup (BeautifulSoup): HTML đã parse của trang danh sách
        base_url (str): URL gốc (để ghép URL tương đối)
        domain (str): Domain trang báo

    Trả về:
        set: Tập hợp URL bài viết (không trùng lặp)
    """
    links = set()  # Dùng set để tự động loại trùng

    # --- Bước 1: Ưu tiên tìm trong các thẻ bài viết ---
    for sel in [
        "article a[href]",                # Thẻ <article> — chuẩn HTML5
        "h2 a[href]",                     # Tiêu đề bài viết thường nằm trong <h2>
        "h3 a[href]",                     # Hoặc <h3>
        ".article-item a[href]",          # Class phổ biến cho item bài viết
        ".news-item a[href]",             # Class phổ biến cho item tin tức
        "[class*='article'] a[href]",     # Bất kỳ class nào chứa "article"
        "[class*='title'] a[href]",       # Bất kỳ class nào chứa "title"
    ]:
        for a_tag in soup.select(sel):
            full = normalize_url(base_url, a_tag.get("href", ""))
            if full and is_article_url(full, domain):
                links.add(full)

    # --- Bước 2: Fallback nếu tìm được ít link ---
    if len(links) < 5:
        for a_tag in soup.find_all("a", href=True):
            full = normalize_url(base_url, a_tag["href"])
            if full and is_article_url(full, domain):
                links.add(full)

    return links


def collect_links(category_url, domain, max_pages=50):
    """
    Thu thập link bài viết từ 1 chuyên mục, duyệt qua nhiều trang phân trang.

    Quy trình:
        1. Cào trang 1 → thu thập link
        2. Tự dò mẫu phân trang (detect_pagination_pattern)
        3. Duyệt trang 2 → trang max_pages (mặc định 50):
           - Tải HTML từng trang → trích xuất link → gom lại
           - Cơ chế an toàn:
             a) Anti-loop: Nếu link trang hiện tại TRÙNG trang trước → DỪNG
                (có nghĩa server trả về cùng 1 trang → đã hết bài)
             b) No new links: Nếu không có link mới nào → DỪNG
             c) Consecutive failures: Nếu 5 lỗi liên tiếp → DỪNG
             d) Empty page: Nếu trang trả về 0 link → HẾT BÀI → DỪNG

    Tham số:
        category_url (str): URL chuyên mục (ví dụ: "https://tuoitre.vn/the-thao")
        domain (str): Domain trang báo
        max_pages (int): Số trang tối đa cần duyệt (mặc định = 50)

    Trả về:
        set: Tập hợp tất cả URL bài viết đã thu thập (không trùng lặp)
    """
    base_url = get_base_url(category_url)
    all_links = set()          # Tập hợp tất cả link đã thu thập
    prev_page_links = set()    # Link trang trước — dùng để phát hiện loop

    # ---- TRANG 1 ----
    print(f"  📄 Trang 1/{max_pages}", end="")
    soup = fetch_html(category_url, referer=base_url)
    if soup is None:
        print(f" → LỖI")
        return set()

    # Trích xuất link từ trang 1
    page_links = extract_article_links(soup, base_url, domain)
    if not page_links:
        print(f" → 0 link")
        return set()

    all_links.update(page_links)        # Thêm tất cả link vào tập kết quả
    prev_page_links = page_links        # Ghi nhớ link trang 1
    print(f" → {len(page_links)} link | Tổng: {len(all_links)}")

    # ---- PHÁT HIỆN MẪU PHÂN TRANG ----
    pagination_fn = detect_pagination_pattern(category_url)
    if pagination_fn is None:
        # Không tìm thấy mẫu → chỉ trả về link trang 1
        return all_links

    # ---- DUYỆT TRANG 2 TRỞ ĐI ----
    consecutive_failures = 0  # Đếm số lỗi liên tiếp

    for page in range(2, max_pages + 1):
        polite_sleep()  # Nghỉ 2-4 giây trước mỗi request

        # Tạo URL trang phân trang theo mẫu đã phát hiện
        try:
            page_url = pagination_fn(category_url, page)
        except Exception:
            break

        print(f"  📄 Trang {page}/{max_pages}", end="")
        soup = fetch_html(page_url, referer=category_url)

        # Xử lý lỗi tải trang
        if soup is None:
            consecutive_failures += 1
            print(f" → LỖI (liên tiếp: {consecutive_failures})")
            # Nếu 5 lỗi liên tiếp → dừng (tránh request vô ích)
            if consecutive_failures >= 5:
                print(f"  ✗ Quá nhiều lỗi → dừng")
                break
            continue

        # Trích xuất link từ trang hiện tại
        page_links = extract_article_links(soup, base_url, domain)

        # Kiểm tra: nếu trang không có link → đã hết bài
        if not page_links:
            print(f" → 0 link → HẾT BÀI")
            break

        # --- ANTI-LOOP ---
        # Nếu link trang này TRÙNG HOÀN TOÀN với trang trước → server trả lại cùng 1 trang
        # (nghĩa là trang không tồn tại, server redirect về trang cuối)
        if page_links == prev_page_links:
            print(f" → TRÙNG trang trước → DỪNG (Anti-Loop)")
            break

        # Reset bộ đếm lỗi (không còn lỗi liên tiếp)
        consecutive_failures = 0

        # Tính số link MỚI (chưa có trong tập kết quả)
        new_links = page_links - all_links
        all_links.update(page_links)
        prev_page_links = page_links

        print(f" → {len(page_links)} link ({len(new_links)} mới) | Tổng: {len(all_links)}")

        # Nếu không có link mới → đã cào hết bài mới → dừng
        if len(new_links) == 0:
            print(f"  ⚠ Không có link mới → dừng")
            break

    return all_links


# =============================================================================
# PHẦN 6: CÀO NỘI DUNG BÀI VIẾT — GENERIC (HOẠT ĐỘNG VỚI MỌI TRANG)
# =============================================================================

def generic_scrape_article(url):
    """
    Cào tiêu đề + nội dung từ BẤT KỲ trang báo nào (generic scraper).

    Đây là hàm CORE — thiết kế theo hướng "universal" (tổng quát):
    KHÔNG hardcode cấu trúc HTML của từng trang báo, mà dùng nhiều CSS selector
    phổ biến + fallback thông minh để hoạt động với trang chưa biết.

    === TRÍCH XUẤT TIÊU ĐỀ ===
    Thử 9 CSS selector theo thứ tự ưu tiên (từ cụ thể → chung):
        1. h1.detail-title          — Tuổi Trẻ
        2. h1.title-detail          — VnExpress
        3. h1.title_detail          — Biến thể
        4. h1.title-page            — Dân Trí (giao diện cũ)
        5. h1.dt-text-4xl           — Dân Trí (giao diện mới)
        6. h1.content-detail-title  — VietnamNet
        7. h1.article-title         — Phổ biến quốc tế
        8. h1[class*='title']       — Bất kỳ h1 nào có class chứa "title"
        9. h1                       — Fallback: bất kỳ thẻ h1 nào

    === TRÍCH XUẤT NỘI DUNG ===
    Thử 20+ CSS selector body bài viết + 2 fallback:
        Fallback 1: <article> chứa nhiều <p> nhất
        Fallback 2: <div> chứa nhiều <p> trực tiếp nhất (≥ 3 đoạn)

    === LOẠI BỎ NHIỄU ===
    Trước khi ghép đoạn văn, xóa các thẻ rác:
        script, style, figure, video, iframe, quảng cáo, tác giả,
        bài liên quan, nút chia sẻ, danh sách tag

    === KIỂM TRA CHẤT LƯỢNG ===
    Bỏ qua bài có nội dung < 50 ký tự (quá ngắn, có thể là lỗi)

    Tham số:
        url (str): URL bài viết cần cào

    Trả về:
        tuple: (title, content) — chuỗi tiêu đề và nội dung, hoặc (None, None) nếu thất bại
    """
    soup = fetch_html(url)
    if soup is None:
        return None, None

    try:
        # ===== TRÍCH XUẤT TIÊU ĐỀ =====
        title = None
        # Thử từng selector theo thứ tự ưu tiên (cụ thể → chung)
        for sel in [
            "h1.detail-title",             # Tuổi Trẻ (tuoitre.vn)
            "h1.title-detail",             # VnExpress (vnexpress.net)
            "h1.title_detail",             # Biến thể với dấu gạch dưới
            "h1.title-page",              # Dân Trí giao diện cũ
            "h1.dt-text-4xl",             # Dân Trí giao diện mới (2025+)
            "h1.content-detail-title",     # VietnamNet
            "h1.article-title",           # Chuẩn quốc tế (WordPress, ...)
            "h1[class*='title']",         # Bất kỳ h1 nào có class chứa "title"
            "h1",                         # Fallback cuối: bất kỳ <h1> nào
        ]:
            tag = soup.select_one(sel)  # Tìm thẻ đầu tiên khớp selector
            if tag and tag.get_text(strip=True):  # Kiểm tra tồn tại + có text
                title = tag.get_text(strip=True)   # Lấy text, bỏ khoảng trắng thừa
                break  # Tìm thấy → dừng, không cần thử selector tiếp

        # Không tìm thấy tiêu đề → bỏ qua bài này
        if not title:
            return None, None

        # ===== TRÍCH XUẤT NỘI DUNG BÀI VIẾT =====
        body = None  # Biến lưu thẻ HTML chứa nội dung bài viết

        # Thử 20+ CSS selector cho phần body bài viết
        for sel in [
            "article.fck_detail",          # Tuổi Trẻ (class FCKEditor)
            "div.detail-content",          # Phổ biến: Tuổi Trẻ, nhiều báo khác
            "div.detail-c",                # Biến thể viết tắt
            "div.dt-text-black-mine",      # Dân Trí giao diện mới
            "div.singular-content",        # Dân Trí giao diện cũ
            "div.maincontent",             # VietnamNet
            "div.content-detail",          # Biến thể
            "div.ArticleContent",          # Zing News (znews.vn)
            "div.article-content",         # Thanh Niên, chuẩn quốc tế
            "div.article-body",            # Chuẩn quốc tế
            "div.post-content",            # WordPress
            "div.entry-content",           # WordPress
            "div.news-content",            # Biến thể
            "div.story-content",           # Biến thể
            "div.the-article-body",        # Biến thể
            "article[class*='content']",   # <article> có class chứa "content"
            "[class*='article-body']",     # Bất kỳ thẻ nào có class chứa "article-body"
            "[class*='detail-content']",   # Bất kỳ thẻ nào có class chứa "detail-content"
            "[class*='content-detail']",   # Bất kỳ thẻ nào có class chứa "content-detail"
        ]:
            tag = soup.select_one(sel)
            if tag:
                body = tag
                break

        # --- FALLBACK 1: Tìm thẻ <article> chứa nhiều đoạn <p> nhất ---
        # Nếu không khớp selector nào → tìm tất cả <article> trong trang,
        # chọn thẻ <article> có số lượng <p> (đoạn văn) nhiều nhất.
        # Vì thẻ <article> chứa bài viết thường có rất nhiều đoạn <p>.
        if body is None:
            articles = soup.find_all("article")
            if articles:
                body = max(articles, key=lambda a: len(a.find_all("p")))

        # --- FALLBACK 2: Tìm <div> chứa nhiều <p> trực tiếp nhất ---
        # Trường hợp trang không dùng <article> → duyệt tất cả <div>,
        # đếm số <p> CON TRỰC TIẾP (recursive=False, chỉ đếm <p> là con cấp 1).
        # Chọn <div> có nhiều <p> nhất và yêu cầu ≥ 3 đoạn (tránh nhận nhầm sidebar).
        if body is None:
            best_div, max_p = None, 0
            for div in soup.find_all("div"):
                # recursive=False: chỉ đếm <p> là con trực tiếp của <div>,
                # không đếm <p> nằm sâu bên trong (tránh đếm trùng)
                p_count = len(div.find_all("p", recursive=False))
                if p_count > max_p:
                    max_p = p_count
                    best_div = div
            # Yêu cầu tối thiểu 3 đoạn <p> để chắc chắn đây là nội dung bài viết
            if max_p >= 3:
                body = best_div

        # Không tìm thấy nội dung → bỏ qua bài này
        if body is None:
            return None, None

        # ===== LOẠI BỎ CÁC THẺ RÁC (NOISE REMOVAL) =====
        # Trước khi ghép đoạn văn, cần xóa các thẻ không mong muốn:
        #   - script, style: mã JavaScript / CSS
        #   - figure, video, iframe: hình ảnh, video nhúng
        #   - noscript: nội dung cho trình duyệt không hỗ trợ JS
        #   - .fig-picture, .image, .caption, .photo: hình ảnh và chú thích
        #   - .author, .detail-author, ...: thông tin tác giả
        #   - .relate-container, .related, ...: bài viết liên quan
        #   - .advertisement, .ads: quảng cáo
        #   - .social-share, .share: nút chia sẻ mạng xã hội
        #   - .tags, .tag-list: danh sách tag
        for tag in body.select(
            "script, style, figure, video, iframe, noscript, "
            ".fig-picture, .image, .caption, .photo, "
            ".author, .author-info, .detail-author, .article-author, "
            ".author-name, .singular-author, "
            ".relate-container, .related, .box-tinlienquan, "
            ".advertisement, .ads, [class*='advert'], "
            ".social-share, .share, .tags, .tag-list"
        ):
            tag.decompose()  # decompose(): xóa hoàn toàn thẻ + nội dung khỏi cây DOM

        # ===== GHÉP CÁC ĐOẠN VĂN THÀNH NỘI DUNG =====
        # Tìm tất cả thẻ <p> còn lại trong body → lấy text → ghép bằng dấu cách
        # Bỏ qua các <p> rỗng (không có nội dung sau khi strip)
        content = " ".join(
            p.get_text(strip=True) for p in body.find_all("p") if p.get_text(strip=True)
        )

        # Kiểm tra chất lượng: nội dung rỗng hoặc quá ngắn (< 50 ký tự) → bỏ qua
        if not content or len(content) < 50:
            return None, None

        # Trả về tiêu đề + nội dung
        return title, content

    except Exception as e:
        # Bắt mọi lỗi không mong muốn (HTML lỗi, encoding, ...) → in lỗi, trả None
        print(f"  [LỖI PARSE] {url} — {e}")
        return None, None


# =============================================================================
# PHẦN 7: CÀO MỘT CHUYÊN MỤC (ORCHESTRATOR)
# =============================================================================

def scrape_category(label, category_url, domain, site_name, output_file,
                    max_pages=50, max_workers=3):
    """
    Cào toàn bộ bài viết của 1 chuyên mục.

    Đây là hàm "điều phối" (orchestrator) — kết hợp các bước:
        1. Thu thập tất cả link bài viết (collect_links)
        2. Cào nội dung từng bài đa luồng (generic_scrape_article)
        3. Ghi kết quả vào CSV (append_row)

    Đa luồng (Multi-threading):
        - Sử dụng ThreadPoolExecutor với max_workers luồng chạy song song
        - Mỗi luồng: nghỉ → cào 1 bài → ghi CSV (thread-safe)
        - In tiến trình mỗi 20 bài hoặc khi hoàn tất

    Tham số:
        label (str): Nhãn chuyên mục (ví dụ: "Thể thao")
        category_url (str): URL chuyên mục
        domain (str): Domain trang báo
        site_name (str): Tên trang báo (ví dụ: "Tuoitre")
        output_file (str): Đường dẫn file CSV đầu ra
        max_pages (int): Số trang phân trang tối đa (mặc định = 50)
        max_workers (int): Số luồng chạy song song (mặc định = 3)

    Trả về:
        int: Số bài viết cào thành công
    """
    # In thông tin chuyên mục đang cào
    print(f"\n{'='*60}")
    print(f"  ▶ [{site_name}] Chuyên mục: {label}")
    print(f"    URL: {category_url}")
    print(f"{'='*60}")

    # Bước 1: Thu thập tất cả link bài viết từ chuyên mục
    article_urls = collect_links(category_url, domain, max_pages)
    print(f"\n  → Tổng link duy nhất: {len(article_urls)}")

    if not article_urls:
        print(f"  [!] Không tìm thấy bài nào")
        return 0

    success = 0      # Đếm số bài cào thành công
    total = len(article_urls)

    def process(url):
        """
        Hàm xử lý 1 bài viết (chạy trong 1 luồng riêng).
        Nghỉ → cào tiêu đề + nội dung → ghi vào CSV.
        """
        polite_sleep()  # Nghỉ ngẫu nhiên 2-4 giây (chống bị chặn)
        title, content = generic_scrape_article(url)
        if title and content:
            # Ghi 1 dòng vào CSV: [url, nhãn, tiêu đề, nội dung, nguồn]
            append_row(output_file, [url, label, title, content, site_name])
            return True   # Cào thành công
        return False      # Thất bại (không lấy được tiêu đề hoặc nội dung)

    # Bước 2: Cào đa luồng bằng ThreadPoolExecutor
    # ThreadPoolExecutor quản lý 1 nhóm luồng (thread pool), mỗi luồng xử lý 1 bài
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # submit(): gửi tác vụ vào pool → trả về Future (đại diện kết quả tương lai)
        # Tạo dict {Future: url} để tra ngược khi cần in lỗi
        futures = {executor.submit(process, u): u for u in article_urls}

        # as_completed(): trả về Future khi chúng HOÀN THÀNH (không theo thứ tự submit)
        for i, future in enumerate(as_completed(futures), 1):
            try:
                if future.result():  # .result() lấy giá trị trả về của hàm process()
                    success += 1
                # In tiến trình mỗi 20 bài hoặc khi hoàn tất tất cả
                if i % 20 == 0 or i == total:
                    print(f"  📰 [{site_name} | {label}] {i}/{total} | OK: {success}")
            except Exception as e:
                print(f"  [LỖI] {futures[future]} — {e}")

    print(f"\n  ✓ Hoàn tất [{site_name} | {label}]: {success}/{total} bài")
    return success


# =============================================================================
# PHẦN 8: HÀM CHÍNH (MAIN) — GIAO DIỆN NGƯỜI DÙNG
# =============================================================================

def print_banner():
    """In banner chào mừng khi khởi chạy script."""
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║   UNIVERSAL NEWS SCRAPER — CÀO BẤT KỲ TRANG BÁO NÀO      ║")
    print("║   Nhập link → tự phát hiện chuyên mục → tự cào bài viết   ║")
    print("║                                                            ║")
    print("║   Ví dụ: tuoitre.vn, dantri.com.vn, znews.vn,             ║")
    print("║          thanhnien.vn, vietnamnet.vn, vnexpress.net, ...   ║")
    print("╚══════════════════════════════════════════════════════════════╝")


def parse_input_url(raw):
    """
    Chuẩn hóa URL do người dùng nhập.

    Người dùng có thể nhập không đầy đủ:
        "tuoitre.vn"           → "https://tuoitre.vn"
        "https://tuoitre.vn/"  → "https://tuoitre.vn"  (bỏ dấu / cuối)
        "  znews.vn  "         → "https://znews.vn"  (bỏ khoảng trắng)

    Tham số:
        raw (str): Chuỗi URL thô do người dùng nhập

    Trả về:
        str: URL đã chuẩn hóa (có https://, không có / cuối)
    """
    raw = raw.strip().rstrip("/")           # Bỏ khoảng trắng + dấu / cuối
    if not raw.startswith("http"):          # Nếu thiếu scheme (http/https)
        raw = "https://" + raw              # Tự thêm https://
    return raw


def main():
    """
    Hàm chính — điều khiển toàn bộ quy trình cào dữ liệu.

    Quy trình:
        1. Hiển thị banner chào mừng
        2. Nhận input: URL trang báo (có thể nhiều, cách bằng dấu phẩy)
        3. Với mỗi trang báo:
           a. Quét trang chủ → phát hiện chuyên mục
           b. Hiển thị danh sách chuyên mục → cho người dùng chọn
        4. Hiển thị kế hoạch cào (tổng hợp)
        5. Xác nhận → bắt đầu cào
        6. Với mỗi chuyên mục: gọi scrape_category()
        7. In kết quả tổng kết
    """
    # Bước 1: Hiển thị giao diện
    print_banner()

    print("\n  Nhập link trang báo cần cào (phân cách bằng dấu phẩy).")
    print("  Ví dụ: tuoitre.vn, znews.vn, dantri.com.vn")

    # Bước 2: Nhận input từ người dùng (lặp cho đến khi nhập gì đó)
    while True:
        user_input = input("\n👉 Nhập link trang báo: ").strip()
        if user_input:
            break

    # Phân tách input thành danh sách URL
    # "tuoitre.vn, znews.vn" → ["tuoitre.vn", "znews.vn"]
    raw_urls = [u.strip() for u in user_input.split(",") if u.strip()]

    # Chuẩn hóa mỗi URL và tạo thông tin site
    sites = []
    for raw in raw_urls:
        url = parse_input_url(raw)                     # Chuẩn hóa URL
        domain = get_domain(url)                       # Lấy domain: "tuoitre.vn"
        name = domain.split(".")[0].capitalize()        # Lấy tên: "Tuoitre"
        sites.append({"url": url, "domain": domain, "name": name})

    # Bước 3: Phát hiện chuyên mục cho từng trang báo
    scrape_plan = []  # Kế hoạch cào: danh sách {name, domain, url, categories}

    for site in sites:
        # Quét trang chủ → tìm chuyên mục
        categories = discover_categories(site["url"])

        if not categories:
            # Không tìm thấy chuyên mục → hỏi người dùng có bỏ qua không
            print(f"  [!] Không tìm thấy chuyên mục nào tại {site['url']}")
            choice = input(f"      Bỏ qua? (y/n): ").strip().lower()
            if choice in ("y", "yes", ""):
                continue

        # Thêm vào kế hoạch cào
        scrape_plan.append({
            "name": site["name"],
            "domain": site["domain"],
            "url": site["url"],
            "categories": categories,
        })

    # Nếu không có trang báo nào → thoát
    if not scrape_plan:
        print("\n  ❌ Không có trang báo nào để cào.")
        return

    # Bước 4: Cho người dùng chọn chuyên mục cần cào
    for plan in scrape_plan:
        cats = plan["categories"]
        if not cats:
            continue

        # Hiển thị danh sách chuyên mục có đánh số
        cat_list = list(cats.keys())
        print(f"\n  [{plan['name']}] Các chuyên mục tìm thấy:")
        for i, label in enumerate(cat_list, 1):
            print(f"    {i:2d}. {label}")
        print(f"    {len(cat_list)+1:2d}. ✅ Giữ tất cả")

        # Nhận lựa chọn: số (cách dấu phẩy), hoặc Enter = tất cả
        choice = input(f"  👉 Chọn (số, phân cách dấu phẩy, Enter = tất cả): ").strip()
        if choice and choice != str(len(cat_list) + 1):
            try:
                # Parse danh sách số: "1,3,5" → [1, 3, 5]
                indices = [int(x.strip()) for x in choice.split(",")]
                selected = {}
                for idx in indices:
                    if 1 <= idx <= len(cat_list):       # Kiểm tra index hợp lệ
                        label = cat_list[idx - 1]       # Lấy nhãn tương ứng
                        selected[label] = cats[label]   # Thêm vào danh sách chọn
                if selected:
                    plan["categories"] = selected       # Thay thế danh sách chuyên mục
            except ValueError:
                pass  # Nhập sai định dạng → giữ tất cả

    # Bước 5: Hiển thị kế hoạch cào tổng hợp
    total_tasks = sum(len(p["categories"]) for p in scrape_plan)
    print(f"\n{'='*60}")
    print(f"  📋 KẾ HOẠCH CÀO DỮ LIỆU")
    print(f"{'='*60}")
    for plan in scrape_plan:
        print(f"  [{plan['name']}] ({plan['domain']}) — {len(plan['categories'])} chuyên mục:")
        for label in plan["categories"]:
            print(f"    ✓ {label}")
    print(f"  Tổng: {total_tasks} chuyên mục")
    print(f"  File đầu ra: dataset_all_news.csv")
    print(f"{'='*60}")

    # Xác nhận từ người dùng trước khi cào
    confirm = input("\n👉 Bắt đầu cào? (y/n): ").strip().lower()
    if confirm not in ("y", "yes", ""):
        print("  ❌ Đã hủy.")
        return

    # Bước 6: Khởi tạo file CSV đầu ra
    output_file = "dataset_all_news.csv"
    init_csv(output_file)

    # Bước 7: Thực hiện cào từng chuyên mục
    total_success = 0     # Tổng số bài cào thành công
    t0 = time.time()      # Ghi nhận thời gian bắt đầu
    task_num = 0           # Đếm task hiện tại

    for plan in scrape_plan:
        for label, category_url in plan["categories"].items():
            task_num += 1
            print(f"\n{'─'*60}")
            print(f"  📌 Task {task_num}/{total_tasks}")
            print(f"{'─'*60}")

            # Gọi hàm cào chuyên mục — trả về số bài thành công
            count = scrape_category(
                label, category_url, plan["domain"], plan["name"],
                output_file, max_pages=50, max_workers=3,
            )
            total_success += count

    # Bước 8: In kết quả tổng kết
    elapsed = time.time() - t0                          # Tính thời gian đã trôi qua
    m, s = int(elapsed // 60), int(elapsed % 60)        # Chuyển thành phút:giây

    print(f"\n{'='*60}")
    print(f"  🏁 HOÀN TẤT!")
    print(f"{'='*60}")
    print(f"  Tổng bài đã lưu : {total_success}")
    print(f"  Thời gian        : {m} phút {s} giây")
    print(f"  File đầu ra      : {output_file}")
    print(f"{'='*60}")


# =============================================================================
# ĐIỂM KHỞI CHẠY (ENTRY POINT)
# =============================================================================
# Dòng này đảm bảo hàm main() chỉ chạy khi file được thực thi trực tiếp:
#   python scrape_all.py  → __name__ == "__main__" → chạy main()
#
# Nếu file được import từ file khác:
#   import scrape_all     → __name__ == "scrape_all" → KHÔNG chạy main()
#   (cho phép sử dụng các hàm riêng lẻ mà không kích hoạt toàn bộ script)
if __name__ == "__main__":
    main()
