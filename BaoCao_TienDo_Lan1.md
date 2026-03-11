# BÁO CÁO TIẾN ĐỘ LẦN 1

## Đề tài: Mô Hình Phân Loại Chủ Đề Tin Tức Tiếng Việt

---

## 1. Xác định phạm vi đề tài và phương pháp thu thập dữ liệu

### 1.1. Phạm vi đề tài

Đề tài tập trung xây dựng mô hình **Phân loại chủ đề tin tức tiếng Việt** — một bài toán thuộc lĩnh vực **Xử lý ngôn ngữ tự nhiên (NLP)** kết hợp với **Học máy (Machine Learning)**. Cụ thể:

- **Đầu vào**: Nội dung bài báo tiếng Việt (text).
- **Đầu ra**: Chủ đề / chuyên mục tương ứng của bài báo (ví dụ: Thể thao, Kinh doanh, Giáo dục, Sức khỏe, Giải trí, Thế giới, Pháp luật, ...).
- **Nguồn dữ liệu**: **Bất kỳ trang báo điện tử Việt Nam** — chỉ cần nhập URL trang chủ, hệ thống tự động phát hiện chuyên mục và thu thập bài viết. Ví dụ: `tuoitre.vn`, `dantri.com.vn`, `vietnamnet.vn`, `vnexpress.net`, `znews.vn`, `thanhnien.vn`, ...
- **Các chuyên mục cần phân loại**: Thể thao, Kinh doanh, Giáo dục, Giải trí, Sức khỏe, Thế giới, Pháp luật, Du lịch, Khoa học, Công nghệ, Văn hóa, Nhịp sống trẻ, Đời sống, Xe, v.v.

### 1.2. Phương pháp thu thập dữ liệu (Web Scraping)

Dữ liệu được thu thập tự động bằng kỹ thuật **Web Scraping** sử dụng ngôn ngữ **Python** thông qua một script duy nhất: **`scrape_all.py`** — Universal News Scraper. Script được thiết kế theo hướng **tổng quát (generic)**, có khả năng cào bài viết từ **bất kỳ trang báo Việt Nam** chỉ bằng cách nhập URL trang chủ.

#### Thư viện sử dụng

| Thư viện                                  | Vai trò                                            |
| ----------------------------------------- | -------------------------------------------------- |
| `requests`                                | Gửi HTTP GET request để tải trang HTML             |
| `BeautifulSoup` (bs4)                     | Phân tích cú pháp HTML, trích xuất dữ liệu         |
| `concurrent.futures` (ThreadPoolExecutor) | Cào dữ liệu đa luồng, tăng tốc độ thu thập         |
| `csv` + `threading.Lock`                  | Ghi kết quả ra CSV an toàn đa luồng                |
| `urllib.parse`                            | Phân tích và chuẩn hóa URL                         |
| `re`                                      | Biểu thức chính quy để lọc URL, phát hiện bài viết |

#### a) Tự động phát hiện chuyên mục (`discover_categories`)

Khi người dùng nhập URL trang chủ (ví dụ: `znews.vn`), script **tự động quét trang chủ** để tìm các chuyên mục tin tức:

1. **Tải trang chủ** và phân tích HTML.
2. **Quét vùng navigation**: Tìm link trong các thẻ `<nav>`, `<header>`, `<ul class="menu">`, `[class*='nav']`, v.v. — sử dụng **12 CSS selector** khác nhau để tương thích với nhiều giao diện báo khác nhau.
3. **Lọc link chuyên mục**: Chỉ giữ lại các link 1 segment (ví dụ: `/the-thao`, `/kinh-doanh`), loại bỏ các path không hợp lệ (contact, login, video, tag, search, ...).
4. **Ánh xạ slug → nhãn tiếng Việt**: Sử dụng bảng `KNOWN_CATEGORY_SLUGS` gồm **35+ cặp slug-label** (ví dụ: `the-thao` → `Thể thao`, `kinh-te` → `Kinh doanh`). Với slug chưa biết, tự động capitalize (ví dụ: `xu-huong` → `Xu Huong`).

#### b) Tự động phát hiện mẫu phân trang (`detect_pagination_pattern`)

Mỗi trang báo có cách phân trang khác nhau. Script thử tuần tự **6 mẫu phân trang phổ biến** trên trang thứ 2 của chuyên mục để phát hiện mẫu đúng:

| #   | Mẫu phân trang                | Ví dụ                                |
| --- | ----------------------------- | ------------------------------------ |
| 1   | `/trang-{page}.htm`           | `tuoitre.vn/the-thao/trang-2.htm`    |
| 2   | `/trang-{page}.htm` (Dân Trí) | `dantri.com.vn/the-thao/trang-2.htm` |
| 3   | `-p{page}`                    | `vnexpress.net/the-thao-p2`          |
| 4   | `-page{page}`                 | `vietnamnet.vn/the-thao-page2`       |
| 5   | `?page={page}`                | `znews.vn/the-thao?page=2`           |
| 6   | `/page/{page}`                | `example.vn/the-thao/page/2`         |

Nếu không tìm được mẫu phù hợp, script chỉ cào trang 1 của chuyên mục.

#### c) Thu thập link bài viết (`extract_article_links`, `collect_links`)

- **Nhận diện bài viết bằng heuristic**: Một URL được coi là bài viết nếu slug cuối cùng đủ dài (≥ 3 dấu gạch ngang), cùng domain, không phải trang phân trang hay multimedia.
- **Ưu tiên trích xuất**: Tìm link trong `<article>`, `<h2>`, `<h3>`, `[class*='article']`, `[class*='title']` trước. Nếu ít hơn 5 link → fallback quét tất cả thẻ `<a>` trong trang.
- **Phân trang tự động**: Duyệt tối đa **50 trang** mỗi chuyên mục, kết hợp cơ chế **anti-loop** (dừng nếu link trùng lặp với trang trước hoặc không có link mới).

#### d) Cào nội dung bài viết — Generic (`generic_scrape_article`)

Điểm đặc biệt của script là cào nội dung bài viết theo cách **tổng quát**, không phụ thuộc cấu trúc HTML cụ thể của từng trang báo:

- **Trích xuất tiêu đề**: Thử 9 CSS selector phổ biến theo thứ tự ưu tiên: `h1.detail-title`, `h1.title-detail`, `h1[class*='title']`, `h1`, v.v.
- **Trích xuất nội dung**: Thử **20+ CSS selector** cho phần body bài viết: `article.fck_detail`, `div.detail-content`, `div.article-body`, `div.entry-content`, v.v.
- **Fallback thông minh**: Nếu không khớp selector nào:
  - Tìm thẻ `<article>` chứa nhiều `<p>` nhất.
  - Nếu vẫn không có → tìm `<div>` chứa nhiều `<p>` trực tiếp nhất (yêu cầu ≥ 3 đoạn `<p>`).
- **Loại bỏ nhiễu**: Xóa các thẻ script, style, figure, video, iframe, quảng cáo, tác giả, bài liên quan, share button, tag trước khi ghép đoạn văn.
- **Kiểm tra chất lượng**: Bỏ qua bài có nội dung < 50 ký tự.

#### e) Kỹ thuật chống bị chặn (Anti-blocking)

- Xoay vòng **User-Agent** ngẫu nhiên (5 trình duyệt: Chrome, Firefox, Safari, Edge).
- **Polite sleep**: Nghỉ ngẫu nhiên **2–4 giây** giữa mỗi request.
- **Retry tự động**: Tối đa 3 lần khi gặp lỗi mạng, với thời gian chờ tăng dần (`attempt × 3` giây).
- **Anti-loop**: Dừng cào phân trang nếu link trùng trang trước hoặc không có link mới.
- **Dừng sớm**: Nếu gặp 5 lỗi liên tiếp → dừng chuyên mục đó.

#### f) Đa luồng

Sử dụng `ThreadPoolExecutor` với tối đa **3 worker** để cào song song nhiều bài cùng lúc, kết hợp `threading.Lock` để ghi file CSV an toàn (thread-safe).

#### g) Kết quả thu thập

Toàn bộ dữ liệu từ **tất cả các trang báo** được ghi vào **một file CSV duy nhất**: **`dataset_all_news.csv`**.

| Cột       | Mô tả                                               |
| --------- | --------------------------------------------------- |
| `url`     | Đường dẫn bài báo gốc                               |
| `label`   | Nhãn chủ đề (tự động ánh xạ từ slug chuyên mục)     |
| `title`   | Tiêu đề bài báo                                     |
| `content` | Nội dung bài viết (đầy đủ)                          |
| `source`  | Tên trang báo nguồn (ví dụ: Tuoitre, Dantri, Znews) |

**Cách sử dụng**: Chỉ cần chạy `python scrape_all.py` → nhập URL trang báo (có thể nhập nhiều trang, phân cách dấu phẩy) → script tự phát hiện chuyên mục → cho phép chọn lọc → tự động cào bài viết.

---

## 2. Tiền xử lý cơ bản trên tập dữ liệu thu thập được

Quá trình tiền xử lý được thực hiện qua nhiều bước, triển khai trong các file Python.

### Bước 1: Gộp dữ liệu từ nhiều nguồn (`preprocess_data.py`)

Tất cả các file CSV thu thập được gộp thành một DataFrame duy nhất bằng `pd.concat()`. Với script Universal Scraper mới, dữ liệu đầu ra nằm trong file `dataset_all_news.csv`. Ngoài ra, các file CSV cũ từ các đợt cào trước cũng được gộp:

```
dataset_all_news.csv + news_dataset.csv + news_dataset_dantri.csv
+ news_dataset_tuoitre.csv + news_dataset_vietnamnet.csv
+ dataset_tuoitre_massive.csv
```

### Bước 2: Xóa dữ liệu rác (`preprocess_data.py`, `check_data.py`)

- **Xóa bài trùng lặp**: Loại bỏ các dòng trùng URL (`drop_duplicates(subset="url")`).
- **Xóa dòng thiếu dữ liệu**: Bỏ các dòng mà cột `content` hoặc `label` bị rỗng/NaN.
- **Xóa dòng thiếu tiêu đề**: Bỏ các dòng `title` rỗng.
- **Kiểm tra chất lượng**: File `check_data.py` thống kê số lượng trùng lặp (theo URL, title, content), phân bố nhãn, số dòng rỗng để đánh giá chất lượng dữ liệu.

### Bước 3: Chuẩn hóa nhãn (Label Mapping) (`clean_dataset.py`)

Do dữ liệu thu thập từ nhiều nguồn nên nhãn chuyên mục bị **không nhất quán** (ví dụ: `"THỂ THAO"`, `"Thể Thao"`, `"thể thao"`, `"Bóng đá"` đều thuộc chuyên mục _Thể thao_). Bước này thực hiện:

- **Mapping nhãn**: Xây dựng bảng ánh xạ (`LABEL_MAP`) để gom các nhãn tương tự về một nhãn chuẩn. Ví dụ:
  - `"Bóng đá"`, `"Tennis"`, `"Các môn khác"` → **Thể thao**
  - `"Kinh tế"`, `"Tài chính"`, `"Chứng khoán"`, `"Bất động sản"` → **Kinh doanh**
  - `"An ninh - Hình sự"` → **Pháp luật**
  - `"Văn hóa - Giải trí"`, `"Sao"`, `"Phim"` → **Giải trí**

### Bước 4: Làm sạch văn bản (Text Cleaning) (`preprocess_data.py`)

Hàm `clean_text()` thực hiện:

1. **Chuyển về chữ thường** (lowercase): `"Thể Thao Việt Nam"` → `"thể thao việt nam"`.
2. **Xóa ký tự đặc biệt**: Loại bỏ tất cả ký tự không phải chữ cái tiếng Việt hoặc khoảng trắng (số, dấu câu, ký tự đặc biệt) bằng biểu thức chính quy (regex).
3. **Xóa khoảng trắng thừa**: Gộp nhiều dấu cách liên tiếp thành 1 dấu cách.

### Bước 5: Tách từ tiếng Việt (Word Segmentation) (`preprocess_data.py`)

Sử dụng thư viện **underthesea** để tách từ tiếng Việt. Đây là bước **cực kỳ quan trọng** vì tiếng Việt là ngôn ngữ có từ ghép (ví dụ: "giáo dục", "khoa học"). Nếu không tách từ, mô hình sẽ hiểu sai nghĩa.

- **Trước**: `"giáo dục việt nam phát triển mạnh"`
- **Sau**: `"giáo_dục việt_nam phát_triển mạnh"`

Hàm `segment_words()` sử dụng `word_tokenize(text, format="text")` của underthesea.

### Bước 6: Sửa lỗi dữ liệu sau xử lý (`fix_missing_cleaned.py`)

Sau khi chạy tiền xử lý, kiểm tra và sửa các dòng bị lỗi:

- Tìm các dòng có `content_cleaned` là `'0'`, `'1'`, NaN, rỗng, hoặc quá ngắn (< 10 ký tự).
- Áp dụng lại `clean_text()` + `segment_words()` cho những dòng bị lỗi.
- Xóa các dòng vẫn rỗng sau khi sửa.

### Bước 7: Kết hợp dữ liệu JSON (`convert_json_to_csv.py`)

Chuyển đổi dữ liệu từ file `news_dataset.json` (VnExpress) sang định dạng CSV và gộp vào dataset tổng, đảm bảo cột tương thích (`topic` → `label`, `processed` → `content_cleaned`).

### Kết quả sau tiền xử lý

File đầu ra: **`dataset_tong_cleaned.csv`** với các cột:
| Cột | Mô tả |
|---|---|
| `url` | Đường dẫn bài báo gốc |
| `label` | Nhãn chủ đề (đã chuẩn hóa) |
| `title` | Tiêu đề bài báo |
| `content` | Nội dung gốc |
| `content_cleaned` | Nội dung đã làm sạch + tách từ |

---

## 3. Tổng quan phương pháp / thuật toán áp dụng

### 3.1. Trích xuất đặc trưng văn bản: TF-IDF

Máy tính không thể hiểu trực tiếp chữ viết. Do đó, trước khi đưa vào thuật toán phân loại, cần **chuyển đổi văn bản thành dạng số** (vector hóa). Kỹ thuật được sử dụng là **TF-IDF (Term Frequency – Inverse Document Frequency)**.

#### TF-IDF hoạt động như thế nào?

TF-IDF đánh giá **mức độ quan trọng** của một từ đối với một tài liệu trong tập dữ liệu, dựa trên hai thành phần:

- **TF (Term Frequency)** — Tần suất xuất hiện của từ trong tài liệu:

$$TF(t, d) = \frac{\text{Số lần từ } t \text{ xuất hiện trong tài liệu } d}{\text{Tổng số từ trong tài liệu } d}$$

- **IDF (Inverse Document Frequency)** — Độ hiếm của từ trong toàn bộ tập dữ liệu:

$$IDF(t) = \log\frac{\text{Tổng số tài liệu}}{\text{Số tài liệu chứa từ } t}$$

- **TF-IDF** = TF × IDF:

$$TF\text{-}IDF(t, d) = TF(t, d) \times IDF(t)$$

**Ý nghĩa**: Từ nào xuất hiện **nhiều trong một bài** nhưng **ít trong các bài khác** sẽ có trọng số TF-IDF cao → đó là từ đặc trưng, giúp phân biệt chủ đề. Ví dụ: từ `"bàn_thắng"` xuất hiện nhiều trong bài Thể thao nhưng hiếm trong bài Kinh doanh → TF-IDF cao.

Sau bước TF-IDF, mỗi bài báo được biểu diễn thành một **vector số** trong không gian nhiều chiều (mỗi chiều tương ứng với một từ trong từ điển).

### 3.2. Thuật toán 1: Naïve Bayes (Multinomial Naïve Bayes) — Mô hình cơ sở (Baseline)

#### Bản chất

Naïve Bayes dựa trên **Định lý Bayes** trong xác suất thống kê. Với bài toán phân loại tin tức, nó trả lời câu hỏi:

> _"Với những từ vựng xuất hiện trong bài báo này, xác suất bài báo thuộc chuyên mục Thể thao / Kinh doanh / Giáo dục /... là bao nhiêu?"_

Công thức Bayes:

$$P(C_k | \mathbf{x}) = \frac{P(\mathbf{x} | C_k) \cdot P(C_k)}{P(\mathbf{x})}$$

Trong đó:

- $P(C_k | \mathbf{x})$: Xác suất bài báo thuộc chủ đề $C_k$ khi biết nội dung $\mathbf{x}$.
- $P(\mathbf{x} | C_k)$: Xác suất nội dung $\mathbf{x}$ xuất hiện nếu bài thuộc chủ đề $C_k$.
- $P(C_k)$: Xác suất tiên nghiệm (prior) của chủ đề $C_k$.

Giả định **"Naïve" (ngây thơ)**: Các từ trong bài báo là **độc lập** với nhau (giả định đơn giản hóa nhưng hiệu quả trong thực tế).

**Multinomial Naïve Bayes** đặc biệt phù hợp cho dữ liệu dạng **đếm tần suất từ** (count-based) hoặc **TF-IDF** — chính xác là dạng dữ liệu trong bài toán phân loại văn bản.

#### Ưu điểm

- **Huấn luyện cực nhanh**: Chỉ cần tính xác suất thống kê, không cần quá trình tối ưu phức tạp → chạy được trên mọi cấu hình máy tính.
- **Đơn giản, dễ hiểu**: Logic trực quan, dễ giải thích kết quả.
- **Hiệu quả với dữ liệu văn bản**: Dù giả định "ngây thơ" nhưng vẫn cho kết quả tốt trong phân loại text.

#### Vai trò trong đề tài

Naïve Bayes được sử dụng làm **Mô hình cơ sở (Baseline Model)** — là mốc đo lường đầu tiên để so sánh với các thuật toán phức tạp hơn. Nếu mô hình sau không vượt qua Baseline, nghĩa là mô hình đó chưa thực sự hiệu quả.

---

### 3.3. Thuật toán 2: Support Vector Machine (SVM)

#### Bản chất

SVM tìm ra một **siêu phẳng (hyperplane)** tối ưu nhất trong không gian nhiều chiều để **chia tách** các chuyên mục bài báo ra khỏi nhau. "Tối ưu" ở đây nghĩa là khoảng cách (margin) từ siêu phẳng đến các điểm dữ liệu gần nhất (support vectors) là **lớn nhất**.

Với bài toán phân loại nhiều lớp (multi-class), SVM sử dụng chiến lược **One-vs-Rest (OvR)**: tạo nhiều bộ phân loại nhị phân, mỗi bộ phân biệt một chủ đề với tất cả các chủ đề còn lại.

#### Tại sao SVM xuất sắc với dữ liệu văn bản?

- **Dữ liệu văn bản có số chiều cực lớn**: Sau bước TF-IDF, mỗi bài báo là một vector với hàng chục nghìn chiều (mỗi chiều = một từ). SVM xử lý rất tốt trong không gian chiều cao nhờ cơ chế tìm margin tối ưu.
- **Dữ liệu thưa (sparse)**: Vector TF-IDF có rất nhiều giá trị = 0 (phần lớn từ không xuất hiện trong bài). SVM hoạt động hiệu quả với dữ liệu thưa.
- **Kernel trick**: SVM có thể sử dụng kernel (ví dụ: Linear, RBF) để ánh xạ dữ liệu sang không gian chiều cao hơn, giúp phân tách tốt hơn khi dữ liệu không tách tuyến tính được.

#### Ưu điểm

- **Độ chính xác cao nhất** trong nhóm thuật toán truyền thống (Machine Learning cổ điển) khi xử lý phân loại văn bản.
- **Khả năng tổng quát hóa tốt**: Ít bị overfitting nhờ cơ chế tối đa hóa margin.
- **Hiệu quả với dữ liệu chiều cao và thưa**: Đặc biệt phù hợp với TF-IDF vector.

#### Vai trò trong đề tài

SVM là **mô hình chính (Main Model)**, kỳ vọng đạt độ chính xác cao hơn Baseline (Naïve Bayes). So sánh kết quả của SVM với Naïve Bayes sẽ cho thấy rõ sự cải thiện khi sử dụng thuật toán phức tạp hơn.

---

### 3.4. Pipeline tổng thể

```
Dữ liệu thô (bài báo tiếng Việt)
        │
        ▼
[1] Thu thập dữ liệu (Universal Scraper — bất kỳ trang báo)
        │
        ▼
[2] Tiền xử lý (Làm sạch → Tách từ → Chuẩn hóa nhãn)
        │
        ▼
[3] Trích xuất đặc trưng (TF-IDF → Vector hóa văn bản)
        │
        ▼
[4] Huấn luyện mô hình
    ├── Naïve Bayes (Baseline)
    └── SVM (Main Model)
        │
        ▼
[5] Đánh giá & So sánh (Accuracy, Precision, Recall, F1-score)
```

---

_Báo cáo tiến độ lần 1 — Hoàn thành._
