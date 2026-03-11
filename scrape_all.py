"""
UNIVERSAL NEWS SCRAPER - Cào dữ liệu tin tức từ bất kỳ trang báo Việt Nam nào.

Cách dùng:
    python scrape_all.py
    → Nhập URL trang báo (vd: tuoitre.vn, znews.vn)
    → Script tự quét chuyên mục, cào bài viết, lưu CSV
"""

# ========================= IMPORT =========================

import csv
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


# ========================= CẤU HÌNH =========================

# Danh sách User-Agent xoay vòng để tránh bị chặn
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# Lock đồng bộ ghi file CSV khi đa luồng
csv_lock = threading.Lock()

# Ánh xạ slug URL → nhãn tiếng Việt chuẩn
KNOWN_CATEGORY_SLUGS = {
    "the-thao": "Thể thao",
    "bong-da": "Thể thao",
    "kinh-doanh": "Kinh doanh",
    "kinh-te": "Kinh doanh",
    "tai-chinh": "Kinh doanh",
    "bat-dong-san": "Kinh doanh",
    "giao-duc": "Giáo dục",
    "tuyen-sinh": "Giáo dục",
    "du-hoc": "Giáo dục",
    "giai-tri": "Giải trí",
    "sao": "Giải trí",
    "am-nhac": "Giải trí",
    "phim": "Giải trí",
    "suc-khoe": "Sức khỏe",
    "doi-song": "Đời sống",
    "the-gioi": "Thế giới",
    "quoc-te": "Thế giới",
    "phap-luat": "Pháp luật",
    "an-ninh-hinh-su": "Pháp luật",
    "du-lich": "Du lịch",
    "khoa-hoc": "Khoa học",
    "cong-nghe": "Công nghệ",
    "so-hoa": "Công nghệ",
    "van-hoa": "Văn hóa",
    "thoi-su": "Thời sự",
    "chinh-tri": "Thời sự",
    "xa-hoi": "Xã hội",
    "oto-xe-may": "Xe",
    "xe": "Xe",
    "nhip-song-tre": "Nhịp sống trẻ",
    "tam-su": "Đời sống",
    "gia-dinh": "Đời sống",
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

# Các đường dẫn bỏ qua (không phải chuyên mục tin tức)
SKIP_PATHS = {
    "lien-he", "contact", "about", "gioi-thieu", "quang-cao",
    "dieu-khoan", "chinh-sach-bao-mat", "tuyen-dung", "rss", "sitemap",
    "video", "podcast", "infographic", "photo", "anh", "multimedia",
    "login", "dang-nhap", "dang-ky", "register", "search", "tim-kiem",
    "tag", "tags", "author", "tac-gia", "page", "trang",
    "thu-vien", "brand-voice", "megastory", "longform", "special",
    "english", "e-paper", "e-magazine",
}

# Các mẫu phân trang phổ biến (thử lần lượt để tìm mẫu đúng)
PAGINATION_PATTERNS = [
    # Tuổi Trẻ: /the-thao/trang-2.htm
    lambda base, page: (
        base.replace(".htm", "") + f"/trang-{page}.htm"
        if ".htm" in base
        else base.rstrip("/") + f"/trang-{page}.htm"
    ),
    # Dân Trí: /the-thao/trang-2.htm
    lambda base, page: base.rstrip("/") + f"/trang-{page}.htm",
    # VnExpress: /the-thao-p2
    lambda base, page: base.rstrip("/") + f"-p{page}",
    # VietnamNet: /the-thao-page2
    lambda base, page: base.rstrip("/") + f"-page{page}",
    # Zing/Thanh Niên: /the-thao?page=2
    lambda base, page: base.rstrip("/") + f"?page={page}",
    # WordPress: /the-thao/page/2
    lambda base, page: base.rstrip("/") + f"/page/{page}",
]


# ========================= HÀM TIỆN ÍCH =========================

def get_headers(referer=None):
    """Tạo HTTP headers giả lập trình duyệt."""
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def polite_sleep(min_sec=2, max_sec=4):
    """Nghỉ ngẫu nhiên giữa các request để tránh bị chặn."""
    time.sleep(random.uniform(min_sec, max_sec))


def fetch_html(url, retries=3, referer=None):
    """Tải trang web → trả về BeautifulSoup, None nếu thất bại. Có cơ chế retry."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=get_headers(referer), timeout=20)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            if attempt < retries:
                time.sleep(attempt * 3)
            else:
                print(f"  [LỖI] {url} — {e}")
    return None


def normalize_url(base_url, href):
    """Chuyển URL tương đối → tuyệt đối. Lọc bỏ javascript, anchor, mailto."""
    if not href:
        return None
    href = href.strip()
    if href.startswith(("javascript:", "#", "mailto:")):
        return None
    return urljoin(base_url, href)


def get_domain(url):
    """Trích xuất domain từ URL, bỏ 'www.'."""
    return urlparse(url).netloc.replace("www.", "")


def get_base_url(url):
    """Lấy phần gốc URL (scheme + domain)."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def init_csv(filepath):
    """Tạo file CSV với header nếu chưa tồn tại."""
    if not os.path.exists(filepath):
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(["url", "label", "title", "content", "source"])
        print(f"[INFO] Đã tạo file: {filepath}")
    else:
        print(f"[INFO] File đã tồn tại, append vào: {filepath}")


def append_row(filepath, row):
    """Thêm 1 dòng vào CSV (thread-safe với Lock)."""
    with csv_lock:
        with open(filepath, "a", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(row)


# ========================= PHÁT HIỆN CHUYÊN MỤC =========================

def slug_to_label(slug):
    """Chuyển slug URL → nhãn tiếng Việt. Tra bảng hoặc tự capitalize."""
    slug_clean = slug.strip("/").lower()
    if slug_clean in KNOWN_CATEGORY_SLUGS:
        return KNOWN_CATEGORY_SLUGS[slug_clean]
    words = slug_clean.replace("-", " ").split()
    return " ".join(w.capitalize() for w in words)


def is_category_path(path):
    """Kiểm tra path có phải chuyên mục: 1 segment, không trong SKIP_PATHS, không chứa ID."""
    path = path.strip("/")
    path_clean = re.sub(r'\.(htm|html)$', '', path)
    if not path_clean:
        return False

    segments = path_clean.split("/")
    if len(segments) > 1:
        return False

    slug = segments[0]
    if slug.lower() in SKIP_PATHS:
        return False
    if re.search(r'\d{3,}', slug):
        return False
    if len(slug) < 2 or len(slug) > 35:
        return False
    return True


def discover_categories(homepage_url):
    """Quét trang chủ → phát hiện chuyên mục tự động. Trả về dict {label: url}."""
    domain = get_domain(homepage_url)
    base = get_base_url(homepage_url)

    print(f"\n  🔍 Đang quét trang chủ: {homepage_url}")
    soup = fetch_html(homepage_url, referer=homepage_url)
    if soup is None:
        print(f"  [LỖI] Không thể truy cập {homepage_url}")
        return {}

    # Tìm link trong vùng nav/menu bằng nhiều CSS selector
    nav_selectors = [
        "nav a[href]", "header a[href]",
        "ul.menu a[href]", "ul.nav a[href]", "ul.main-nav a[href]",
        ".main-menu a[href]", ".navigation a[href]", ".nav-menu a[href]",
        ".header-menu a[href]", ".top-menu a[href]",
        "[class*='menu'] a[href]", "[class*='nav'] a[href]",
    ]

    candidate_links = []
    for selector in nav_selectors:
        candidate_links.extend(soup.select(selector))

    # Fallback: quét tất cả link nếu không tìm thấy nav
    if not candidate_links:
        candidate_links = soup.find_all("a", href=True)

    # Lọc và phân loại thành chuyên mục
    categories = {}
    seen_labels = set()

    for a_tag in candidate_links:
        href = a_tag.get("href", "")
        full_url = normalize_url(base, href)
        if not full_url:
            continue

        link_domain = get_domain(full_url)
        if domain not in link_domain and link_domain not in domain:
            continue

        parsed = urlparse(full_url)
        if not is_category_path(parsed.path):
            continue

        slug = parsed.path.strip("/").split("/")[0]
        slug = re.sub(r'\.(htm|html)$', '', slug)
        label = slug_to_label(slug)

        if label in seen_labels:
            continue
        seen_labels.add(label)

        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        categories[label] = clean_url

    print(f"  ✓ Tìm thấy {len(categories)} chuyên mục")
    for label, url in categories.items():
        print(f"    • {label}: {url}")

    return categories


# ========================= PHÁT HIỆN PHÂN TRANG =========================

def detect_pagination_pattern(category_url):
    """Thử 6 mẫu phân trang trên trang 2. Trả về mẫu đúng hoặc None."""
    print(f"  🔎 Đang dò mẫu phân trang...", end="")

    for i, pattern_fn in enumerate(PAGINATION_PATTERNS):
        try:
            test_url = pattern_fn(category_url, 2)
            resp = requests.get(test_url, headers=get_headers(category_url), timeout=15)
            if resp.status_code == 200 and len(resp.text) > 5000:
                print(f" mẫu #{i+1} OK")
                return pattern_fn
        except Exception:
            continue

    print(f" không tìm thấy → chỉ cào trang 1")
    return None


# ========================= THU THẬP LINK BÀI VIẾT =========================

def is_article_url(href, domain):
    """Kiểm tra URL có phải bài viết không (heuristic: cùng domain, slug dài, nhiều dấu '-')."""
    if not href:
        return False

    link_domain = get_domain(href)
    if domain not in link_domain and link_domain not in domain:
        return False

    parsed = urlparse(href)
    path = parsed.path.strip("/")
    if not path:
        return False

    path_lower = path.lower()
    for skip in ["video", "photo", "infographic", "podcast", "/anh/", "multimedia"]:
        if skip in path_lower:
            return False

    if re.search(r'(trang-|/page/|-page\d|-p\d)', path_lower):
        return False

    segments = path.split("/")
    last_segment = segments[-1]
    last_clean = re.sub(r'\.(htm|html)$', '', last_segment)

    # Slug có ≥ 3 dấu '-' → bài viết
    if last_clean.count("-") >= 3:
        return True
    # ≥ 2 segment + slug dài
    if len(segments) >= 2 and len(last_clean) > 15:
        return True
    # Đuôi .htm/.html + ≥ 2 dấu '-'
    if (path.endswith(".htm") or path.endswith(".html")) and last_clean.count("-") >= 2:
        return True

    return False


def extract_article_links(soup, base_url, domain):
    """Trích xuất link bài viết từ trang danh sách. Ưu tiên thẻ article/h2/h3, fallback quét tất cả."""
    links = set()

    for sel in [
        "article a[href]", "h2 a[href]", "h3 a[href]",
        ".article-item a[href]", ".news-item a[href]",
        "[class*='article'] a[href]", "[class*='title'] a[href]",
    ]:
        for a_tag in soup.select(sel):
            full = normalize_url(base_url, a_tag.get("href", ""))
            if full and is_article_url(full, domain):
                links.add(full)

    # Fallback nếu tìm ít link
    if len(links) < 5:
        for a_tag in soup.find_all("a", href=True):
            full = normalize_url(base_url, a_tag["href"])
            if full and is_article_url(full, domain):
                links.add(full)

    return links


def collect_links(category_url, domain, max_pages=50):
    """Thu thập link bài viết từ chuyên mục qua nhiều trang phân trang."""
    base_url = get_base_url(category_url)
    all_links = set()
    prev_page_links = set()

    # Trang 1
    print(f"  📄 Trang 1/{max_pages}", end="")
    soup = fetch_html(category_url, referer=base_url)
    if soup is None:
        print(f" → LỖI")
        return set()

    page_links = extract_article_links(soup, base_url, domain)
    if not page_links:
        print(f" → 0 link")
        return set()

    all_links.update(page_links)
    prev_page_links = page_links
    print(f" → {len(page_links)} link | Tổng: {len(all_links)}")

    # Phát hiện mẫu phân trang
    pagination_fn = detect_pagination_pattern(category_url)
    if pagination_fn is None:
        return all_links

    # Duyệt trang 2 trở đi
    consecutive_failures = 0

    for page in range(2, max_pages + 1):
        polite_sleep()

        try:
            page_url = pagination_fn(category_url, page)
        except Exception:
            break

        print(f"  📄 Trang {page}/{max_pages}", end="")
        soup = fetch_html(page_url, referer=category_url)

        if soup is None:
            consecutive_failures += 1
            print(f" → LỖI (liên tiếp: {consecutive_failures})")
            if consecutive_failures >= 5:
                print(f"  ✗ Quá nhiều lỗi → dừng")
                break
            continue

        page_links = extract_article_links(soup, base_url, domain)

        if not page_links:
            print(f" → 0 link → HẾT BÀI")
            break

        # Anti-loop: trùng trang trước → dừng
        if page_links == prev_page_links:
            print(f" → TRÙNG trang trước → DỪNG (Anti-Loop)")
            break

        consecutive_failures = 0
        new_links = page_links - all_links
        all_links.update(page_links)
        prev_page_links = page_links

        print(f" → {len(page_links)} link ({len(new_links)} mới) | Tổng: {len(all_links)}")

        if len(new_links) == 0:
            print(f"  ⚠ Không có link mới → dừng")
            break

    return all_links


# ========================= CÀO NỘI DUNG BÀI VIẾT =========================

def generic_scrape_article(url):
    """Cào tiêu đề + nội dung bài viết từ bất kỳ trang báo nào. Trả về (title, content) hoặc (None, None)."""
    soup = fetch_html(url)
    if soup is None:
        return None, None

    try:
        # Trích xuất tiêu đề (thử nhiều selector phổ biến)
        title = None
        for sel in [
            "h1.detail-title", "h1.title-detail", "h1.title_detail",
            "h1.title-page", "h1.dt-text-4xl", "h1.content-detail-title",
            "h1.article-title", "h1[class*='title']", "h1",
        ]:
            tag = soup.select_one(sel)
            if tag and tag.get_text(strip=True):
                title = tag.get_text(strip=True)
                break

        if not title:
            return None, None

        # Trích xuất nội dung (thử nhiều selector phổ biến)
        body = None
        for sel in [
            "article.fck_detail", "div.detail-content", "div.detail-c",
            "div.dt-text-black-mine", "div.singular-content", "div.maincontent",
            "div.content-detail", "div.ArticleContent", "div.article-content",
            "div.article-body", "div.post-content", "div.entry-content",
            "div.news-content", "div.story-content", "div.the-article-body",
            "article[class*='content']", "[class*='article-body']",
            "[class*='detail-content']", "[class*='content-detail']",
        ]:
            tag = soup.select_one(sel)
            if tag:
                body = tag
                break

        # Fallback 1: <article> chứa nhiều <p> nhất
        if body is None:
            articles = soup.find_all("article")
            if articles:
                body = max(articles, key=lambda a: len(a.find_all("p")))

        # Fallback 2: <div> chứa nhiều <p> trực tiếp nhất (≥ 3)
        if body is None:
            best_div, max_p = None, 0
            for div in soup.find_all("div"):
                p_count = len(div.find_all("p", recursive=False))
                if p_count > max_p:
                    max_p = p_count
                    best_div = div
            if max_p >= 3:
                body = best_div

        if body is None:
            return None, None

        # Loại bỏ thẻ rác (script, quảng cáo, tác giả, bài liên quan, ...)
        for tag in body.select(
            "script, style, figure, video, iframe, noscript, "
            ".fig-picture, .image, .caption, .photo, "
            ".author, .author-info, .detail-author, .article-author, "
            ".author-name, .singular-author, "
            ".relate-container, .related, .box-tinlienquan, "
            ".advertisement, .ads, [class*='advert'], "
            ".social-share, .share, .tags, .tag-list"
        ):
            tag.decompose()

        # Ghép các đoạn <p> thành nội dung
        content = " ".join(
            p.get_text(strip=True) for p in body.find_all("p") if p.get_text(strip=True)
        )

        if not content or len(content) < 50:
            return None, None

        return title, content

    except Exception as e:
        print(f"  [LỖI PARSE] {url} — {e}")
        return None, None


# ========================= CÀO CHUYÊN MỤC =========================

def scrape_category(label, category_url, domain, site_name, output_file,
                    max_pages=50, max_workers=3):
    """Cào toàn bộ bài viết 1 chuyên mục: thu thập link → cào đa luồng → ghi CSV."""
    print(f"\n{'='*60}")
    print(f"  ▶ [{site_name}] Chuyên mục: {label}")
    print(f"    URL: {category_url}")
    print(f"{'='*60}")

    article_urls = collect_links(category_url, domain, max_pages)
    print(f"\n  → Tổng link duy nhất: {len(article_urls)}")

    if not article_urls:
        print(f"  [!] Không tìm thấy bài nào")
        return 0

    success = 0
    total = len(article_urls)

    def process(url):
        """Xử lý 1 bài: nghỉ → cào → ghi CSV."""
        polite_sleep()
        title, content = generic_scrape_article(url)
        if title and content:
            append_row(output_file, [url, label, title, content, site_name])
            return True
        return False

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process, u): u for u in article_urls}
        for i, future in enumerate(as_completed(futures), 1):
            try:
                if future.result():
                    success += 1
                if i % 20 == 0 or i == total:
                    print(f"  📰 [{site_name} | {label}] {i}/{total} | OK: {success}")
            except Exception as e:
                print(f"  [LỖI] {futures[future]} — {e}")

    print(f"\n  ✓ Hoàn tất [{site_name} | {label}]: {success}/{total} bài")
    return success


# ========================= HÀM CHÍNH =========================

def print_banner():
    """In banner chào mừng."""
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║   UNIVERSAL NEWS SCRAPER — CÀO BẤT KỲ TRANG BÁO NÀO      ║")
    print("║   Nhập link → tự phát hiện chuyên mục → tự cào bài viết   ║")
    print("║                                                            ║")
    print("║   Ví dụ: tuoitre.vn, dantri.com.vn, znews.vn,             ║")
    print("║          thanhnien.vn, vietnamnet.vn, vnexpress.net, ...   ║")
    print("╚══════════════════════════════════════════════════════════════╝")


def parse_input_url(raw):
    """Chuẩn hóa URL: thêm https:// nếu thiếu, bỏ khoảng trắng và '/' cuối."""
    raw = raw.strip().rstrip("/")
    if not raw.startswith("http"):
        raw = "https://" + raw
    return raw


def main():
    """Hàm chính: nhận URL → phát hiện chuyên mục → cho chọn → cào → lưu CSV."""
    print_banner()

    print("\n  Nhập link trang báo cần cào (phân cách bằng dấu phẩy).")
    print("  Ví dụ: tuoitre.vn, znews.vn, dantri.com.vn")

    while True:
        user_input = input("\n👉 Nhập link trang báo: ").strip()
        if user_input:
            break

    raw_urls = [u.strip() for u in user_input.split(",") if u.strip()]

    sites = []
    for raw in raw_urls:
        url = parse_input_url(raw)
        domain = get_domain(url)
        name = domain.split(".")[0].capitalize()
        sites.append({"url": url, "domain": domain, "name": name})

    # Phát hiện chuyên mục
    scrape_plan = []

    for site in sites:
        categories = discover_categories(site["url"])

        if not categories:
            print(f"  [!] Không tìm thấy chuyên mục nào tại {site['url']}")
            choice = input(f"      Bỏ qua? (y/n): ").strip().lower()
            if choice in ("y", "yes", ""):
                continue

        scrape_plan.append({
            "name": site["name"],
            "domain": site["domain"],
            "url": site["url"],
            "categories": categories,
        })

    if not scrape_plan:
        print("\n  ❌ Không có trang báo nào để cào.")
        return

    # Cho người dùng chọn chuyên mục
    for plan in scrape_plan:
        cats = plan["categories"]
        if not cats:
            continue

        cat_list = list(cats.keys())
        print(f"\n  [{plan['name']}] Các chuyên mục tìm thấy:")
        for i, label in enumerate(cat_list, 1):
            print(f"    {i:2d}. {label}")
        print(f"    {len(cat_list)+1:2d}. ✅ Giữ tất cả")

        choice = input(f"  👉 Chọn (số, phân cách dấu phẩy, Enter = tất cả): ").strip()
        if choice and choice != str(len(cat_list) + 1):
            try:
                indices = [int(x.strip()) for x in choice.split(",")]
                selected = {}
                for idx in indices:
                    if 1 <= idx <= len(cat_list):
                        label = cat_list[idx - 1]
                        selected[label] = cats[label]
                if selected:
                    plan["categories"] = selected
            except ValueError:
                pass

    # Hiển thị kế hoạch cào
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

    confirm = input("\n👉 Bắt đầu cào? (y/n): ").strip().lower()
    if confirm not in ("y", "yes", ""):
        print("  ❌ Đã hủy.")
        return

    # Bắt đầu cào
    output_file = "dataset_all_news.csv"
    init_csv(output_file)

    total_success = 0
    t0 = time.time()
    task_num = 0

    for plan in scrape_plan:
        for label, category_url in plan["categories"].items():
            task_num += 1
            print(f"\n{'─'*60}")
            print(f"  📌 Task {task_num}/{total_tasks}")
            print(f"{'─'*60}")

            count = scrape_category(
                label, category_url, plan["domain"], plan["name"],
                output_file, max_pages=50, max_workers=3,
            )
            total_success += count

    # Tổng kết
    elapsed = time.time() - t0
    m, s = int(elapsed // 60), int(elapsed % 60)

    print(f"\n{'='*60}")
    print(f"  🏁 HOÀN TẤT!")
    print(f"{'='*60}")
    print(f"  Tổng bài đã lưu : {total_success}")
    print(f"  Thời gian        : {m} phút {s} giây")
    print(f"  File đầu ra      : {output_file}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
