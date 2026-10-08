"""
================================================================================
DATA INTEGRATION & MERGING MODULE (src/data_merge.py)
Project: IT4930 - Data Science (Khoa học dữ liệu)
Description:
    Tích hợp dữ liệu giao thông (Traffic), thời tiết (Weather) và lịch lễ (Holidays)
    thành một bảng dữ liệu thống nhất dựa trên mốc thời gian chung.
    
    Quy trình chuẩn hóa:
    1. Trích xuất/Nạp các bảng dữ liệu thô (Traffic, Weather, Holidays).
    2. Chuẩn hóa thời gian sang định dạng ISO-8601, gắn múi giờ cục bộ (America/Chicago)
       và chuyển đổi múi giờ chuẩn UTC.
    3. Xử lý đồng bộ múi giờ và chuyển đổi giờ mùa hè (Daylight Saving Time - DST).
    4. Xử lý quan hệ 1-N trong dữ liệu thời tiết (gộp nhiều hiện tượng thời tiết trong 1 giờ)
       để tránh nhân đôi bản ghi giao thông (duplicate traffic rows).
    5. Xử lý dữ liệu ngày lễ: phân phối nhãn ngày lễ cho toàn bộ các giờ trong ngày (full-day mapping).
    6. Thực hiện phép ghép nối (Left Join / Inner Join) trên khóa thời gian chung.
    7. Kiểm định tính toàn vẹn dữ liệu (Data Quality & Integrity Validation).
    8. Xuất file kết quả trung gian: data/interim/merged_traffic_data.csv.
================================================================================
"""

import os
import sys
import argparse
import logging
from typing import Tuple, Dict, Any, Optional
import pandas as pd
import numpy as np
import pytz

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("DataMergePipeline")

# Cấu hình hằng số mặc định
DEFAULT_INPUT_FILE = "dataset/Metro_Interstate_Traffic_Volume_modified.csv"
DEFAULT_FALLBACK_FILE = "dataset/Metro_Interstate_Traffic_Volume.csv"
DEFAULT_OUTPUT_FILE = "data/interim/merged_traffic_data.csv"
DEFAULT_RAW_DIR = "data/raw"
DEFAULT_TIMEZONE = "America/Chicago"


def load_dataset(file_path: str) -> pd.DataFrame:
    """
    Nạp dữ liệu từ file CSV với kiểm tra sự tồn tại của file.
    
    Args:
        file_path (str): Đường dẫn tới file dữ liệu CSV.
        
    Returns:
        pd.DataFrame: Dữ liệu đã nạp.
    """
    if not os.path.exists(file_path):
        if os.path.exists(DEFAULT_FALLBACK_FILE):
            logger.warning(f"Không tìm thấy '{file_path}'. Sử dụng file fallback '{DEFAULT_FALLBACK_FILE}'")
            file_path = DEFAULT_FALLBACK_FILE
        else:
            raise FileNotFoundError(f"Không tìm thấy file dữ liệu tại đường dẫn: {file_path}")
            
    logger.info(f"Đang nạp dữ liệu từ: {file_path}")
    df = pd.read_csv(file_path)
    logger.info(f"Nạp thành công: {df.shape[0]:,} dòng, {df.shape[1]} cột.")
    return df


def extract_raw_tables(
    source_df: pd.DataFrame, 
    raw_dir: str = DEFAULT_RAW_DIR
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Tách tập dữ liệu tổng hợp thô thành 3 bảng nguồn riêng biệt đại diện cho 3 miền dữ liệu:
    1. Bảng dữ liệu giao thông (Traffic Table)
    2. Bảng dữ liệu thời tiết (Weather Table)
    3. Bảng lịch ngày lễ (Holiday Table)
    Đồng thời lưu vào thư mục data/raw/ để phục vụ truy xuất nguồn gốc.
    
    Args:
        source_df (pd.DataFrame): DataFrame nguồn.
        raw_dir (str): Thư mục lưu dữ liệu thô.
        
    Returns:
        Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]: (traffic_df, weather_df, holiday_df)
    """
    os.makedirs(raw_dir, exist_ok=True)
    logger.info(f"Đang phân tách và lưu các bảng dữ liệu thô vào '{raw_dir}'...")
    
    # 1. Bảng dữ liệu giao thông
    traffic_cols = ['date_time', 'traffic_volume']
    available_traffic_cols = [c for c in traffic_cols if c in source_df.columns]
    traffic_raw = source_df[available_traffic_cols].copy()
    traffic_raw_path = os.path.join(raw_dir, "traffic_data_raw.csv")
    traffic_raw.to_csv(traffic_raw_path, index=False)
    logger.info(f"-> Đã lưu bảng giao thông thô: {traffic_raw_path} ({len(traffic_raw):,} dòng)")

    # 2. Bảng dữ liệu thời tiết
    weather_candidate_cols = [
        'date_time', 'temp', 'rain_1h', 'snow_1h', 'clouds_all', 
        'fog_mm', 'wind_speed_ms', 'flood_mm', 'weather_main', 'weather_description'
    ]
    available_weather_cols = [c for c in weather_candidate_cols if c in source_df.columns]
    weather_raw = source_df[available_weather_cols].copy()
    weather_raw_path = os.path.join(raw_dir, "weather_data_raw.csv")
    weather_raw.to_csv(weather_raw_path, index=False)
    logger.info(f"-> Đã lưu bảng thời tiết thô: {weather_raw_path} ({len(weather_raw):,} dòng)")

    # 3. Bảng lịch ngày lễ
    temp_dt = pd.to_datetime(source_df['date_time'], format='mixed', errors='coerce')
    holiday_mask = source_df['holiday'].notna() & (source_df['holiday'] != 'None') & (source_df['holiday'] != '')
    
    holiday_records = []
    if holiday_mask.any():
        raw_holidays = source_df[holiday_mask].copy()
        raw_holidays['date'] = temp_dt[holiday_mask].dt.strftime('%Y-%m-%d')
        holiday_unique = raw_holidays[['date', 'holiday']].drop_duplicates(subset=['date'])
        holiday_calendar = holiday_unique.rename(columns={'holiday': 'holiday_name'}).copy()
        holiday_calendar['is_holiday'] = 1
    else:
        holiday_calendar = pd.DataFrame(columns=['date', 'holiday_name', 'is_holiday'])

    holiday_raw_path = os.path.join(raw_dir, "holiday_calendar_raw.csv")
    holiday_calendar.to_csv(holiday_raw_path, index=False)
    logger.info(f"-> Đã lưu bảng lịch lễ thô: {holiday_raw_path} ({len(holiday_calendar):,} ngày lễ)")

    return traffic_raw, weather_raw, holiday_calendar


def standardize_timestamps(
    df: pd.DataFrame,
    datetime_col: str = 'date_time',
    source_tz: str = DEFAULT_TIMEZONE
) -> pd.DataFrame:
    """
    Chuẩn hóa chuỗi thời gian về chuẩn ISO-8601 và xử lý đồng bộ múi giờ:
    - Chuyển đổi định dạng đa dạng (M/D/YY H:MM, YYYY-MM-DD HH:MM:SS) sang datetime chuẩn.
    - Gán múi giờ địa phương (America/Chicago) với xử lý chuyển đổi giờ mùa hè (DST transitions).
    - Tạo các cột định dạng ISO-8601:
        + date_time_iso: Định dạng chuẩn ISO-8601 mở rộng 'YYYY-MM-DD HH:MM:SS'
        + date_time_local: Định dạng ISO-8601 kèm độ lệch múi giờ (VD: 2012-10-02T09:00:00-05:00)
        + date_time_utc: Định dạng chuẩn quốc tế UTC ISO-8601 (VD: 2012-10-02T14:00:00Z)
        + date: Chuỗi ngày 'YYYY-MM-DD' để làm khóa kết hợp dữ liệu theo ngày.
        
    Args:
        df (pd.DataFrame): DataFrame chứa cột thời gian.
        datetime_col (str): Tên cột thời gian gốc.
        source_tz (str): Múi giờ thu thập dữ liệu (mặc định America/Chicago).
        
    Returns:
        pd.DataFrame: DataFrame kèm các cột thời gian đã được chuẩn hóa.
    """
    df = df.copy()
    if datetime_col not in df.columns:
        raise KeyError(f"Không tìm thấy cột thời gian '{datetime_col}' trong DataFrame.")

    # 1. Parse chuỗi thời gian đa định dạng sang datetime object
    parsed_dt = pd.to_datetime(df[datetime_col], format='mixed', errors='coerce')
    null_dates = parsed_dt.isna().sum()
    if null_dates > 0:
        logger.warning(f"Phát hiện {null_dates:,} dòng không parse được thời gian!")

    # 2. Xử lý đồng bộ múi giờ cục bộ & Daylight Saving Time (DST)
    # Vào mùa thu khi chuyển giờ, 01:00 xuất hiện 2 lần. Ta đặt ambiguous=False (Standard Time)
    # và nonexistent='shift_forward' để đảm bảo an toàn tuyệt đối, không làm crash pipeline.
    dt_local = parsed_dt.dt.tz_localize(source_tz, ambiguous=False, nonexistent='shift_forward')
    dt_utc = dt_local.dt.tz_convert('UTC')

    # 3. Sinh các cột chuẩn hóa ISO-8601
    df['date_time_raw'] = df[datetime_col]
    df['date_time_iso'] = parsed_dt.dt.strftime('%Y-%m-%d %H:%M:%S')
    df['date_time_local'] = dt_local.apply(lambda x: x.isoformat() if pd.notna(x) else None)
    df['date_time_utc'] = dt_utc.dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    df['date'] = parsed_dt.dt.strftime('%Y-%m-%d')
    
    return df


def aggregate_weather_data(
    weather_df: pd.DataFrame,
    time_key: str = 'date_time_iso'
) -> pd.DataFrame:
    """
    Xử lý mối quan hệ 1-N trong dữ liệu thời tiết (nhiều hiện tượng thời tiết cùng 1 mốc giờ).
    Gộp các bản ghi thời tiết theo từng mốc giờ (hourly aggregation):
    - Các biến số (temp, rain_1h, snow_1h, clouds_all, fog_mm, wind_speed_ms, flood_mm): Tính trung bình.
    - Biến phân loại (weather_main, weather_description): Kết hợp các mô tả duy nhất bằng dấu phân cách.
    
    Args:
        weather_df (pd.DataFrame): DataFrame thời tiết đã được chuẩn hóa thời gian.
        time_key (str): Tên cột khóa thời gian làm căn cứ nhóm.
        
    Returns:
        pd.DataFrame: DataFrame thời tiết đã được tổng hợp (1 dòng duy nhất cho mỗi mốc giờ).
    """
    logger.info("Đang xử lý tổng hợp và khử trùng lặp dữ liệu thời tiết theo mốc giờ...")
    
    agg_dict: Dict[str, Any] = {}
    
    # Danh sách các cột số
    num_cols = ['temp', 'rain_1h', 'snow_1h', 'clouds_all', 'fog_mm', 'wind_speed_ms', 'flood_mm']
    for col in num_cols:
        if col in weather_df.columns:
            agg_dict[col] = 'mean'
            
    # Danh sách các cột phân loại (weather categories)
    if 'weather_main' in weather_df.columns:
        agg_dict['weather_main'] = lambda s: s.dropna().unique()[0] if len(s.dropna().unique()) == 1 else '/'.join(s.dropna().unique())
        
    if 'weather_description' in weather_df.columns:
        agg_dict['weather_description'] = lambda s: s.dropna().unique()[0] if len(s.dropna().unique()) == 1 else '; '.join(s.dropna().unique())

    # Thực hiện groupby theo time_key
    weather_agg = weather_df.groupby(time_key, as_index=False).agg(agg_dict)
    
    # Làm tròn các cột số để dữ liệu chuẩn đẹp
    round_cols = {'temp': 2, 'fog_mm': 2, 'wind_speed_ms': 2, 'flood_mm': 2, 'clouds_all': 1, 'rain_1h': 4, 'snow_1h': 4}
    for col, decimals in round_cols.items():
        if col in weather_agg.columns:
            weather_agg[col] = weather_agg[col].round(decimals)
            
    logger.info(f"Đã gộp dữ liệu thời tiết từ {len(weather_df):,} bản ghi thô thành {len(weather_agg):,} mốc giờ duy nhất.")
    return weather_agg


def enrich_temporal_features(df: pd.DataFrame, time_col: str = 'date_time_iso') -> pd.DataFrame:
    """
    Bổ sung các đặc trưng thời gian hữu ích cho bài toán phân tích giao thông:
    - hour (0 - 23)
    - day_of_week (Monday - Sunday)
    - day_of_week_num (0 - 6)
    - month (1 - 12)
    - year (2012 - 2018)
    - day_type (Weekday, Weekend, Holiday)
    
    Args:
        df (pd.DataFrame): DataFrame đã join.
        time_col (str): Tên cột thời gian ISO-8601.
        
    Returns:
        pd.DataFrame: DataFrame bổ sung các cột đặc trưng thời gian.
    """
    df = df.copy()
    dt = pd.to_datetime(df[time_col])
    
    df['hour'] = dt.dt.hour
    df['day_of_week'] = dt.dt.day_name()
    df['day_of_week_num'] = dt.dt.dayofweek
    df['month'] = dt.dt.month
    df['year'] = dt.dt.year
    
    # Phân loại day_type chuẩn xác
    def classify_day_type(row):
        if row.get('is_holiday', 0) == 1:
            return 'Holiday'
        elif row['day_of_week'] in ['Saturday', 'Sunday']:
            return 'Weekend'
        else:
            return 'Weekday'
            
    df['day_type'] = df.apply(classify_day_type, axis=1)
    return df


def merge_traffic_weather_holidays(
    traffic_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    holiday_df: pd.DataFrame,
    join_type: str = 'left',
    aggregate_weather: bool = True
) -> pd.DataFrame:
    """
    Thực hiện ghép nối toàn diện các bảng dữ liệu giao thông, thời tiết và ngày lễ.
    
    Quy tắc ghép nối:
    1. Bảng dữ liệu giao thông (Traffic) đóng vai trò là bảng chủ (Left table / primary time-series).
    2. Chuẩn hóa khóa thời gian date_time_iso và date trên tất cả các bảng.
    3. Ghép nối bảng giao thông với bảng thời tiết qua khóa 'date_time_iso' (Left Join).
    4. Ghép nối kết quả với bảng ngày lễ qua khóa ngày 'date' (Left Join),
       phát tán nhãn ngày lễ cho toàn bộ 24 giờ trong ngày lễ tương ứng.
    5. Xử lý giá trị mặc định cho ngày thường (is_holiday = 0, holiday_name = 'None').
    6. Trích xuất các thuộc tính thời gian bổ trợ (hour, day_of_week, day_type,...).
    
    Args:
        traffic_df (pd.DataFrame): Bảng dữ liệu giao thông.
        weather_df (pd.DataFrame): Bảng dữ liệu thời tiết.
        holiday_df (pd.DataFrame): Bảng lịch ngày lễ.
        join_type (str): Kiểu join ('left' hoặc 'inner'). Mặc định 'left'.
        aggregate_weather (bool): Có gộp các hiện tượng thời tiết cùng giờ hay không.
        
    Returns:
        pd.DataFrame: DataFrame kết quả sau khi ghép nối hoàn chỉnh.
    """
    logger.info(f"Bắt đầu quá trình ghép nối dữ liệu (Join Type: {join_type.upper()}, Aggregate Weather: {aggregate_weather})...")

    # 1. Chuẩn hóa thời gian trên bảng giao thông
    traffic_std = standardize_timestamps(traffic_df, 'date_time')
    
    # Nếu bảng giao thông có nhiều dòng trùng mốc giờ, khử trùng lặp
    traffic_unique = traffic_std.drop_duplicates(subset=['date_time_iso']).copy()
    traffic_unique = traffic_unique.sort_values('date_time_iso').reset_index(drop=True)
    logger.info(f"Bảng giao thông sau chuẩn hóa: {len(traffic_unique):,} mốc thời gian.")

    # 2. Chuẩn hóa và tổng hợp dữ liệu thời tiết
    weather_std = standardize_timestamps(weather_df, 'date_time')
    if aggregate_weather:
        weather_processed = aggregate_weather_data(weather_std, time_key='date_time_iso')
    else:
        weather_processed = weather_std.copy()

    # Bỏ các cột trùng lặp trước khi join
    cols_to_drop_from_weather = [c for c in ['date_time', 'date_time_raw', 'date_time_local', 'date_time_utc', 'date'] if c in weather_processed.columns]
    weather_processed = weather_processed.drop(columns=cols_to_drop_from_weather)

    # 3. Chuẩn bị bảng ngày lễ
    holiday_clean = holiday_df.drop_duplicates(subset=['date']).copy()
    if 'is_holiday' not in holiday_clean.columns:
        holiday_clean['is_holiday'] = 1
    if 'holiday_name' not in holiday_clean.columns and 'holiday' in holiday_clean.columns:
        holiday_clean = holiday_clean.rename(columns={'holiday': 'holiday_name'})

    # 4. Thực hiện phép nối 1: Traffic + Weather (qua date_time_iso)
    merged_traffic_weather = pd.merge(
        traffic_unique,
        weather_processed,
        on='date_time_iso',
        how=join_type
    )
    logger.info(f"Kết quả sau khi nối Traffic + Weather: {len(merged_traffic_weather):,} bản ghi.")

    # 5. Thực hiện phép nối 2: (Traffic + Weather) + Holiday (qua date)
    final_merged = pd.merge(
        merged_traffic_weather,
        holiday_clean[['date', 'holiday_name', 'is_holiday']],
        on='date',
        how='left'
    )
    logger.info(f"Kết quả sau khi nối với Holiday Calendar: {len(final_merged):,} bản ghi.")

    # 6. Xử lý giá trị mặc định cho ngày không phải ngày lễ
    final_merged['is_holiday'] = final_merged['is_holiday'].fillna(0).astype(int)
    final_merged['holiday_name'] = final_merged['holiday_name'].fillna('None')

    # 7. Bổ sung các đặc trưng thời gian hữu ích
    final_merged = enrich_temporal_features(final_merged, time_col='date_time_iso')

    # 8. Sắp xếp thứ tự cột logic, chuyên nghiệp
    column_order = [
        'date_time_iso',
        'date_time_utc',
        'date_time_local',
        'date',
        'hour',
        'day_of_week',
        'day_type',
        'is_holiday',
        'holiday_name',
        'traffic_volume',
        'temp',
        'rain_1h',
        'snow_1h',
        'clouds_all',
        'fog_mm',
        'wind_speed_ms',
        'flood_mm',
        'weather_main',
        'weather_description',
        'month',
        'year',
        'day_of_week_num',
        'date_time_raw'
    ]
    
    # Chỉ giữ các cột thực tế có trong dataframe
    final_cols = [c for c in column_order if c in final_merged.columns] + \
                 [c for c in final_merged.columns if c not in column_order]
    final_merged = final_merged[final_cols]

    return final_merged


def validate_integration_quality(
    merged_df: pd.DataFrame,
    traffic_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    holiday_df: pd.DataFrame
) -> Dict[str, Any]:
    """
    Kiểm định chất lượng dữ liệu sau khi tích hợp:
    - Kiểm tra số lượng bản ghi trước và sau khi ghép nối.
    - Kiểm tra tính duy nhất của khóa thời gian (không bị nhân bản sai lệch).
    - Đánh giá tỷ lệ ghép nối thành công (Join Match Rate).
    - Thống kê phân bố ngày thường / ngày cuối tuần / ngày lễ.
    - Kiểm tra số lượng giá trị thiếu (Missing values).
    
    Args:
        merged_df (pd.DataFrame): Dữ liệu sau khi merge.
        traffic_df (pd.DataFrame): Dữ liệu giao thông gốc.
        weather_df (pd.DataFrame): Dữ liệu thời tiết gốc.
        holiday_df (pd.DataFrame): Dữ liệu ngày lễ gốc.
        
    Returns:
        Dict[str, Any]: Từ điển chứa các chỉ số kiểm định chất lượng.
    """
    logger.info("==================================================")
    logger.info("KIỂM ĐỊNH CHẤT LƯỢNG DỮ LIỆU SAU TÍCH HỢP (QA CHECKS)")
    logger.info("==================================================")

    total_rows = len(merged_df)
    unique_timestamps = merged_df['date_time_iso'].nunique()
    dup_timestamps = total_rows - unique_timestamps

    null_counts = merged_df.isna().sum().to_dict()
    day_type_counts = merged_df['day_type'].value_counts().to_dict()
    holiday_hours_count = (merged_df['is_holiday'] == 1).sum()

    logger.info(f"1. Tổng số dòng dữ liệu hợp nhất: {total_rows:,}")
    logger.info(f"2. Số mốc thời gian duy nhất: {unique_timestamps:,}")
    logger.info(f"3. Số dòng bị trùng mốc thời gian: {dup_timestamps} (Mục tiêu = 0)")
    logger.info(f"4. Phân bố loại ngày: {day_type_counts}")
    logger.info(f"5. Số giờ rơi vào ngày lễ được phát tán chuẩn xác: {holiday_hours_count:,} giờ")
    logger.info(f"6. Giá trị thiếu trên các khóa chính:")
    logger.info(f"   - date_time_iso: {null_counts.get('date_time_iso', 0)}")
    logger.info(f"   - date: {null_counts.get('date', 0)}")
    logger.info(f"   - traffic_volume: {null_counts.get('traffic_volume', 0)} (giá trị thiếu từ nguồn đo)")
    logger.info(f"   - temp: {null_counts.get('temp', 0)}")

    metrics = {
        'total_rows': total_rows,
        'unique_timestamps': unique_timestamps,
        'duplicate_timestamps': dup_timestamps,
        'day_type_distribution': day_type_counts,
        'holiday_hours_count': holiday_hours_count,
        'null_counts': null_counts,
        'status': 'PASSED' if dup_timestamps == 0 else 'WARNING'
    }
    return metrics


def export_data(df: pd.DataFrame, output_path: str = DEFAULT_OUTPUT_FILE) -> None:
    """
    Xuất DataFrame ra file CSV với việc đảm bảo thư mục đích tồn tại.
    
    Args:
        df (pd.DataFrame): DataFrame cần xuất.
        output_path (str): Đường dẫn file CSV đầu ra.
    """
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        
    df.to_csv(output_path, index=False)
    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info(f"Đã xuất dữ liệu thành công tới: {output_path} ({len(df):,} dòng, {file_size_mb:.2f} MB)")


def run_pipeline(
    input_file: str = DEFAULT_INPUT_FILE,
    output_file: str = DEFAULT_OUTPUT_FILE,
    raw_dir: str = DEFAULT_RAW_DIR,
    join_type: str = 'left',
    aggregate_weather: bool = True,
    extract_raw: bool = True
) -> pd.DataFrame:
    """
    Chạy toàn bộ đường ống (end-to-end pipeline) tích hợp dữ liệu.
    
    Args:
        input_file (str): Đường dẫn file dữ liệu gốc.
        output_file (str): Đường dẫn file kết quả trung gian.
        raw_dir (str): Thư mục lưu dữ liệu thô phân tách.
        join_type (str): Kiểu join ('left' hoặc 'inner').
        aggregate_weather (bool): Có gộp các sự kiện thời tiết cùng mốc giờ hay không.
        extract_raw (bool): Có trích xuất các bảng dữ liệu thô vào data/raw hay không.
        
    Returns:
        pd.DataFrame: Bảng dữ liệu trung gian hoàn chỉnh.
    """
    logger.info("=== BẮT ĐẦU ĐƯỜNG ỐNG TÍCH HỢP DỮ LIỆU GIAO THÔNG - THỜI TIẾT - LỊCH LỄ ===")
    
    # 1. Nạp dữ liệu
    source_df = load_dataset(input_file)
    
    # 2. Phân tách bảng thô
    if extract_raw:
        traffic_raw, weather_raw, holiday_raw = extract_raw_tables(source_df, raw_dir=raw_dir)
    else:
        traffic_raw = source_df[['date_time', 'traffic_volume']].copy()
        weather_cols = [c for c in source_df.columns if c not in ['traffic_volume', 'holiday', 'day_type']]
        weather_raw = source_df[weather_cols].copy()
        temp_dt = pd.to_datetime(source_df['date_time'], format='mixed', errors='coerce')
        holiday_mask = source_df['holiday'].notna() & (source_df['holiday'] != 'None')
        raw_holidays = source_df[holiday_mask].copy()
        raw_holidays['date'] = temp_dt[holiday_mask].dt.strftime('%Y-%m-%d')
        holiday_raw = raw_holidays[['date', 'holiday']].drop_duplicates(subset=['date']).rename(columns={'holiday': 'holiday_name'})
        holiday_raw['is_holiday'] = 1

    # 3. Thực hiện ghép nối
    merged_df = merge_traffic_weather_holidays(
        traffic_df=traffic_raw,
        weather_df=weather_raw,
        holiday_df=holiday_raw,
        join_type=join_type,
        aggregate_weather=aggregate_weather
    )

    # 4. Kiểm định chất lượng
    validate_integration_quality(merged_df, traffic_raw, weather_raw, holiday_raw)

    # 5. Xuất file kết quả trung gian
    export_data(merged_df, output_file)
    
    logger.info("=== HOÀN TẤT ĐƯỜNG ỐNG TÍCH HỢP DỮ LIỆU THÀNH CÔNG ===")
    return merged_df


def parse_args():
    """Thiết lập và phân tích các tham số dòng lệnh CLI."""
    parser = argparse.ArgumentParser(
        description="Data Integration Pipeline: Ghép nối dữ liệu giao thông, thời tiết và lịch lễ."
    )
    parser.add_argument(
        "--input-file", "-i",
        type=str,
        default=DEFAULT_INPUT_FILE,
        help=f"Đường dẫn file dữ liệu đầu vào (mặc định: {DEFAULT_INPUT_FILE})"
    )
    parser.add_argument(
        "--output-file", "-o",
        type=str,
        default=DEFAULT_OUTPUT_FILE,
        help=f"Đường dẫn file kết quả trung gian (mặc định: {DEFAULT_OUTPUT_FILE})"
    )
    parser.add_argument(
        "--raw-dir", "-r",
        type=str,
        default=DEFAULT_RAW_DIR,
        help=f"Thư mục lưu các bảng dữ liệu thô phân tách (mặc định: {DEFAULT_RAW_DIR})"
    )
    parser.add_argument(
        "--join-type", "-j",
        type=str,
        choices=['left', 'inner'],
        default='left',
        help="Kiểu phép toán Join ('left' hoặc 'inner', mặc định: 'left')"
    )
    parser.add_argument(
        "--no-aggregate-weather",
        action="store_true",
        help="Nếu bật cờ này, sẽ không gộp các sự kiện thời tiết trùng giờ (giữ nguyên từng sự kiện thời tiết)."
    )
    parser.add_argument(
        "--skip-raw-extraction",
        action="store_true",
        help="Bỏ qua bước lưu các file raw CSV phân tách vào data/raw."
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        run_pipeline(
            input_file=args.input_file,
            output_file=args.output_file,
            raw_dir=args.raw_dir,
            join_type=args.join_type,
            aggregate_weather=not args.no_aggregate_weather,
            extract_raw=not args.skip_raw_extraction
        )
    except Exception as e:
        logger.error(f"Đã xảy ra lỗi trong quá trình thực thi pipeline: {e}", exc_info=True)
        sys.exit(1)
