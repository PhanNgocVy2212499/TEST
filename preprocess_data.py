# =============================================================================
# Script Tiền xử lý dữ liệu văn bản tiếng Việt
# Phục vụ bài toán: Phân loại chủ đề tin tức
# Thư viện: pandas, re, underthesea
# =============================================================================

import pandas as pd
import re
import os
from underthesea import word_tokenize

# =============================================================================
# Bước 2.1 - Gộp dữ liệu từ nhiều file CSV
# =============================================================================
print("=" * 60)
print("BƯỚC 1: Đọc và gộp dữ liệu từ các file CSV")
print("=" * 60)

# Danh sách các file CSV cần đọc
csv_files = [
    "news_dataset.csv",
    "news_dataset_dantri.csv",
    "news_dataset_tuoitre.csv",
    "news_dataset_vietnamnet.csv",
    "dataset_tuoitre_massive.csv",
]

# Đọc từng file, bỏ qua file nào không tồn tại
dataframes = []
for file in csv_files:
    if os.path.exists(file):
        try:
            df_temp = pd.read_csv(file)
            dataframes.append(df_temp)
            print(f"  ✔ Đọc thành công: {file} ({len(df_temp)} bài)")
        except Exception as e:
            print(f"  ✘ Lỗi khi đọc {file}: {e}")
    else:
        print(f"  ⚠ Không tìm thấy file: {file} -> Bỏ qua.")

# Gộp tất cả DataFrame lại thành 1
if not dataframes:
    raise SystemExit("Không có file CSV nào hợp lệ để xử lý. Dừng chương trình.")

df = pd.concat(dataframes, ignore_index=True)
print(f"\n→ Tổng số bài sau khi gộp: {len(df)}")

# =============================================================================
# Bước 2.2 - Xóa dữ liệu rác (trùng lặp, thiếu dữ liệu)
# =============================================================================
print("\n" + "=" * 60)
print("BƯỚC 2: Xóa dữ liệu rác (trùng lặp & thiếu dữ liệu)")
print("=" * 60)

print(f"  Tổng số bài TRƯỚC khi lọc: {len(df)}")

# Xóa các dòng trùng lặp dựa trên cột 'url'
before_dedup = len(df)
df.drop_duplicates(subset="url", keep="first", inplace=True)
print(f"  → Đã xóa {before_dedup - len(df)} dòng trùng lặp (theo url)")

# Xóa các dòng bị thiếu dữ liệu ở cột 'content' hoặc 'label'
before_dropna = len(df)
df.dropna(subset=["content", "label"], inplace=True)
print(f"  → Đã xóa {before_dropna - len(df)} dòng thiếu content hoặc label")

# Reset lại index sau khi xóa
df.reset_index(drop=True, inplace=True)
print(f"  ✔ Tổng số bài SAU khi lọc: {len(df)}")

# Thống kê số lượng bài theo từng chủ đề
print("\n  Phân bố chủ đề:")
label_counts = df["label"].value_counts()
for label, count in label_counts.items():
    print(f"    - {label}: {count} bài")

# =============================================================================
# Bước 2.3 - Hàm Làm sạch văn bản (Clean Text)
# =============================================================================

def clean_text(text):
    """
    Làm sạch văn bản:
    - Chuyển về chữ thường (lowercase)
    - Xóa ký tự đặc biệt, dấu câu, số
    - Chỉ giữ lại chữ cái tiếng Việt và khoảng trắng
    """
    if not isinstance(text, str):
        return ""

    # Chuyển về chữ thường
    text = text.lower()

    # Xóa tất cả ký tự KHÔNG phải chữ cái (tiếng Việt + Latin) hoặc khoảng trắng
    # Giữ lại: a-z, các ký tự có dấu tiếng Việt, khoảng trắng
    text = re.sub(
        r"[^a-záàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ\s]",
        " ",
        text,
    )

    # Xóa khoảng trắng thừa (nhiều dấu cách liên tiếp -> 1 dấu cách)
    text = re.sub(r"\s+", " ", text).strip()

    return text


# =============================================================================
# Bước 2.4 - Hàm Tách từ tiếng Việt (Word Segmentation)
# =============================================================================

def segment_words(text):
    """
    Tách từ tiếng Việt bằng underthesea.
    Ví dụ: "giáo dục" -> "giáo_dục"
    """
    if not isinstance(text, str) or text.strip() == "":
        return ""
    return word_tokenize(text, format="text")


# =============================================================================
# Bước 2.5 - Áp dụng tiền xử lý và lưu kết quả
# =============================================================================
print("\n" + "=" * 60)
print("BƯỚC 3: Áp dụng tiền xử lý lên cột 'content'")
print("=" * 60)

total = len(df)

# Bước 3a: Làm sạch văn bản
print(f"  Đang làm sạch văn bản ({total} bài)...")
df["content_cleaned"] = df["content"].apply(clean_text)
print("  ✔ Làm sạch hoàn tất!")

# Bước 3b: Tách từ tiếng Việt
print(f"  Đang tách từ tiếng Việt ({total} bài)... (có thể mất vài phút)")
df["content_cleaned"] = df["content_cleaned"].apply(segment_words)
print("  ✔ Tách từ hoàn tất!")

# Xóa các dòng mà sau khi xử lý content_cleaned bị rỗng
before_clean = len(df)
df = df[df["content_cleaned"].str.strip().astype(bool)]
df.reset_index(drop=True, inplace=True)
if before_clean - len(df) > 0:
    print(f"  → Đã xóa thêm {before_clean - len(df)} dòng có nội dung rỗng sau khi làm sạch")

# Lưu kết quả ra file CSV mới
output_file = "dataset_tong_cleaned.csv"
df.to_csv(output_file, index=False)

print("\n" + "=" * 60)
print("HOÀN TẤT!")
print("=" * 60)
print(f"  ✔ Tổng số bài sau tiền xử lý: {len(df)}")
print(f"  ✔ File kết quả đã lưu tại: {output_file}")
print(f"  ✔ Các cột: {df.columns.tolist()}")

# Hiển thị mẫu 3 dòng đầu tiên để kiểm tra
print("\n  📋 Mẫu dữ liệu sau tiền xử lý:")
print("-" * 60)
for i in range(min(3, len(df))):
    print(f"  [{i}] Label: {df.loc[i, 'label']}")
    print(f"      Content gốc : {str(df.loc[i, 'content'])[:100]}...")
    print(f"      Content sạch : {str(df.loc[i, 'content_cleaned'])[:100]}...")
    print()
