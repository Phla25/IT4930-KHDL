"""
================================================================================
DATA CLEANING & PREPROCESSING PIPELINE (src/data_cleaning.py)
Project: IT4930 - Data Science (Khoa học dữ liệu)
Author: Quỳnh Anh (TECH-01) - Task: SP1-T3
Description:
    Tiền xử lý, lọc rác và làm sạch dữ liệu gộp giao thông - thời tiết - lịch lễ:
    1. Loại bỏ các cột trùng lặp và không mang giá trị dự báo (date_time_raw, date_time).
    2. Phát hiện và xử lý giá trị ngoại lai vật lý (temp 0 K, rain_1h cực đại phi lý/âm,
       traffic_volume âm/bất thường, snow_1h âm).
    3. Bù khuyết dữ liệu thiếu (Missing/NaN) phù hợp đặc thù chuỗi thời gian:
       - Linear Interpolation (Nội suy tuyến tính) cho biến liên tục.
       - Forward-fill (ffill) & Backward-fill (bfill) cho biến phân loại.
       - Domain-specific logic cho các hiện tượng thời tiết thưa (rain, snow).
    4. Kiểm định chất lượng dữ liệu (QA & DoD Validation: 0 NaN, 0 Ngoại lai vật lý).
    5. Xuất bản file chuẩn sạch: data/processed/clean_traffic_data.csv.
================================================================================
"""

import os
import sys
import argparse
import logging
from typing import Dict, Any, Tuple, List
import pandas as pd
import numpy as np

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("DataCleaningPipeline")

# Cấu hình đường dẫn mặc định
DEFAULT_INPUT_FILE = "data/interim/merged_traffic_data.csv"
DEFAULT_OUTPUT_FILE = "data/processed/clean_traffic_data.csv"

# Ngưỡng vật lý thực tế (Physical Boundaries)
PHYSICAL_BOUNDS = {
    "temp": {"min": 200.0, "max": 330.0},           # Kelvin: 200K (-73°C) -> 330K (+57°C)
    "rain_1h": {"min": 0.0, "max": 300.0},          # mm/h: Kỷ lục mưa cực đoan thế giới ~305 mm/h
    "snow_1h": {"min": 0.0, "max": 100.0},          # mm/h: Lượng tuyết đo trong 1h
    "traffic_volume": {"min": 1.0, "max": 10000.0}, # Lưu lượng xe/h trên tuyến cao tốc liên bang
    "clouds_all": {"min": 0.0, "max": 100.0},       # Tỷ lệ che phủ mây (%)
    "wind_speed_ms": {"min": 0.0, "max": 60.0},     # Tốc độ gió (m/s)
    "fog_mm": {"min": 0.0, "max": 1000.0},          # Mật độ sương mù
    "flood_mm": {"min": 0.0, "max": 1000.0}         # Mực nước ngập
}

# Danh sách cột trùng lặp hoặc không mang giá trị dự báo cần loại bỏ
REDUNDANT_COLUMNS = ["date_time_raw", "date_time"]


def load_dataset(file_path: str) -> pd.DataFrame:
    """
    Nạp dữ liệu từ file CSV interim.
    
    Args:
        file_path (str): Đường dẫn tới file interim CSV.
        
    Returns:
        pd.DataFrame: Dữ liệu đã nạp.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Không tìm thấy file dữ liệu tại: {file_path}")
        
    logger.info(f"Đang nạp dữ liệu từ '{file_path}'...")
    df = pd.read_csv(file_path)
    logger.info(f"Nạp thành công: {df.shape[0]:,} dòng, {df.shape[1]} cột.")
    return df


def drop_redundant_features(df: pd.DataFrame, drop_cols: List[str] = REDUNDANT_COLUMNS) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Loại bỏ các cột trùng lặp, định dạng chuỗi thô hoặc không mang giá trị dự báo.
    
    Args:
        df (pd.DataFrame): DataFrame đầu vào.
        drop_cols (List[str]): Danh sách các cột cần loại bỏ.
        
    Returns:
        Tuple[pd.DataFrame, Dict[str, Any]]: (df_sau_khi_drop, thống_kê)
    """
    logger.info("Đang tiến hành loại bỏ các cột trùng lặp và không mang giá trị dự báo...")
    existing_drop_cols = [col for col in drop_cols if col in df.columns]
    
    df_cleaned = df.drop(columns=existing_drop_cols).copy()
    
    stats = {
        "dropped_columns": existing_drop_cols,
        "num_dropped_columns": len(existing_drop_cols),
        "initial_columns_count": df.shape[1],
        "remaining_columns_count": df_cleaned.shape[1]
    }
    
    logger.info(f"-> Đã loại bỏ {len(existing_drop_cols)} cột: {existing_drop_cols}")
    logger.info(f"-> Số cột còn lại: {df_cleaned.shape[1]}")
    return df_cleaned, stats


def sanitize_physical_outliers(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Phát hiện các giá trị ngoại lai vật lý (vô lý khoa học / lỗi cảm biến)
    và gán thành NaN để chuẩn bị cho bước nội suy bù khuyết theo chuỗi thời gian.
    
    Các trường hợp xử lý:
    1. temp: 0 K (độ không tuyệt đối) hoặc ngoài dải [200K, 330K].
    2. rain_1h: < 0 mm hoặc > 300 mm/h (sensor glitch như 9831.3 mm).
    3. snow_1h: < 0 mm.
    4. traffic_volume: < 0 hoặc == 0 trên đường cao tốc huyết mạch I-94 vào ban ngày/chiều tối.
    5. clouds_all: < 0% hoặc > 100%.
    
    Args:
        df (pd.DataFrame): DataFrame sau khi lọc cột.
        
    Returns:
        Tuple[pd.DataFrame, Dict[str, Any]]: (df_sau_khi_mask, thống_kê_ngoại_lai)
    """
    logger.info("Đang quét và xử lý các giá trị ngoại lai vật lý...")
    df_sanitized = df.copy()
    outlier_stats = {}

    # 1. Nhiệt độ (temp)
    t_bounds = PHYSICAL_BOUNDS["temp"]
    mask_temp_zero = (df_sanitized["temp"] == 0)
    mask_temp_out = (df_sanitized["temp"] < t_bounds["min"]) | (df_sanitized["temp"] > t_bounds["max"])
    outlier_temp_count = int(mask_temp_out.sum())
    outlier_stats["temp_outliers_count"] = outlier_temp_count
    outlier_stats["temp_absolute_zero_count"] = int(mask_temp_zero.sum())
    if outlier_temp_count > 0:
        logger.warning(f"-> Phát hiện {outlier_temp_count} ngoại lai nhiệt độ (gồm {mask_temp_zero.sum()} mốc 0.0 K). Chuyển thành NaN.")
        df_sanitized.loc[mask_temp_out, "temp"] = np.nan

    # 2. Lượng mưa (rain_1h)
    r_bounds = PHYSICAL_BOUNDS["rain_1h"]
    mask_rain_neg = (df_sanitized["rain_1h"] < r_bounds["min"])
    mask_rain_extreme = (df_sanitized["rain_1h"] > r_bounds["max"])
    outlier_rain_count = int((mask_rain_neg | mask_rain_extreme).sum())
    outlier_stats["rain_extreme_count"] = int(mask_rain_extreme.sum())
    outlier_stats["rain_negative_count"] = int(mask_rain_neg.sum())
    if outlier_rain_count > 0:
        logger.warning(f"-> Phát hiện {outlier_rain_count} ngoại lai lượng mưa (lớn nhất {df['rain_1h'].max():.1f} mm). Chuyển thành NaN.")
        df_sanitized.loc[mask_rain_neg | mask_rain_extreme, "rain_1h"] = np.nan

    # 3. Lượng tuyết (snow_1h)
    s_bounds = PHYSICAL_BOUNDS["snow_1h"]
    mask_snow_out = (df_sanitized["snow_1h"] < s_bounds["min"]) | (df_sanitized["snow_1h"] > s_bounds["max"])
    outlier_snow_count = int(mask_snow_out.sum())
    outlier_stats["snow_outliers_count"] = outlier_snow_count
    if outlier_snow_count > 0:
        logger.warning(f"-> Phát hiện {outlier_snow_count} ngoại lai lượng tuyết âm. Chuyển thành NaN.")
        df_sanitized.loc[mask_snow_out, "snow_1h"] = np.nan

    # 4. Lưu lượng xe (traffic_volume)
    # Lưu lượng âm hoặc bằng 0 tại khung giờ cao điểm / cuối tuần trên cao tốc I-94
    mask_traffic_neg = (df_sanitized["traffic_volume"] < 0)
    mask_traffic_zero = (df_sanitized["traffic_volume"] == 0)
    outlier_traffic_count = int((mask_traffic_neg | mask_traffic_zero).sum())
    outlier_stats["traffic_negative_count"] = int(mask_traffic_neg.sum())
    outlier_stats["traffic_zero_drop_count"] = int(mask_traffic_zero.sum())
    if outlier_traffic_count > 0:
        logger.warning(f"-> Phát hiện {outlier_traffic_count} mốc lưu lượng xe bất thường (bằng 0 hoặc âm). Chuyển thành NaN.")
        df_sanitized.loc[mask_traffic_neg | mask_traffic_zero, "traffic_volume"] = np.nan

    # 5. Độ che phủ mây (clouds_all)
    c_bounds = PHYSICAL_BOUNDS["clouds_all"]
    mask_clouds_out = (df_sanitized["clouds_all"] < c_bounds["min"]) | (df_sanitized["clouds_all"] > c_bounds["max"])
    outlier_clouds_count = int(mask_clouds_out.sum())
    outlier_stats["clouds_outliers_count"] = outlier_clouds_count
    if outlier_clouds_count > 0:
        logger.warning(f"-> Phát hiện {outlier_clouds_count} ngoại lai độ che phủ mây. Chuyển thành NaN.")
        df_sanitized.loc[mask_clouds_out, "clouds_all"] = np.nan

    return df_sanitized, outlier_stats


def impute_missing_values(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Bù khuyết các giá trị thiếu (Missing/NaN) phù hợp đặc thù chuỗi thời gian:
    1. Sắp xếp chuỗi thời gian tuần tự theo date_time_iso.
    2. Biến liên tục (traffic_volume, temp, clouds_all, wind_speed_ms, fog_mm, flood_mm):
       - Nội suy tuyến tính theo thời gian: df[col].interpolate(method='linear')
       - Kết hợp forward-fill (ffill) và backward-fill (bfill) cho phần biên.
    3. Biến hiện tượng thời tiết thưa (rain_1h, snow_1h):
       - Nếu không có mưa/tuyết (thời tiết Clear, Clouds, Mist,...), bù 0.0.
       - Nếu nằm trong đợt mưa/tuyết, nội suy tuyến tính.
    4. Biến nhãn ngày lễ (holiday_name):
       - Gán chuỗi 'None' cho các ngày thường (is_holiday == 0).
    5. Biến phân loại thời tiết (weather_main, weather_description):
       - Forward-fill (ffill) theo tính liên tục khí hậu, sau đó bfill.
       
    Args:
        df (pd.DataFrame): DataFrame cần bù khuyết.
        
    Returns:
        Tuple[pd.DataFrame, Dict[str, Any]]: (df_sau_khi_bù, thống_kê_missing)
    """
    logger.info("Đang tiến hành bù khuyết dữ liệu thiếu (Time-series Imputation)...")
    df_imputed = df.copy()

    # Lưu lại thống kê missing trước khi bù
    pre_impute_missing = df_imputed.isna().sum().to_dict()

    # 1. Đảm bảo dữ liệu sắp xếp chính xác theo trục thời gian
    df_imputed["date_time_iso"] = pd.to_datetime(df_imputed["date_time_iso"])
    df_imputed = df_imputed.sort_values("date_time_iso").reset_index(drop=True)

    # 2. Bù khuyết biến nhãn ngày lễ
    # Sử dụng nhãn tường minh 'Not Holiday' thay vì 'None' để tránh việc thư viện
    # Pandas khi nạp lại file CSV từ đĩa tự động nhận diện chuỗi 'None' thành NaN (default na_values).
    if "holiday_name" in df_imputed.columns:
        df_imputed["holiday_name"] = df_imputed["holiday_name"].replace({"None": "Not Holiday"}).fillna("Not Holiday")

    # 3. Bù khuyết biến số liên tục (Nội suy tuyến tính + ffill + bfill)
    continuous_features = [
        "traffic_volume", "temp", "clouds_all", 
        "wind_speed_ms", "fog_mm", "flood_mm"
    ]
    for col in continuous_features:
        if col in df_imputed.columns:
            df_imputed[col] = df_imputed[col].interpolate(method="linear").ffill().bfill()
            # Bounding lại các giá trị vật lý để tránh sai số nội suy
            if col in PHYSICAL_BOUNDS:
                b = PHYSICAL_BOUNDS[col]
                df_imputed[col] = df_imputed[col].clip(lower=b["min"], upper=b["max"])

    # 4. Bù khuyết lượng mưa (rain_1h) theo ngữ cảnh thời tiết
    if "rain_1h" in df_imputed.columns:
        rain_indicators = ["Rain", "Drizzle", "Thunderstorm", "Squall"]
        is_rain_event = df_imputed["weather_main"].astype(str).str.contains(
            "|".join(rain_indicators), case=False, na=False
        )
        # Nếu không có mưa trong mô tả thời tiết, lượng mưa là 0.0
        df_imputed.loc[df_imputed["rain_1h"].isna() & ~is_rain_event, "rain_1h"] = 0.0
        # Các vị trí còn lại trong đợt mưa áp dụng nội suy tuyến tính
        df_imputed["rain_1h"] = df_imputed["rain_1h"].interpolate(method="linear").fillna(0.0)
        df_imputed["rain_1h"] = df_imputed["rain_1h"].clip(lower=0.0)

    # 5. Bù khuyết lượng tuyết (snow_1h) theo ngữ cảnh thời tiết
    if "snow_1h" in df_imputed.columns:
        is_snow_event = df_imputed["weather_main"].astype(str).str.contains(
            "Snow", case=False, na=False
        )
        df_imputed.loc[df_imputed["snow_1h"].isna() & ~is_snow_event, "snow_1h"] = 0.0
        df_imputed["snow_1h"] = df_imputed["snow_1h"].interpolate(method="linear").fillna(0.0)
        df_imputed["snow_1h"] = df_imputed["snow_1h"].clip(lower=0.0)

    # 6. Bù khuyết biến phân loại thời tiết (nếu có)
    categorical_features = ["weather_main", "weather_description", "day_type", "day_of_week"]
    for col in categorical_features:
        if col in df_imputed.columns:
            df_imputed[col] = df_imputed[col].ffill().bfill()

    # Chuyển đổi date_time_iso về dạng chuỗi chuẩn định dạng
    df_imputed["date_time_iso"] = df_imputed["date_time_iso"].dt.strftime("%Y-%m-%d %H:%M:%S")

    # Lưu lại thống kê missing sau khi bù
    post_impute_missing = df_imputed.isna().sum().to_dict()

    stats = {
        "pre_missing": pre_impute_missing,
        "post_missing": post_impute_missing,
        "total_missing_before": sum(pre_impute_missing.values()),
        "total_missing_after": sum(post_impute_missing.values())
    }

    logger.info(f"-> Tổng missing trước khi bù: {stats['total_missing_before']:,}")
    logger.info(f"-> Tổng missing sau khi bù: {stats['total_missing_after']}")
    return df_imputed, stats


def validate_clean_data(df: pd.DataFrame) -> Dict[str, bool]:
    """
    Kiểm định toàn diện chất lượng dữ liệu đầu ra đạt chuẩn Definition of Done (DoD):
    1. Không còn bất kỳ giá trị NaN / Null nào trong bảng.
    2. Không có giá trị lưu lượng xe <= 0.
    3. Không có giá trị nhiệt độ < 200 K (hoặc 0 K).
    4. Không có giá trị lượng mưa / tuyết < 0.
    5. Không có độ che phủ mây < 0 hoặc > 100%.
    6. Khóa thời gian date_time_iso duy nhất 100% (không trùng lặp).
    
    Args:
        df (pd.DataFrame): DataFrame đã làm sạch.
        
    Returns:
        Dict[str, bool]: Báo cáo trạng thái các bài kiểm định.
    """
    logger.info("Đang thực hiện kiểm định chất lượng dữ liệu (QA Checks)...")
    
    # 1. Null check
    total_nulls = df.isna().sum().sum()
    null_check = (total_nulls == 0)

    # 2. Traffic check
    traffic_valid = (df["traffic_volume"] > 0).all()

    # 3. Temp check
    temp_valid = ((df["temp"] >= PHYSICAL_BOUNDS["temp"]["min"]) & 
                  (df["temp"] <= PHYSICAL_BOUNDS["temp"]["max"])).all()

    # 4. Rain & Snow check
    rain_valid = (df["rain_1h"] >= 0.0).all()
    snow_valid = (df["snow_1h"] >= 0.0).all()

    # 5. Clouds check
    clouds_valid = ((df["clouds_all"] >= 0.0) & (df["clouds_all"] <= 100.0)).all()

    # 6. Timestamp uniqueness
    timestamp_unique = (df["date_time_iso"].nunique() == len(df))

    checks = {
        "Zero NaN Check": bool(null_check),
        "Valid Traffic Volume Check": bool(traffic_valid),
        "Valid Temperature Check": bool(temp_valid),
        "Valid Rain & Snow Check": bool(rain_valid and snow_valid),
        "Valid Clouds Coverage Check": bool(clouds_valid),
        "Unique Timestamps Check": bool(timestamp_unique)
    }

    for name, passed in checks.items():
        status = "PASSED ✅" if passed else "FAILED ❌"
        logger.info(f"QA: {name.ljust(32)}: {status}")

    all_passed = all(checks.values())
    if not all_passed:
        logger.error("Dữ liệu không vượt qua các kiểm định chất lượng!")
    else:
        logger.info("TẤT CẢ CÁC KIỂM ĐỊNH CHẤT LƯỢNG ĐÃ VƯỢT QUA XUẤT SẮC! 🎉")

    return checks


def export_clean_data(df: pd.DataFrame, output_path: str = DEFAULT_OUTPUT_FILE) -> None:
    """
    Lưu tập dữ liệu đã làm sạch vào đường dẫn đích.
    
    Args:
        df (pd.DataFrame): DataFrame đã làm sạch.
        output_path (str): Đường dẫn lưu file CSV.
    """
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        
    logger.info(f"Đang lưu file dữ liệu sạch vào '{output_path}'...")
    df.to_csv(output_path, index=False)
    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info(f"Đã lưu thành công: {df.shape[0]:,} dòng, {df.shape[1]} cột ({file_size_mb:.2f} MB).")


def run_pipeline(
    input_path: str = DEFAULT_INPUT_FILE, 
    output_path: str = DEFAULT_OUTPUT_FILE
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Thực thi toàn bộ quy trình tiền xử lý, lọc rác và làm sạch dữ liệu.
    
    Args:
        input_path (str): Đường dẫn file interim.
        output_path (str): Đường dẫn file xuất processed.
        
    Returns:
        Tuple[pd.DataFrame, Dict[str, Any]]: (df_clean, full_report)
    """
    logger.info("=" * 70)
    logger.info("BẮT ĐẦU ĐƯỜNG ỐNG LÀM SẠCH VÀ TIỀN XỬ LÝ DỮ LIỆU (SP1-T3)")
    logger.info("=" * 70)

    # 1. Nạp dữ liệu
    df_raw = load_dataset(input_path)

    # 2. Loại bỏ cột trùng lặp
    df_dropped, drop_stats = drop_redundant_features(df_raw)

    # 3. Xử lý ngoại lai vật lý
    df_sanitized, outlier_stats = sanitize_physical_outliers(df_dropped)

    # 4. Bù khuyết dữ liệu thiếu
    df_clean, impute_stats = impute_missing_values(df_sanitized)

    # 5. Kiểm định chất lượng
    qa_checks = validate_clean_data(df_clean)

    # 6. Lưu file kết quả
    export_clean_data(df_clean, output_path)

    full_report = {
        "drop_stats": drop_stats,
        "outlier_stats": outlier_stats,
        "impute_stats": impute_stats,
        "qa_checks": qa_checks,
        "final_shape": df_clean.shape
    }

    logger.info("=" * 70)
    logger.info("HOÀN THÀNH ĐƯỜNG ỐNG TIỀN XỬ LÝ VÀ LÀM SẠCH DỮ LIỆU THÀNH CÔNG!")
    logger.info("=" * 70)

    return df_clean, full_report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Data Cleaning & Preprocessing Pipeline for IT4930 (SP1-T3)"
    )
    parser.add_argument(
        "--input", 
        type=str, 
        default=DEFAULT_INPUT_FILE, 
        help=f"Đường dẫn file dữ liệu interim (mặc định: {DEFAULT_INPUT_FILE})"
    )
    parser.add_argument(
        "--output", 
        type=str, 
        default=DEFAULT_OUTPUT_FILE, 
        help=f"Đường dẫn file dữ liệu sạch xuất ra (mặc định: {DEFAULT_OUTPUT_FILE})"
    )

    args = parser.parse_args()
    run_pipeline(input_path=args.input, output_path=args.output)
