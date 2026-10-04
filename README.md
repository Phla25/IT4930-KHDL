# Đồ án Môn học: IT4930 - Nhập môn Khoa học Dữ liệu (IT4930-KHDL)

**Đề tài:** Dự báo lưu lượng giao thông liên bang I-94 (Metro Interstate Traffic Volume Forecasting)  
**Trường:** Công nghệ Thông tin và Truyền thông - Đại học Bách khoa Hà Nội (HUST)  

---

## 1. Giới thiệu Đề tài
Dự án tập trung vào việc nghiên cứu, tiền xử lý, phân tích khám phá (EDA) và ứng dụng các mô hình học máy (Machine Learning) để dự báo lưu lượng giao thông theo giờ (`traffic_volume`) trên tuyến cao tốc liên bang I-94 Westbound (nối Minneapolis và St Paul, Minnesota), kết hợp các yếu tố khí tượng (nhiệt độ, mưa, tuyết, mây phủ, tốc độ gió) và lịch nghỉ lễ.

---

## 2. Cấu trúc Thư mục Dự án

```
IT4930-KHDL/
│
├── data/
│   ├── raw/                                           # Dữ liệu thô ban đầu (bất biến)
│   │   ├── traffic_volume_raw.csv                     # Tập 1: Lưu lượng phương tiện chính (40,575 dòng)
│   │   ├── weather_holiday_raw.csv                    # Tập 2: Thời tiết & Lịch lễ tương ứng (48,204 dòng)
│   │   ├── Metro_Interstate_Traffic_Volume.csv        # Tập 3: Dữ liệu thô gốc tích hợp (UCI Repository)
│   │   └── Metro_Interstate_Traffic_Volume_modified.csv # Tập 4: Dữ liệu thô mở rộng thuộc tính & có khuyết thiếu
│   └── data_understanding_report.md                   # Báo cáo thấu hiểu dữ liệu
│
├── dataset/                                           # Thư mục dataset (đồng bộ tương thích)
│   ├── data_details.md                                # Bản sao Từ điển dữ liệu
│   ├── Metro_Interstate_Traffic_Volume.csv
│   └── Metro_Interstate_Traffic_Volume_modified.csv
│
├── data_understanding_report.md                       # Từ điển dữ liệu & Báo cáo thấu hiểu dữ liệu chi tiết
└── README.md
```

---

## 3. Tài liệu Báo cáo & Từ điển Dữ liệu (Data Dictionary)
Báo cáo chi tiết về thấu hiểu dữ liệu theo chuẩn CRISP-DM đã được biên soạn đầy đủ tại:
* [data_understanding_report.md](file:///D:/lessonsatuniversity/DataScience/IT4930-KHDL/data_understanding_report.md)
* Bản sao tại [dataset/data_details.md](file:///D:/lessonsatuniversity/DataScience/IT4930-KHDL/dataset/data_details.md)

Tài liệu bao gồm:
* Tổng quan bài toán, xuất xứ và nguồn gốc dữ liệu.
* Bảng tra cứu và mô tả chi tiết **100% các trường thuộc tính (13/13 trường)**: ý nghĩa nghiệp vụ, đơn vị đo, kiểu dữ liệu, miền giá trị, tỷ lệ khuyết thiếu và phân phối danh mục.
* Sơ đồ thực thể quan hệ (ERD) và code mẫu Python tích hợp hai tập dữ liệu thô độc lập qua khóa `date_time`.
* Đánh giá chất lượng dữ liệu thô (ngoại lai nhiệt độ $0K$, lượng mưa cực đoan $9831.3mm$, tính bất đồng nhất về kiểu chữ).
* Kế hoạch và định hướng các bước tiền xử lý dữ liệu tiếp theo.
