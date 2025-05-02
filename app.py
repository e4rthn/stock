# -*- coding: utf-8 -*-
import json
import os
from datetime import datetime, timedelta, timezone # Standard library timezone
import pytz # For Bangkok timezone handling
import uuid
from math import floor
from collections import defaultdict # For grouping
from flask import Flask, render_template, request, redirect, url_for, flash
import calendar
from dateutil.relativedelta import relativedelta # For month calculations

# --- App Setup ---
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'โปรดเปลี่ยน_secret_key_นี้_final_version_01')

# --- ค่าคงที่ ---
SKU_FILE = 'skus.json'
INVENTORY_FILE = 'inventory.json'
PRICE_HISTORY_FILE = 'price_history.json' # ไฟล์ประวัติราคา
SALES_LOG_FILE = 'sales_log.json'         # ไฟล์บันทึกการขาย
ALLOWED_CATEGORIES = sorted(['หมู', 'ไก่', 'เนื้อ', 'อาหารทะเล', 'ผัก', 'ผลไม้', 'เครื่องดื่ม', 'อื่นๆ'])
BANGKOK_TZ = pytz.timezone('Asia/Bangkok')

# --- ย้าย HELPER FUNCTION มาไว้ระดับ TOP LEVEL ---
def format_iso_date(date_str, fmt='%Y-%m-%d %H:%M'):
    """Formats ISO date string (UTC) or datetime object to Bangkok time display format."""
    if not date_str: return "-"
    try:
        dt_utc = None
        if isinstance(date_str, datetime): # Handle if already datetime obj
            dt_utc = date_str
            if dt_utc.tzinfo is None:
                dt_utc = pytz.utc.localize(dt_utc) # Make timezone aware (UTC)
        elif isinstance(date_str, str):
             if date_str.endswith('Z'):
                dt_utc = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
             else:
                # Try parsing assuming it might have offset already
                try:
                    dt_utc = datetime.fromisoformat(date_str)
                    if dt_utc.tzinfo is None: # If parsed but naive, assume UTC
                        dt_utc = pytz.utc.localize(dt_utc)
                except ValueError: # If direct fromisoformat fails, assume naive UTC string needs parsing
                    # Attempt common formats, add more if needed
                    possible_formats = ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"]
                    dt_naive = None
                    for dt_fmt in possible_formats:
                        try:
                            dt_naive = datetime.strptime(date_str, dt_fmt)
                            break
                        except ValueError:
                            continue
                    if dt_naive is None: raise ValueError(f"Could not parse date string: {date_str}")
                    dt_utc = pytz.utc.localize(dt_naive)

        if dt_utc is None:
             raise TypeError("Input must be a datetime object or compatible ISO string")

        # Ensure dt_utc is timezone aware before converting
        if dt_utc.tzinfo is None or dt_utc.tzinfo.utcoffset(dt_utc) is None:
             print(f"Warning: Assuming UTC for naive datetime: {dt_utc}")
             dt_utc = pytz.utc.localize(dt_utc) # Force UTC if still naive

        dt_bkk = dt_utc.astimezone(BANGKOK_TZ)
        return dt_bkk.strftime(fmt)

    except (ValueError, TypeError, AttributeError) as e:
        print(f"Error formatting date '{date_str}': {e}")
        return str(date_str) # Return original string representation on error


# --- Context Processors (สำหรับ Template Helpers) ---
@app.context_processor
def inject_global_vars():
    """Inject global variables and helper functions needed in templates."""

    # format_time_remaining ยังคงอยู่ข้างในได้
    def format_time_remaining(expiry_date_input):
        """Calculates and formats remaining time from UTC expiry string or datetime."""
        if not expiry_date_input: return '<span class="text-muted">N/A</span>'
        try:
            now_utc = datetime.now(timezone.utc)
            expiry_dt_utc = None
            if isinstance(expiry_date_input, datetime):
                expiry_dt_utc = expiry_date_input
                if expiry_dt_utc.tzinfo is None: # Assume UTC if naive
                    expiry_dt_utc = pytz.utc.localize(expiry_dt_utc)
            elif isinstance(expiry_date_input, str):
                 if expiry_date_input.endswith('Z'):
                    expiry_dt_utc = datetime.fromisoformat(expiry_date_input.replace('Z', '+00:00'))
                 else:
                    # Try parsing assuming it might have offset already
                    try:
                         expiry_dt_utc = datetime.fromisoformat(expiry_date_input)
                         if expiry_dt_utc.tzinfo is None: expiry_dt_utc = pytz.utc.localize(expiry_dt_utc)
                    except ValueError: # If direct fromisoformat fails, assume naive UTC string needs parsing
                        possible_formats = ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"]
                        dt_naive = None
                        for dt_fmt in possible_formats:
                             try: dt_naive = datetime.strptime(expiry_date_input, dt_fmt); break
                             except ValueError: continue
                        if dt_naive is None: raise ValueError(f"Could not parse expiry date string: {expiry_date_input}")
                        expiry_dt_utc = pytz.utc.localize(dt_naive)
            else:
                raise TypeError("Input must be datetime object or ISO string")

            # Ensure expiry_dt_utc is timezone aware before comparison
            if expiry_dt_utc.tzinfo is None or expiry_dt_utc.tzinfo.utcoffset(expiry_dt_utc) is None:
                 print(f"Warning: Assuming UTC for naive expiry datetime: {expiry_dt_utc}")
                 expiry_dt_utc = pytz.utc.localize(expiry_dt_utc)

            delta = expiry_dt_utc - now_utc

            if delta.total_seconds() <= 0: return '<span class="badge bg-danger">หมดอายุ</span>'
            days = delta.days; hours = floor(delta.seconds / 3600); minutes = floor((delta.seconds % 3600) / 60)
            parts = []; text_class = "text-success"
            if delta <= timedelta(hours=12): text_class = "text-danger"
            elif delta <= timedelta(days=1, hours=1): text_class = "text-warning"
            elif delta <= timedelta(days=3): text_class = "text-warning"

            if days > 0: parts.append(f"{days} วัน")
            if hours > 0 and days < 3: parts.append(f"{hours} ชม.")
            if minutes > 0 and days == 0 and hours < 1: parts.append(f"{minutes} นาที")
            if not parts and delta.total_seconds() > 0: return '<span class="badge bg-danger">ใกล้หมดอายุมาก</span>'
            elif not parts: return '<span class="badge bg-danger">หมดอายุ</span>'

            remaining_str = " ".join(parts)
            if text_class == "text-danger": return f'<span class="badge bg-danger-subtle text-danger-emphasis">{remaining_str}</span>'
            elif text_class == "text-warning": return f'<span class="badge bg-warning-subtle text-warning-emphasis">{remaining_str}</span>'
            else: return f'<span class="text-success">{remaining_str}</span>'
        except (ValueError, TypeError, AttributeError) as e:
            print(f"Error calculating time remaining for '{expiry_date_input}': {e}")
            return '<span class="text-muted">Date Error</span>'

    return dict(
        current_year=datetime.now(BANGKOK_TZ).year,
        format_iso_date=format_iso_date, # ส่งฟังก์ชันที่ย้ายไปแล้วเข้ามาให้ Template
        format_time_remaining=format_time_remaining,
        now=datetime.now,
        BANGKOK_TZ=BANGKOK_TZ # ส่ง Timezone object ไปด้วย
    )

# --- Helper Functions: Data Loading/Saving ---
def load_data(filename):
    """โหลดข้อมูลจากไฟล์ JSON พร้อมจัดการกรณีไฟล์ไม่มี/ว่าง/เสีย"""
    default_data = None
    if filename == INVENTORY_FILE: default_data = {"batches": []}
    elif filename == PRICE_HISTORY_FILE: default_data = []
    elif filename == SKU_FILE: default_data = {}
    elif filename == SALES_LOG_FILE: default_data = [] # เพิ่ม default สำหรับ sales log
    else: default_data = {} # Default fallback

    if not os.path.exists(filename):
        print(f"File {filename} not found, creating/returning default.")
        try:
            # Create parent directory if it doesn't exist
            file_dir = os.path.dirname(filename)
            if file_dir and not os.path.exists(file_dir):
                 os.makedirs(file_dir)
            # Create empty file with default structure
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(default_data, f, indent=4, ensure_ascii=False)
            print(f"Created empty default file: {filename}")
        except IOError as e:
            print(f"Error creating default file {filename}: {e}")
            # ไม่ควร flash ตอนโหลด อาจจะแค่ log error
        except Exception as e:
            print(f"Unexpected error creating file {filename}: {e}")
        return default_data

    try:
        with open(filename, 'r', encoding='utf-8-sig') as f:
            content = f.read()
            if not content.strip():
                print(f"File {filename} is empty, returning default.")
                return default_data
            return json.loads(content)
    except (IOError) as e:
        print(f"Error loading data from {filename} (IOError): {e}")
        flash(f"เกิดข้อผิดพลาดในการอ่านไฟล์ {filename}", "danger")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {filename}: {e}")
        flash(f"ไฟล์ข้อมูล {filename} เสียหายหรือไม่ใช่รูปแบบ JSON ({e})", "danger")
        return None
    except Exception as e:
        print(f"Unexpected error loading {filename}: {e}")
        flash(f"เกิดข้อผิดพลาดไม่คาดคิดในการโหลด {filename}", "danger")
        return None

def save_data(filename, data):
    """บันทึกข้อมูลลงไฟล์ JSON"""
    try:
        # Create parent directory if it doesn't exist
        file_dir = os.path.dirname(filename)
        if file_dir and not os.path.exists(file_dir):
                os.makedirs(file_dir)
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except IOError as e:
        print(f"Error saving data to {filename}: {e}")
        flash(f"เกิดข้อผิดพลาดในการบันทึกข้อมูลลง {filename}", "danger")
    except Exception as e:
        print(f"Unexpected error saving {filename}: {e}")
        flash(f"เกิดข้อผิดพลาดไม่คาดคิดในการบันทึก {filename}", "danger")


# --- Price History Helpers ---
def load_price_history():
    """โหลดข้อมูลประวัติราคาจากไฟล์ JSON"""
    history = load_data(PRICE_HISTORY_FILE)
    if history is None: return []
    if not isinstance(history, list):
        print(f"Warning: Data in {PRICE_HISTORY_FILE} is not a list. Returning empty.")
        # ไม่ควร flash ตอนโหลด
        return []
    # Ensure sorted by date descending
    history.sort(key=lambda x: x.get('date', ''), reverse=True)
    return history

def save_price_history(history_data):
    """บันทึกข้อมูลประวัติราคาลงไฟล์ JSON"""
    if not isinstance(history_data, list):
        print(f"Error: Attempting to save invalid price history data (not a list).")
        flash("เกิดข้อผิดพลาด: ไม่สามารถบันทึกข้อมูลประวัติราคาได้", "danger")
        return
    history_data.sort(key=lambda x: x.get('date', ''), reverse=True)
    save_data(PRICE_HISTORY_FILE, history_data)

def add_price_entry(sku, price_b2c, price_b2b):
    """เพิ่มรายการราคาใหม่ลงใน history (ถ้ามีการเปลี่ยนแปลง)"""
    history = load_price_history()
    now_utc_iso = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')

    def safe_float(val):
        if val is None or val == '': return None
        try: return float(val)
        except (ValueError, TypeError): return None

    new_b2c_float = safe_float(price_b2c)
    new_b2b_float = safe_float(price_b2b)
    latest_entry = next((entry for entry in history if entry.get('sku') == sku), None)

    price_changed = True
    if latest_entry:
        latest_b2c = safe_float(latest_entry.get('price_b2c'))
        latest_b2b = safe_float(latest_entry.get('price_b2b'))
        if latest_b2c == new_b2c_float and latest_b2b == new_b2b_float:
            price_changed = False

    if price_changed:
        new_entry = {
            "sku": sku, "date": now_utc_iso,
            "price_b2c": new_b2c_float, "price_b2b": new_b2b_float
        }
        history.append(new_entry)
        save_price_history(history) # Save will re-sort
        print(f"Added new price entry for {sku}: B2C={new_b2c_float}, B2B={new_b2b_float}")
    else:
        print(f"Skipping price history entry for {sku}: Prices haven't changed.")

def get_current_prices(sku_list):
     """ดึงราคาล่าสุดของ SKU ที่ระบุจาก History"""
     history = load_price_history() # Sorted desc
     current_prices = {}
     processed_skus = set()
     target_skus = set(sku_list)

     for entry in history:
         sku = entry.get('sku')
         if not sku or sku not in target_skus: continue
         if sku not in processed_skus:
             current_prices[sku] = {
                 'price_b2c': entry.get('price_b2c'),
                 'price_b2b': entry.get('price_b2b')
             }
             processed_skus.add(sku)
             # Optimization: Stop early if all target SKUs are found
             if len(processed_skus) == len(target_skus):
                 break
     return current_prices

# --- Sales Log Helpers ---
def load_sales_log():
    """Loads sales transaction data from JSON file."""
    log_data = load_data(SALES_LOG_FILE)
    if log_data is None: return [] # Return empty list on load error
    if not isinstance(log_data, list):
        print(f"Warning: Data in {SALES_LOG_FILE} is not a list. Returning empty.")
        # ไม่ควร flash ตอนโหลด
        return []
    return log_data

def save_sales_log(log_data):
    """Saves sales transaction data to JSON file."""
    if not isinstance(log_data, list):
        print(f"Error: Attempting to save invalid sales log data (not a list).")
        flash("เกิดข้อผิดพลาด: ไม่สามารถบันทึกข้อมูลการขายได้", "danger")
        return
    # Sort descending before saving? Optional, maybe better to sort on read.
    # log_data.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    save_data(SALES_LOG_FILE, log_data)

# --- SKU Helpers ---
def load_skus():
    """โหลดข้อมูล SKU (ไม่รวมราคา) และตรวจสอบ/แปลงค่าเบื้องต้น"""
    skus = load_data(SKU_FILE)
    if skus is None: return {}
    if not isinstance(skus, dict):
        print(f"Warning: Data in {SKU_FILE} is not a dictionary. Returning empty.")
        return {}
    cleaned_skus = {}
    for sku_code, sku_data in skus.items():
        if isinstance(sku_data, dict):
            cleaned_data = sku_data.copy()
            def safe_int(val):
                # Improved safe_int to handle non-string inputs as well
                if val is None: return None
                if isinstance(val, int): return val
                if isinstance(val, float) and val.is_integer(): return int(val)
                if isinstance(val, str):
                    if val == '': return None
                    if val.isdigit(): return int(val)
                return None # Cannot safely convert

            rp_int = safe_int(cleaned_data.get('reorder_point'))
            cleaned_data['reorder_point'] = rp_int if rp_int is not None and rp_int >= 0 else None

            sl_int = safe_int(cleaned_data.get('shelf_life_days'))
            cleaned_data['shelf_life_days'] = sl_int if sl_int is not None and sl_int > 0 else None

            cleaned_data.pop('price_b2c', None); cleaned_data.pop('price_b2b', None)
            cleaned_skus[sku_code] = cleaned_data
        else: print(f"Warning: Invalid data structure for SKU '{sku_code}'. Skipping.")
    return cleaned_skus

def save_skus(skus_data):
    """บันทึกข้อมูล SKU (ที่ไม่ใช่ราคา)"""
    clean_data = {}
    if not isinstance(skus_data, dict):
        print("Error: Invalid data type passed to save_skus")
        return
    for sku, data in skus_data.items():
        if isinstance(data, dict): # Ensure data is a dict
            clean_copy = data.copy()
            clean_copy.pop('price_b2c', None); clean_copy.pop('price_b2b', None)
            clean_data[sku] = clean_copy
        else:
             print(f"Warning: Skipping invalid data for SKU '{sku}' in save_skus")
    save_data(SKU_FILE, clean_data)

# --- Inventory Helpers ---
def load_inventory():
    """โหลดข้อมูล Inventory และตรวจสอบโครงสร้างพื้นฐาน"""
    inventory_data = load_data(INVENTORY_FILE)
    if inventory_data is None: return {"batches": []}
    if not isinstance(inventory_data, dict) or 'batches' not in inventory_data or not isinstance(inventory_data.get('batches'), list):
        print(f"Warning: Data in {INVENTORY_FILE} has incorrect structure. Resetting.")
        flash(f"โครงสร้างข้อมูลใน {INVENTORY_FILE} ไม่ถูกต้อง, กำลังรีเซ็ต", "warning")
        inventory = {"batches": []}
        save_inventory(inventory) # Attempt to save the reset structure
    else: inventory = inventory_data
    return inventory

def save_inventory(inventory_data):
    """บันทึกข้อมูล Inventory"""
    if 'batches' not in inventory_data or not isinstance(inventory_data.get('batches'), list):
       print(f"Error: Attempting to save inventory data without valid 'batches' list.")
       flash("เกิดข้อผิดพลาด: ไม่สามารถบันทึกข้อมูลสต็อกได้", "danger")
       return
    save_data(INVENTORY_FILE, inventory_data)

# --- Helper Function: Update Batch Statuses ---
def update_batch_statuses(batches, skus_data):
    """อัปเดตสถานะ (location) ของแต่ละ Batch ตามวันหมดอายุและกฎ RTC."""
    now_utc = datetime.now(timezone.utc)
    updated_batches = []; something_changed = False
    for batch in batches:
        current_location = batch.get('location'); expiry_input = batch.get('expiry_date')
        sku = batch.get('sku'); qty = batch.get('quantity', 0)
        batch_id_short = batch.get('batch_id', 'N/A')[:8]; new_batch_data = batch.copy()
        # Skip if essential data missing, or already 'bad'
        if not expiry_input or not sku or sku not in skus_data or qty <= 0 or current_location == 'bad':
            updated_batches.append(new_batch_data); continue
        try:
            expiry_dt_utc = None
            # More robust date parsing for expiry
            if isinstance(expiry_input, datetime):
                expiry_dt_utc = expiry_input
            elif isinstance(expiry_input, str):
                if expiry_input.endswith('Z'):
                    expiry_dt_utc = datetime.fromisoformat(expiry_input.replace('Z', '+00:00'))
                else:
                     try: # Attempt direct ISO format parse first
                        expiry_dt_utc = datetime.fromisoformat(expiry_input)
                     except ValueError: # Fallback to known formats if needed
                         possible_formats = ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"]
                         dt_naive = None
                         for fmt in possible_formats:
                            try: dt_naive = datetime.strptime(expiry_input, fmt); break
                            except ValueError: pass
                         if dt_naive is None: raise ValueError(f"Unparseable date: {expiry_input}")
                         expiry_dt_utc = dt_naive # Will be localized below

            if expiry_dt_utc is None: raise ValueError("Invalid expiry date type")

            # Ensure timezone aware (assume UTC if naive)
            if expiry_dt_utc.tzinfo is None: expiry_dt_utc = pytz.utc.localize(expiry_dt_utc)

            time_until_expiry = expiry_dt_utc - now_utc; new_location = current_location
            # Rules for location change
            if time_until_expiry <= timedelta(0): new_location = 'bad'
            elif current_location == 'back_stock': pass # No auto change from back_stock
            elif time_until_expiry <= timedelta(hours=12, minutes=30) and current_location in ['display', 'rtc1']: new_location = 'rtc2'
            elif time_until_expiry <= timedelta(days=1, hours=1) and current_location == 'display': new_location = 'rtc1'
            # Update if changed
            if new_location != current_location:
                print(f"Status Change: Batch {batch_id_short} ({sku}) {current_location} -> {new_location}")
                new_batch_data['location'] = new_location; something_changed = True
            updated_batches.append(new_batch_data)
        except (ValueError, TypeError, AttributeError) as e:
            print(f"Error parsing date or processing batch {batch_id_short}, SKU {sku}. Error: {e}")
            updated_batches.append(new_batch_data) # Keep original batch on error
    return updated_batches, something_changed

# --- Date Range Helper for Sales Report ---
def get_date_range(period_str, start_date_str=None, end_date_str=None):
    """Calculates UTC start and end datetimes based on period string or custom dates."""
    now_bkk = datetime.now(BANGKOK_TZ)
    start_utc, end_utc = None, None

    try:
        if period_str == 'today':
            start_dt_bkk = BANGKOK_TZ.localize(datetime.combine(now_bkk.date(), datetime.min.time()))
            end_dt_bkk = BANGKOK_TZ.localize(datetime.combine(now_bkk.date(), datetime.max.time().replace(microsecond=0)))
            start_utc = start_dt_bkk.astimezone(pytz.utc)
            end_utc = end_dt_bkk.astimezone(pytz.utc)
        elif period_str == 'this_week':
            today_weekday = now_bkk.date().weekday() # Monday is 0, Sunday is 6
            start_of_week = now_bkk.date() - timedelta(days=today_weekday)
            end_of_week = start_of_week + timedelta(days=6)
            start_dt_bkk = BANGKOK_TZ.localize(datetime.combine(start_of_week, datetime.min.time()))
            end_dt_bkk = BANGKOK_TZ.localize(datetime.combine(end_of_week, datetime.max.time().replace(microsecond=0)))
            start_utc = start_dt_bkk.astimezone(pytz.utc)
            end_utc = end_dt_bkk.astimezone(pytz.utc)
        elif period_str == 'this_month':
            start_of_month = now_bkk.date().replace(day=1)
            # Find last day of month correctly using relativedelta
            next_month = start_of_month + relativedelta(months=1)
            last_day_of_month = next_month - timedelta(days=1)
            start_dt_bkk = BANGKOK_TZ.localize(datetime.combine(start_of_month, datetime.min.time()))
            end_dt_bkk = BANGKOK_TZ.localize(datetime.combine(last_day_of_month, datetime.max.time().replace(microsecond=0)))
            start_utc = start_dt_bkk.astimezone(pytz.utc)
            end_utc = end_dt_bkk.astimezone(pytz.utc)
        elif period_str == 'custom' and start_date_str and end_date_str:
             start_date_naive = datetime.strptime(start_date_str, '%Y-%m-%d').date()
             end_date_naive = datetime.strptime(end_date_str, '%Y-%m-%d').date()
             if start_date_naive > end_date_naive: # Swap if start is after end
                 start_date_naive, end_date_naive = end_date_naive, start_date_naive
             start_dt_bkk = BANGKOK_TZ.localize(datetime.combine(start_date_naive, datetime.min.time()))
             end_dt_bkk = BANGKOK_TZ.localize(datetime.combine(end_date_naive, datetime.max.time().replace(microsecond=0)))
             start_utc = start_dt_bkk.astimezone(pytz.utc)
             end_utc = end_dt_bkk.astimezone(pytz.utc)
        # 'all' case is handled by returning None, None implicitly if no other case matches

    except (ValueError, TypeError) as e:
        print(f"Error parsing date range for period '{period_str}': {e}")
        flash("รูปแบบวันที่สำหรับช่วงที่กำหนดเองไม่ถูกต้อง", "warning")
        return None, None # Indicate error

    return start_utc, end_utc


# --- Routes ---

@app.route('/', endpoint='index')
def index():
    inventory = load_inventory(); skus_data = load_skus();
    if skus_data is None or inventory is None: # Handle load errors
        flash("เกิดข้อผิดพลาดร้ายแรงในการโหลดข้อมูลหลัก", "danger")
        # Render empty but valid page structure
        return render_template('index.html', inventory_batches=[], skus_data={}, location_configs={}, allowed_categories=[])
    batches = inventory.get('batches', [])
    updated_batches, changed = update_batch_statuses(batches, skus_data)
    if changed:
        inventory['batches'] = updated_batches; save_inventory(inventory); batches_to_process = updated_batches
    else:
        batches_to_process = batches
    location_configs = { 'display': {'title': 'หน้าร้าน', 'border_status_class': 'status-display', 'badge_class': 'text-bg-primary', 'icon': 'bi-shop'}, 'back_stock': {'title': 'หลังร้าน', 'border_status_class': 'status-back-stock', 'badge_class': 'text-bg-secondary', 'icon': 'bi-boxes'}, 'rtc1': {'title': 'RTC-1', 'border_status_class': 'status-rtc1', 'badge_class': 'text-bg-warning', 'icon': 'bi-alarm'}, 'rtc2': {'title': 'RTC-2', 'border_status_class': 'status-rtc2', 'badge_class': 'text-bg-danger', 'icon': 'bi-alarm-fill'}, 'bad': {'title': 'หมดอายุ', 'border_status_class': 'status-bad', 'badge_class': 'text-bg-dark', 'icon': 'bi-x-octagon-fill'} }
    location_order = ['display', 'back_stock', 'rtc1', 'rtc2', 'bad']; location_sort_key = {loc: i for i, loc in enumerate(location_order)}
    valid_batches = [b for b in batches_to_process if b.get('quantity', 0) > 0]
    valid_batches.sort(key=lambda b: ( location_sort_key.get(b.get('location'), 99), b.get('sku', ''), b.get('expiry_date', '') ))
    return render_template('index.html', inventory_batches=valid_batches, skus_data=skus_data, location_configs=location_configs, allowed_categories=ALLOWED_CATEGORIES )

# --- SKU Management Routes ---
@app.route('/skus', endpoint='list_skus')
def list_skus():
    skus_data = load_skus()
    if skus_data is None: return render_template('list_skus.html', skus={}, categories=ALLOWED_CATEGORIES) # Handle error
    current_prices = get_current_prices(list(skus_data.keys()))
    sorted_skus = dict(sorted(skus_data.items(), key=lambda item: item[1].get('name', item[0])))
    display_data = {}
    for sku, data in sorted_skus.items():
        display_data[sku] = data.copy()
        prices = current_prices.get(sku, {})
        display_data[sku]['price_b2c'] = prices.get('price_b2c')
        display_data[sku]['price_b2b'] = prices.get('price_b2b')
    return render_template('list_skus.html', skus=display_data, categories=ALLOWED_CATEGORIES)

@app.route('/add_sku', methods=['GET', 'POST'], endpoint='add_sku')
def add_sku():
    render_context = { 'categories': ALLOWED_CATEGORIES, 'errors': {}, 'form_data': {} }
    if request.method == 'POST':
        form_data = request.form.to_dict(); render_context['form_data'] = form_data
        sku_code = form_data.get('sku', '').strip().upper(); name = form_data.get('name', '').strip(); category = form_data.get('category', '').strip(); shelf_life_str = form_data.get('shelf_life_days', '').strip(); reorder_point_str = form_data.get('reorder_point', '').strip(); price_b2c_str = form_data.get('price_b2c', '').strip(); price_b2b_str = form_data.get('price_b2b', '').strip()
        errors = {}
        def safe_int(val):
            if val is None: return None
            if isinstance(val, int): return val
            if isinstance(val, float) and val.is_integer(): return int(val)
            if isinstance(val, str):
                if val == '': return None
                if val.isdigit(): return int(val)
            return None

        # --- Validation ---
        if not sku_code: errors['sku'] = "ต้องระบุ SKU Code"
        if not name: errors['name'] = "ต้องระบุชื่อสินค้า"
        if not category: errors['category'] = "ต้องเลือกประเภทสินค้า"
        elif category not in ALLOWED_CATEGORIES: errors['category'] = "ประเภทสินค้าไม่ถูกต้อง"
        shelf_life_days = None; sl_int = safe_int(shelf_life_str)
        if not shelf_life_str: errors['shelf_life_days'] = "ต้องระบุอายุสินค้า (วัน)"
        elif sl_int is None: errors['shelf_life_days'] = "อายุสินค้าต้องเป็นตัวเลข"
        elif sl_int <= 0: errors['shelf_life_days'] = "อายุสินค้าต้องเป็นจำนวนเต็มบวก"
        else: shelf_life_days = sl_int
        reorder_point = None; rp_int = safe_int(reorder_point_str)
        if reorder_point_str and rp_int is None: errors['reorder_point'] = "จุดสั่งซื้อต้องเป็นตัวเลข"
        elif rp_int is not None and rp_int < 0: errors['reorder_point'] = "จุดสั่งซื้อต้องไม่ติดลบ"
        else: reorder_point = rp_int # Allows None
        price_b2c = None
        if price_b2c_str:
            try: p_val = float(price_b2c_str); price_b2c = p_val if p_val >= 0 else None
            except ValueError: errors['price_b2c'] = "รูปแบบราคา B2C ไม่ถูกต้อง"
            if price_b2c is None and 'price_b2c' not in errors: errors['price_b2c'] = "ราคา B2C ต้องไม่ติดลบ"
        price_b2b = None
        if price_b2b_str:
            try: p_val = float(price_b2b_str); price_b2b = p_val if p_val >= 0 else None
            except ValueError: errors['price_b2b'] = "รูปแบบราคา B2B ไม่ถูกต้อง"
            if price_b2b is None and 'price_b2b' not in errors: errors['price_b2b'] = "ราคา B2B ต้องไม่ติดลบ"
        # --- End Validation ---
        if not errors:
            skus_data_check = load_skus()
            if skus_data_check is not None and sku_code in skus_data_check: errors['sku'] = f"SKU Code '{sku_code}' มีอยู่แล้ว"
            elif skus_data_check is None: errors['general'] = "เกิดข้อผิดพลาดในการโหลดข้อมูล SKU เดิม" # Load error check

        render_context['errors'] = errors
        if errors:
            for field, msg in errors.items(): flash(f"{field.replace('_', ' ').title()}: {msg}", "warning")
            return render_template('add_sku.html', **render_context)

        # --- Save Data ---
        new_sku_data = {'name': name, 'category': category, 'shelf_life_days': shelf_life_days, 'reorder_point': reorder_point }
        skus_data = load_skus()
        if skus_data is None: flash("ผิดพลาด: ไม่สามารถโหลดข้อมูล SKU เพื่อบันทึกได้", "danger"); return render_template('add_sku.html', **render_context) # Check again before saving
        skus_data[sku_code] = new_sku_data
        save_skus(skus_data)
        add_price_entry(sku_code, price_b2c, price_b2b) # Add price history
        flash(f"เพิ่ม SKU '{name}' ({sku_code}) เรียบร้อยแล้ว", "success"); return redirect(url_for('list_skus'))
    else: # GET
        return render_template('add_sku.html', **render_context)

@app.route('/edit_sku/<sku>', methods=['GET', 'POST'], endpoint='edit_sku')
def edit_sku(sku):
    skus_data = load_skus()
    if skus_data is None: flash("ผิดพลาด: ไม่สามารถโหลดข้อมูล SKU ได้", "danger"); return redirect(url_for('list_skus'))
    if sku not in skus_data: flash(f"ไม่พบ SKU Code: {sku}", "danger"); return redirect(url_for('list_skus'))
    original_sku_data = skus_data[sku]

    if request.method == 'POST':
        form_data = request.form.to_dict(); errors = {}
        def safe_int(val):
            if val is None: return None
            if isinstance(val, int): return val
            if isinstance(val, float) and val.is_integer(): return int(val)
            if isinstance(val, str):
                if val == '': return None
                if val.isdigit(): return int(val)
            return None
        # --- Validation ---
        name = form_data.get('name', '').strip(); category = form_data.get('category', '').strip(); shelf_life_str = form_data.get('shelf_life_days', '').strip(); reorder_point_str = form_data.get('reorder_point', '').strip(); price_b2c_str = form_data.get('price_b2c', '').strip(); price_b2b_str = form_data.get('price_b2b', '').strip()
        if not name: errors['name'] = "ต้องระบุชื่อสินค้า"
        if not category: errors['category'] = "ต้องเลือกประเภทสินค้า"
        elif category not in ALLOWED_CATEGORIES: errors['category'] = "ประเภทสินค้าไม่ถูกต้อง"
        shelf_life_days = None; sl_int = safe_int(shelf_life_str)
        if not shelf_life_str: errors['shelf_life_days'] = "ต้องระบุอายุสินค้า (วัน)"
        elif sl_int is None: errors['shelf_life_days'] = "อายุสินค้าต้องเป็นตัวเลข"
        elif sl_int <= 0: errors['shelf_life_days'] = "อายุสินค้าต้องเป็นจำนวนเต็มบวก"
        else: shelf_life_days = sl_int
        reorder_point = None; rp_int = safe_int(reorder_point_str)
        if reorder_point_str and rp_int is None: errors['reorder_point'] = "จุดสั่งซื้อต้องเป็นตัวเลข"
        elif rp_int is not None and rp_int < 0: errors['reorder_point'] = "จุดสั่งซื้อต้องไม่ติดลบ"
        else: reorder_point = rp_int
        price_b2c = None
        if price_b2c_str:
            try: p_val = float(price_b2c_str); price_b2c = p_val if p_val >= 0 else None
            except ValueError: errors['price_b2c'] = "รูปแบบราคา B2C ไม่ถูกต้อง"
            if price_b2c is None and 'price_b2c' not in errors: errors['price_b2c'] = "ราคา B2C ต้องไม่ติดลบ"
        price_b2b = None
        if price_b2b_str:
            try: p_val = float(price_b2b_str); price_b2b = p_val if p_val >= 0 else None
            except ValueError: errors['price_b2b'] = "รูปแบบราคา B2B ไม่ถูกต้อง"
            if price_b2b is None and 'price_b2b' not in errors: errors['price_b2b'] = "ราคา B2B ต้องไม่ติดลบ"
        # --- End Validation ---

        if errors:
            flash("กรุณาแก้ไขข้อผิดพลาดในฟอร์ม", "warning")
            current_prices = get_current_prices([sku])
            # Prepare data to show in form: original non-price + current price
            sku_display_data_on_error = original_sku_data.copy()
            sku_display_data_on_error.update(current_prices.get(sku, {}))
            # Pass back submitted form data separately
            return render_template('edit_sku.html', sku_code=sku, sku_data=sku_display_data_on_error, form_data=form_data, categories=ALLOWED_CATEGORIES, errors=errors)
        else:
            # Validation passed: Update non-price data
            # Reload skus_data before modifying and saving for safety
            skus_data = load_skus()
            if skus_data is None:
                flash("ผิดพลาดร้ายแรง: ไม่สามารถโหลดข้อมูล SKU เพื่อบันทึกได้", "danger")
                return redirect(url_for('list_skus')) # Redirect if cannot load
            if sku not in skus_data: # Double check SKU still exists
                flash(f"ผิดพลาด: ไม่พบ SKU {sku} แล้ว", "warning")
                return redirect(url_for('list_skus'))

            skus_data[sku]['name'] = name; skus_data[sku]['category'] = category
            skus_data[sku]['shelf_life_days'] = shelf_life_days; skus_data[sku]['reorder_point'] = reorder_point
            save_skus(skus_data)
            # Add new price entry using validated prices from form
            add_price_entry(sku, price_b2c, price_b2b)
            flash(f"แก้ไขข้อมูล SKU '{sku}' เรียบร้อยแล้ว", "success"); return redirect(url_for('list_skus'))
    else: # GET request
        current_prices = get_current_prices([sku])
        # Prepare data to show in form: original non-price + current price
        sku_display_data = original_sku_data.copy()
        sku_display_data.update(current_prices.get(sku, {}))
        return render_template('edit_sku.html', sku_code=sku, sku_data=sku_display_data, form_data=None, categories=ALLOWED_CATEGORIES, errors={})

@app.route('/delete_sku/<sku>', methods=['POST'], endpoint='delete_sku')
def delete_sku(sku):
    skus_data = load_skus(); inventory = load_inventory()
    if skus_data is None or inventory is None: flash("ผิดพลาด: โหลดข้อมูลไม่ได้", "danger"); return redirect(url_for('list_skus'))
    sku_in_active_inventory = any(b.get('sku') == sku and b.get('quantity', 0) > 0 and b.get('location') != 'bad' for b in inventory.get('batches', []))
    if sku not in skus_data: flash(f"ไม่พบ SKU Code: {sku} ที่จะลบ", "warning"); return redirect(url_for('list_skus'))
    if sku_in_active_inventory: flash(f"ไม่สามารถลบ SKU '{sku}' ได้ เนื่องจากยังมีสต็อกสินค้าคงเหลือ", "danger"); return redirect(url_for('list_skus'))
    deleted_name = skus_data.pop(sku).get('name', sku); save_skus(skus_data)
    # Consider if price history for deleted SKU should also be removed or archived
    flash(f"ลบ SKU '{deleted_name}' ({sku}) เรียบร้อยแล้ว", "success"); return redirect(url_for('list_skus'))

# --- Inventory Management Routes ---
@app.route('/add_stock', methods=['GET', 'POST'], endpoint='add_stock')
def add_stock():
    skus_data = load_skus()
    if skus_data is None: flash("ผิดพลาด: โหลดข้อมูล SKU ไม่ได้", "danger"); return redirect(url_for('list_skus'))
    if not skus_data: flash("ยังไม่มีข้อมูล SKU กรุณาเพิ่ม SKU ก่อน", "warning"); return redirect(url_for('add_sku'))
    today_bkk_str = datetime.now(BANGKOK_TZ).strftime('%Y-%m-%d')
    render_context = {'skus': skus_data, 'current_date': today_bkk_str, 'errors': {}, 'form_data': {'arrival_date': today_bkk_str}}
    if request.method == 'POST':
        form_data = request.form.to_dict(); render_context['form_data'] = form_data
        sku = form_data.get('sku'); quantity_str = form_data.get('quantity'); arrival_date_str = form_data.get('arrival_date'); errors = {}
        selected_sku_info = skus_data.get(sku)
        if not sku: errors['sku'] = "ต้องเลือก SKU"
        elif not selected_sku_info: errors['sku'] = f"ไม่พบข้อมูลสำหรับ SKU Code: {sku}"
        quantity = 0
        if not quantity_str: errors['quantity'] = "ต้องระบุจำนวน"
        else:
            try:
                quantity = int(quantity_str)
                if quantity <= 0:
                    errors['quantity'] = "จำนวนต้องเป็นเลขบวก"
            except ValueError:
                errors['quantity'] = "จำนวนต้องเป็นตัวเลข"
        arrival_dt_utc = None
        if not arrival_date_str: errors['arrival_date'] = "ต้องระบุวันที่รับสินค้า"
        else:
            try:
                arrival_date_naive = datetime.strptime(arrival_date_str, '%Y-%m-%d').date()
                # Localize using Bangkok time zone, then convert to UTC
                arrival_dt_bkk = BANGKOK_TZ.localize(datetime.combine(arrival_date_naive, datetime.min.time()))
                arrival_dt_utc = arrival_dt_bkk.astimezone(pytz.utc)
                # Check if arrival date is in the future (compare dates only)
                if arrival_date_naive > datetime.now(BANGKOK_TZ).date():
                    errors['arrival_date'] = "วันที่รับสินค้าต้องไม่ใช่วันในอนาคต"
            except ValueError:
                errors['arrival_date'] = "รูปแบบวันที่รับสินค้าไม่ถูกต้อง (YYYY-MM-DD)"
            except OverflowError:
                 errors['arrival_date'] = "วันที่ระบุไม่ถูกต้อง หรืออยู่นอกขอบเขต"


        shelf_life_days = None
        if not errors and selected_sku_info:
            shelf_life_days = selected_sku_info.get('shelf_life_days')
            if not shelf_life_days: errors['sku'] = f"SKU '{sku}' ไม่ได้กำหนดอายุสินค้า"
        render_context['errors'] = errors
        if errors:
             for field, msg in errors.items(): flash(f"{field.replace('_', ' ').title()}: {msg}", "warning");
             render_context['skus'] = skus_data # Pass skus back
             return render_template('add_stock.html', **render_context)
        try:
            if arrival_dt_utc is None or shelf_life_days is None:
                # This should ideally be caught by validation, but double-check
                raise ValueError("Arrival date or shelf life is missing for expiry calculation")
            expiry_date_utc = arrival_dt_utc + timedelta(days=shelf_life_days); batch_id = str(uuid.uuid4())
            new_batch = {
                "batch_id": batch_id, "sku": sku, "quantity": quantity, "location": "back_stock",
                "arrival_date": arrival_dt_utc.isoformat(timespec='seconds').replace('+00:00', 'Z'),
                "expiry_date": expiry_date_utc.isoformat(timespec='seconds').replace('+00:00', 'Z')
            }
            inventory = load_inventory();
            if inventory is None: raise IOError("Failed to load inventory to add stock")
            inventory['batches'].append(new_batch); save_inventory(inventory); sku_name = selected_sku_info.get('name', sku)
            flash(f"เพิ่มสต็อก '{sku_name}' จำนวน {quantity} ชิ้น เรียบร้อยแล้ว", "success"); return redirect(url_for('index'))
        except Exception as e:
             print(f"Error creating batch for {sku}: {e}")
             flash(f"เกิดข้อผิดพลาดในการสร้าง Batch: {e}", "danger")
             render_context['skus'] = skus_data # Pass skus back
             return render_template('add_stock.html', **render_context)
    else: # GET request
        render_context['skus'] = skus_data; return render_template('add_stock.html', **render_context)

@app.route('/move_to_display', methods=['GET', 'POST'], endpoint='move_to_display')
def move_to_display():
    skus_data = load_skus(); inventory = load_inventory()
    if skus_data is None or inventory is None: flash("ผิดพลาด: โหลดข้อมูลไม่ได้", "danger"); return redirect(url_for('index'))
    batches = inventory.get('batches', [])
    # --- Filter for back_stock batches ---
    back_stock_batches = [b for b in batches if b.get('location') == 'back_stock' and b.get('quantity', 0) > 0];
    available_skus_in_back = {}; aggregated_back_stock = {}
    if back_stock_batches:
        # Sort by expiry (FIFO)
        back_stock_batches.sort(key=lambda b: (b.get('expiry_date', ''), b.get('arrival_date', '')))
        unique_skus = sorted(list(set(b['sku'] for b in back_stock_batches)));
        for sku_code in unique_skus:
            if sku_code in skus_data:
                 available_skus_in_back[sku_code] = skus_data[sku_code]
                 aggregated_back_stock[sku_code] = sum(b['quantity'] for b in back_stock_batches if b['sku'] == sku_code)
            else: print(f"!!! Warning: SKU '{sku_code}' in back stock but not in skus.json !!!")

    # --- Prepare context for template ---
    render_context = {'skus': available_skus_in_back, 'back_stock_agg': aggregated_back_stock, 'errors': {}, 'form_data': {}}

    # --- Handle POST request ---
    if request.method == 'POST':
        form_data = request.form.to_dict(); render_context['form_data'] = form_data
        sku_to_move = form_data.get('sku'); quantity_str = form_data.get('quantity'); errors = {}
        # --- Validation ---
        if not sku_to_move: errors['sku'] = "ต้องเลือก SKU"
        elif sku_to_move not in available_skus_in_back: errors['sku'] = f"ไม่พบ SKU '{sku_to_move}' ในสต็อกหลังร้าน"
        requested_quantity = 0; total_available_for_sku = aggregated_back_stock.get(sku_to_move, 0)
        if not quantity_str: errors['quantity'] = "ต้องระบุจำนวน"
        else:
            try:
                requested_quantity = int(quantity_str)
                if requested_quantity <= 0:
                    errors['quantity'] = "จำนวนต้องเป็นเลขบวก"
                elif sku_to_move in aggregated_back_stock and requested_quantity > total_available_for_sku:
                    errors['quantity'] = f"มีแค่ {total_available_for_sku} ชิ้น"
            except ValueError:
                errors['quantity'] = "จำนวนต้องเป็นตัวเลข"
        render_context['errors'] = errors
        if errors:
            for field, msg in errors.items(): flash(f"{field.replace('_', ' ').title()}: {msg}", "warning");
            render_context['skus'] = available_skus_in_back; render_context['back_stock_agg'] = aggregated_back_stock
            return render_template('move_to_display.html', **render_context)

        # --- If Validation Passed: Process the move ---
        current_inventory = load_inventory();
        if current_inventory is None: flash("ผิดพลาด: โหลดสต็อกไม่ได้ก่อนทำการย้าย", "danger"); return render_template('move_to_display.html', **render_context)
        all_current_batches = current_inventory.get('batches', [])

        quantity_left_to_move = requested_quantity; moved_count = 0; indices_to_update = {}; batches_to_add = []
        # Find relevant source batches and sort FIFO
        source_batches_info = sorted([(i, b) for i, b in enumerate(all_current_batches) if b.get('sku') == sku_to_move and b.get('location') == 'back_stock' and b.get('quantity', 0) > 0], key=lambda item: (item[1].get('expiry_date', ''), item[1].get('arrival_date', '')))

        # Loop through source batches to fulfill request
        # **** START OF LOOP ****
        for original_index, batch_data in source_batches_info:
            # Check if we still need to move items
            if quantity_left_to_move <= 0:
                break; # Exit loop if request is fulfilled

            available_in_this_batch = batch_data['quantity']
            # Determine how much to move from THIS specific batch
            move_from_this_batch = min(available_in_this_batch, quantity_left_to_move) # Assignment

            # Process only if moving a positive amount from this batch
            if move_from_this_batch > 0:
                # Calculate new quantity for the original batch
                new_quantity_original = available_in_this_batch - move_from_this_batch
                # Store the index and the NEW quantity for update/removal later
                indices_to_update[original_index] = new_quantity_original

                # Create a new batch object for the 'display' location
                new_display_batch = {
                    "batch_id": str(uuid.uuid4()), # Generate a new unique ID
                    "sku": sku_to_move,
                    "quantity": move_from_this_batch, # The amount being moved
                    "location": "display",
                    "arrival_date": batch_data['arrival_date'], # Preserve original dates
                    "expiry_date": batch_data['expiry_date']
                 }
                batches_to_add.append(new_display_batch) # Add to list for later addition

                # Update counters
                moved_count += move_from_this_batch
                quantity_left_to_move -= move_from_this_batch
        # **** END OF LOOP ****

        # --- Update Inventory if items were moved ---
        if moved_count > 0:
            final_batches = [];
            # Rebuild the batch list correctly
            for i, batch in enumerate(all_current_batches):
                 if i in indices_to_update: # Check if this batch index was modified
                      new_qty = indices_to_update[i] # Get the updated quantity
                      if new_qty > 0: # If items remain in the source batch
                           updated_batch = batch.copy();
                           updated_batch['quantity'] = new_qty;
                           final_batches.append(updated_batch)
                      # else: If new_qty is 0, the source batch is depleted, so we don't add it back
                 else: # If this batch was not a source batch
                      final_batches.append(batch) # Keep it as is
            # Add the newly created display batches to the final list
            final_batches.extend(batches_to_add);
            current_inventory['batches'] = final_batches;
            save_inventory(current_inventory); # Save the modified inventory
            sku_name = skus_data.get(sku_to_move, {}).get('name', sku_to_move);
            flash(f"ย้าย '{sku_name}' จำนวน {moved_count} ชิ้น ไปยังหน้าร้านเรียบร้อยแล้ว", "success")
        elif requested_quantity > 0: # moved_count was 0, but user requested > 0
             flash("เกิดข้อผิดพลาด: ไม่สามารถย้ายสินค้าได้ (อาจมีการเปลี่ยนแปลงสต็อก)", "danger")
        else: # requested_quantity was 0 or less
             flash("จำนวนต้องมากกว่า 0", "warning")
        return redirect(url_for('index')) # Redirect back to index

    else: # GET request
        if not available_skus_in_back: flash("ไม่มีสินค้าในสต็อกหลังร้านให้ย้าย", "info"); return redirect(url_for('index'))
        return render_template('move_to_display.html', **render_context)

# --- ใช้ฟังก์ชัน record_sale เวอร์ชันนี้ ---
@app.route('/record_sale', methods=['GET', 'POST'], endpoint='record_sale')
def record_sale():
    skus_data = load_skus(); inventory = load_inventory()
    if skus_data is None or inventory is None: flash("ผิดพลาด: โหลดข้อมูลหลักไม่ได้", "danger"); return redirect(url_for('index'))

    batches = inventory.get('batches', [])
    sellable_locations = ['rtc2', 'rtc1', 'display']; location_sell_priority = {loc: i for i, loc in enumerate(sellable_locations)};
    sellable_batches = [b for b in batches if b.get('location') in sellable_locations and b.get('quantity', 0) > 0];
    available_skus_to_sell = {}; aggregated_sellable_stock = {}

    if sellable_batches:
        sellable_batches.sort(key=lambda b: ( location_sell_priority.get(b.get('location'), 99), b.get('expiry_date', ''), b.get('arrival_date', '') ))
        unique_skus = sorted(list(set(b['sku'] for b in sellable_batches)));
        current_prices_dict = get_current_prices(unique_skus)
        for sku_code in unique_skus:
            if sku_code in skus_data:
                available_skus_to_sell[sku_code] = skus_data[sku_code]
                available_skus_to_sell[sku_code]['current_prices'] = current_prices_dict.get(sku_code, {})
                aggregated_sellable_stock[sku_code] = sum(b['quantity'] for b in sellable_batches if b['sku'] == sku_code)
            else: print(f"!!! Warning: SKU '{sku_code}' sellable but not in skus.json !!!")

    render_context = {
        'skus': available_skus_to_sell,
        'sellable_stock_agg': aggregated_sellable_stock,
        'errors': {},
        'form_data': {},
        'get_current_prices': get_current_prices
    }

    if request.method == 'POST':
        form_data = request.form.to_dict(); render_context['form_data'] = form_data
        sku_to_sell = form_data.get('sku'); quantity_str = form_data.get('quantity')
        price_type = form_data.get('price_type');
        custom_b2b_price_str = form_data.get('custom_b2b_price', '').strip() # <-- รับค่าราคา B2B กำหนดเอง
        rtc_discount_str = form_data.get('rtc_discount_percent', '0')
        errors = {}

        # --- Validation ---
        if not sku_to_sell: errors['sku'] = "ต้องเลือก SKU"
        elif sku_to_sell not in available_skus_to_sell: errors['sku'] = f"ไม่พบ SKU '{sku_to_sell}' ในสต็อกพร้อมขาย"

        requested_quantity = 0; total_available_for_sku = aggregated_sellable_stock.get(sku_to_sell, 0)
        if not quantity_str:
            errors['quantity'] = "ต้องระบุจำนวน"
        else:
            try:
                requested_quantity = int(quantity_str)
                if requested_quantity <= 0: errors['quantity'] = "จำนวนต้องเป็นเลขจำนวนเต็มบวก"
                elif sku_to_sell in aggregated_sellable_stock and requested_quantity > total_available_for_sku:
                    errors['quantity'] = f"มีสต็อกพร้อมขายแค่ {total_available_for_sku} ชิ้น"
            except ValueError: errors['quantity'] = "จำนวนที่ขายต้องเป็นตัวเลข"

        if not price_type: errors['price_type'] = "ต้องเลือกประเภทราคา (B2C/B2B)"
        elif price_type not in ['b2c', 'b2b']: errors['price_type'] = "ประเภทราคาไม่ถูกต้อง"

        # Validate Custom B2B Price (if provided and type is B2B)
        custom_b2b_price_val = None
        if price_type == 'b2b' and custom_b2b_price_str: # Validate only if B2B and field is not empty
            try:
                custom_b2b_price_val = float(custom_b2b_price_str)
                if custom_b2b_price_val < 0:
                    errors['custom_b2b_price'] = "ราคา B2B กำหนดเองต้องไม่ติดลบ"
                    custom_b2b_price_val = None # Reset if invalid
            except ValueError:
                errors['custom_b2b_price'] = "รูปแบบราคา B2B กำหนดเองไม่ถูกต้อง"

        rtc_discount_percent = 0.0
        try:
            rtc_discount_val = float(rtc_discount_str) if rtc_discount_str else 0.0
            if 0 <= rtc_discount_val <= 100: rtc_discount_percent = rtc_discount_val
            else: errors['rtc_discount_percent'] = "ส่วนลดต้องอยู่ระหว่าง 0 ถึง 100"
        except ValueError: errors['rtc_discount_percent'] = "ส่วนลดต้องเป็นตัวเลข"

        # Determine Base Unit Price
        base_unit_price = None
        if not errors:
            current_prices = get_current_prices([sku_to_sell]).get(sku_to_sell, {})
            if price_type == 'b2b':
                if custom_b2b_price_val is not None: # Use custom B2B if valid
                    base_unit_price = custom_b2b_price_val
                    print(f"Using custom B2B price for {sku_to_sell}: {base_unit_price}")
                else: # Use standard B2B
                    base_unit_price = current_prices.get('price_b2b')
                    if base_unit_price is None:
                         errors['price_type'] = f"ไม่พบราคา B2B มาตรฐานสำหรับ SKU นี้ กรุณาตั้งราคา หรือกรอกราคา B2B กำหนดเอง"
            else: # price_type is 'b2c'
                base_unit_price = current_prices.get('price_b2c')
                if base_unit_price is None:
                    errors['price_type'] = f"ไม่พบราคา B2C สำหรับ SKU นี้ กรุณาตั้งราคา"

            # Ensure base_unit_price is usable number if found
            if base_unit_price is not None:
                try:
                    base_unit_price = float(base_unit_price) # Ensure it's a float
                except (ValueError, TypeError):
                     errors['price_type'] = "ราคาที่ดึงมามีปัญหา ไม่สามารถคำนวณได้"
                     base_unit_price = None # Mark as None if conversion fails

        # --- Re-render on errors ---
        render_context['errors'] = errors
        if errors:
            for field, msg in errors.items(): flash(f"{field.replace('_', ' ').title()}: {msg}", "warning");
            render_context['skus'] = available_skus_to_sell; render_context['sellable_stock_agg'] = aggregated_sellable_stock
            return render_template('record_sale.html', **render_context)

        # --- Process Sale (If Validation Passed & base_unit_price is valid) ---
        if base_unit_price is None:
             # Should not happen if validation is correct, but safety check
             flash("เกิดข้อผิดพลาด ไม่พบราคาที่ใช้ในการคำนวณ", "danger")
             return render_template('record_sale.html', **render_context)

        current_inventory = load_inventory();
        if current_inventory is None: flash("ผิดพลาด: โหลดสต็อกไม่ได้", "danger"); return render_template('record_sale.html', **render_context)
        all_current_batches = current_inventory.get('batches', [])
        quantity_left_to_sell = requested_quantity; sold_count = 0; indices_to_update = {}
        source_location_for_log = None

        source_batches_info = sorted([(i, b) for i, b in enumerate(all_current_batches) if b.get('sku') == sku_to_sell and b.get('location') in sellable_locations and b.get('quantity', 0) > 0], key=lambda item: ( location_sell_priority.get(item[1].get('location'), 99), item[1].get('expiry_date', ''), item[1].get('arrival_date', '') ))

        for original_index, batch_data in source_batches_info:
            if quantity_left_to_sell <= 0: break
            if source_location_for_log is None: source_location_for_log = batch_data.get('location')
            available_in_this_batch = batch_data['quantity']
            sell_from_this_batch = min(available_in_this_batch, quantity_left_to_sell)
            if sell_from_this_batch > 0:
                new_quantity_original = available_in_this_batch - sell_from_this_batch
                indices_to_update[original_index] = new_quantity_original
                sold_count += sell_from_this_batch
                quantity_left_to_sell -= sell_from_this_batch

        if sold_count == requested_quantity and sold_count > 0:
            final_unit_price = base_unit_price # Already float from validation/check
            actual_discount_applied = 0.0
            if source_location_for_log in ['rtc1', 'rtc2'] and rtc_discount_percent > 0:
                actual_discount_applied = rtc_discount_percent
                final_unit_price = final_unit_price * (1 - (actual_discount_applied / 100.0))
            total_sale_value = final_unit_price * sold_count

            # Save Inventory Changes
            final_batches = []
            for i, batch in enumerate(all_current_batches):
                 if i in indices_to_update:
                      new_qty = indices_to_update[i];
                      if new_qty > 0: updated_batch = batch.copy(); updated_batch['quantity'] = new_qty; final_batches.append(updated_batch)
                 else: final_batches.append(batch)
            current_inventory['batches'] = final_batches; save_inventory(current_inventory)

            # Save Sales Log Entry
            sales_log = load_sales_log()
            sale_entry = {
                "sale_id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
                "sku": sku_to_sell, "quantity": sold_count,
                "source_location": source_location_for_log,
                "price_type": price_type,
                "base_unit_price": base_unit_price, # Can be standard or custom B2B
                "rtc_discount_percent": actual_discount_applied,
                "final_unit_price": final_unit_price,
                "total_sale_value": total_sale_value }
            sales_log.append(sale_entry); save_sales_log(sales_log)

            # Success Message
            sku_name = skus_data.get(sku_to_sell, {}).get('name', sku_to_sell)
            price_info_msg = f"ราคา {price_type.upper()} ({final_unit_price:,.2f}/หน่วย)"
            if custom_b2b_price_val is not None and price_type=='b2b': price_info_msg = f"ราคาพิเศษ B2B ({final_unit_price:,.2f}/หน่วย)" # Indicate custom price used
            if actual_discount_applied > 0: price_info_msg += f" (ลด RTC {actual_discount_applied}%)"
            flash(f"บันทึกการขาย '{sku_name}' จำนวน {sold_count} ชิ้น ({price_info_msg}) เรียบร้อยแล้ว", "success")

        elif requested_quantity > 0 : flash(f"ขาย SKU '{sku_to_sell}' ไม่สำเร็จ ({sold_count}/{requested_quantity}) - ไม่ได้บันทึก", "danger")
        else: flash("จำนวนที่ขายต้องมากกว่า 0", "warning")
        return redirect(url_for('index'))

    else: # GET Request
        if not available_skus_to_sell: flash("ไม่มีสินค้าพร้อมขาย (หน้าร้าน/RTC)", "info"); return redirect(url_for('index'))
        return render_template('record_sale.html', **render_context)

# --- Dashboard Route ---
@app.route('/dashboard', endpoint='dashboard')
def dashboard():
    inventory = load_inventory(); skus_data = load_skus()
    if skus_data is None or inventory is None: flash("ผิดพลาด: โหลดข้อมูลไม่ได้", "danger"); return render_template('dashboard.html', dashboard_data={}, skus_data={}, location_configs={})
    batches = inventory.get('batches', [])
    updated_batches, changed = update_batch_statuses(batches, skus_data)
    if changed: inventory['batches'] = updated_batches; save_inventory(inventory); batches_to_process = updated_batches
    else: batches_to_process = batches
    now_utc = datetime.now(timezone.utc); expiring_soon_threshold_days = 3; expiring_soon_batches = []; status_summary = {loc: {'total_qty': 0, 'sku_count': set()} for loc in ['display', 'back_stock', 'rtc1', 'rtc2', 'bad']}; category_summary = {cat: {'total_qty': 0, 'sku_count': set()} for cat in ALLOWED_CATEGORIES}; bad_stock_summary = {}; current_stock_totals = {}
    batches_to_process.sort(key=lambda b: b.get('expiry_date', ''))
    for batch in batches_to_process:
        sku = batch.get('sku'); qty = batch.get('quantity', 0); loc = batch.get('location'); expiry_input = batch.get('expiry_date'); sku_info = skus_data.get(sku)
        if qty <= 0 or not sku_info: continue
        if loc in status_summary: status_summary[loc]['total_qty'] += qty; status_summary[loc]['sku_count'].add(sku)
        category = sku_info.get('category');
        if category and category in category_summary: category_summary[category]['total_qty'] += qty; category_summary[category]['sku_count'].add(sku)
        elif category and 'อื่นๆ' in category_summary: category_summary['อื่นๆ']['total_qty'] += qty; category_summary['อื่นๆ']['sku_count'].add(sku)
        if loc != 'bad' and expiry_input:
            try:
                expiry_dt_utc = None
                if isinstance(expiry_input, datetime): expiry_dt_utc = expiry_input
                elif isinstance(expiry_input, str):
                    if expiry_input.endswith('Z'): expiry_dt_utc = datetime.fromisoformat(expiry_input.replace('Z', '+00:00'))
                    else: # More robust parsing attempt
                        try: expiry_dt_utc = datetime.fromisoformat(expiry_input)
                        except ValueError: expiry_dt_utc = datetime.strptime(expiry_input, "%Y-%m-%dT%H:%M:%S") # Adjust if needed
                if expiry_dt_utc and expiry_dt_utc.tzinfo is None: expiry_dt_utc = pytz.utc.localize(expiry_dt_utc) # Localize if naive and parsed

                if expiry_dt_utc: # Proceed only if date was parsed successfully
                     time_until_expiry = expiry_dt_utc - now_utc
                     if timedelta(0) < time_until_expiry <= timedelta(days=expiring_soon_threshold_days): expiring_soon_batches.append(batch)
            except (ValueError, TypeError, AttributeError) as e:
                print(f"Error processing expiry for dashboard: {e} - Data: {expiry_input}")
                pass # Skip batch if date is problematic
        if loc == 'bad': bad_stock_summary[sku] = bad_stock_summary.get(sku, 0) + qty
        if loc != 'bad': current_stock_totals[sku] = current_stock_totals.get(sku, 0) + qty
    low_stock_items = []
    for sku, sku_info in skus_data.items():
        reorder_point = sku_info.get('reorder_point');
        if isinstance(reorder_point, int) and reorder_point >= 0:
            current_qty = current_stock_totals.get(sku, 0);
            if current_qty <= reorder_point: low_stock_items.append({ 'sku': sku, 'name': sku_info.get('name', '???'), 'current_qty': current_qty, 'reorder_point': reorder_point })
    low_stock_items.sort(key=lambda item: item['name'])
    for data in status_summary.values(): data['sku_count'] = len(data['sku_count'])
    for data in category_summary.values(): data['sku_count'] = len(data['sku_count'])
    location_configs = { 'display': {'title': 'หน้าร้าน', 'icon': 'bi-shop', 'badge_class': 'text-bg-primary'}, 'back_stock': {'title': 'หลังร้าน', 'icon': 'bi-boxes', 'badge_class': 'text-bg-secondary'}, 'rtc1': {'title': 'RTC-1', 'icon': 'bi-alarm', 'badge_class': 'text-bg-warning'}, 'rtc2': {'title': 'RTC-2', 'icon': 'bi-alarm-fill', 'badge_class': 'text-bg-danger'}, 'bad': {'title': 'หมดอายุ', 'icon': 'bi-x-octagon-fill', 'badge_class': 'text-bg-dark'} }
    dashboard_data = { 'status_summary': status_summary, 'expiring_soon': expiring_soon_batches, 'expiring_threshold_days': expiring_soon_threshold_days, 'bad_stock': bad_stock_summary, 'category_summary': {k: v for k, v in category_summary.items() if v['total_qty'] > 0}, 'low_stock': low_stock_items }
    return render_template('dashboard.html', dashboard_data=dashboard_data, skus_data=skus_data, location_configs=location_configs )


# --- Pricing Route (ปรับปรุงใหม่) ---
@app.route('/pricing', endpoint='view_pricing')
def view_pricing():
    """หน้าแสดงตารางราคา B2C/B2B แยกตาม Category พร้อมเปรียบเทียบ"""
    skus_info = load_skus(); price_history = load_price_history()
    if skus_info is None: flash("ผิดพลาด: โหลดข้อมูล SKU ไม่ได้", "danger"); skus_info = {}
    if price_history is None: flash("ผิดพลาด: โหลดประวัติราคาไม่ได้", "danger"); price_history = []

    now = datetime.now(timezone.utc); one_week_ago = now - timedelta(days=7)
    current_prices = {}; previous_prices = {}
    processed_skus_for_current = set(); processed_skus_for_previous = set()

    for entry in price_history: # Sorted latest first
        sku = entry.get('sku');
        if not sku or sku not in skus_info: continue
        try:
            entry_date_str = entry.get('date');
            if not entry_date_str: continue
            # Ensure date has timezone info (UTC)
            entry_date = datetime.fromisoformat(entry_date_str.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            print(f"Warning: Invalid date format in price history for SKU {sku}: {entry_date_str}")
            continue # Skip invalid date entries

        # Find current price (first entry for this SKU)
        if sku not in processed_skus_for_current:
            current_prices[sku] = {'date': entry_date, 'b2c': entry.get('price_b2c'), 'b2b': entry.get('price_b2b')}
            processed_skus_for_current.add(sku)
        # Find previous price (first entry for this SKU on or before one week ago)
        if sku not in processed_skus_for_previous and entry_date <= one_week_ago:
             previous_prices[sku] = {'date': entry_date, 'b2c': entry.get('price_b2c'), 'b2b': entry.get('price_b2b')}
             processed_skus_for_previous.add(sku)

    # Combine data for display
    grouped_display_data = defaultdict(list); all_skus = sorted(skus_info.keys())
    for sku_code in all_skus:
        sku_details = skus_info.get(sku_code); category = sku_details.get('category', 'อื่นๆ')
        if not category or category not in ALLOWED_CATEGORIES: category = 'อื่นๆ'
        current = current_prices.get(sku_code); previous = previous_prices.get(sku_code)
        # Helper function for safe float conversion
        def safe_float(val):
            if val is None: return None
            try: return float(val)
            except (ValueError, TypeError): return None
        # Get current and previous prices as floats or None
        current_b2c = safe_float(current['b2c']) if current else None; current_b2b = safe_float(current['b2b']) if current else None
        prev_b2c = safe_float(previous['b2c']) if previous else None; prev_b2b = safe_float(previous['b2b']) if previous else None
        # Determine change status
        def get_change_status(current_p, prev_p):
            if current_p is not None and prev_p is not None:
                if current_p > prev_p: return 'up'
                if current_p < prev_p: return 'down'
                return 'same'
            elif current_p is not None and prev_p is None: return 'new'
            elif current_p is None and prev_p is not None: return 'removed'
            return None # Both None or other cases
        b2c_change = get_change_status(current_b2c, prev_b2c); b2b_change = get_change_status(current_b2b, prev_b2b)
        # Append data for this SKU to its category group
        grouped_display_data[category].append({
            'sku': sku_code, 'name': sku_details.get('name', '???'),
            'current_b2c': current_b2c, 'current_b2b': current_b2b,
            'previous_b2c': prev_b2c, 'previous_b2b': prev_b2b,
            'b2c_change': b2c_change, 'b2b_change': b2b_change })
    # Sort SKUs within each category by name
    for cat in grouped_display_data: grouped_display_data[cat].sort(key=lambda x: x['name'])
    # Order categories for display
    category_order = ALLOWED_CATEGORIES + ['อื่นๆ']
    ordered_grouped_data = { cat: grouped_display_data[cat] for cat in category_order if cat in grouped_display_data }
    # Render the template
    return render_template('pricing.html', grouped_prices=ordered_grouped_data, categories=ordered_grouped_data.keys())


# --- Sales Report Route ---
@app.route('/sales_report', endpoint='view_sales_report')
def view_sales_report():
    """แสดงรายงานยอดขายตามช่วงเวลา"""
    # --- รับค่า Filter จาก Query Parameters ---
    selected_period = request.args.get('period', 'today') # Default to 'today'
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')

    # --- คำนวณช่วงวันที่ UTC ---
    start_utc, end_utc = get_date_range(selected_period, start_date_str, end_date_str)

    # --- โหลดข้อมูล ---
    sales_log = load_sales_log()
    skus_data = load_skus()
    if sales_log is None or skus_data is None:
        flash("เกิดข้อผิดพลาดในการโหลดข้อมูลการขายหรือ SKU", "danger")
        return render_template('sales_report.html',
                               selected_period=selected_period,
                               start_date=start_date_str, end_date=end_date_str,
                               total_sales=0, filtered_sales=[], report_range_str="ข้อผิดพลาด")

    # --- กรองข้อมูลตามช่วงเวลา ---
    filtered_sales = []
    total_sales = 0.0
    report_range_str = "ทั้งหมด" # Default for 'all' or error

    if start_utc and end_utc: # Filter only if date range is valid
        report_range_str = f"{format_iso_date(start_utc, '%d/%m/%Y')} - {format_iso_date(end_utc, '%d/%m/%Y')}"
        for sale in sales_log:
            try:
                sale_timestamp_str = sale.get('timestamp')
                if not sale_timestamp_str: continue
                # Parse sale timestamp string to aware datetime object
                sale_dt_utc = datetime.fromisoformat(sale_timestamp_str.replace('Z', '+00:00'))

                if start_utc <= sale_dt_utc <= end_utc:
                    # เพิ่มข้อมูล ชื่อสินค้า เพื่อแสดงผล
                    sale['sku_name'] = skus_data.get(sale.get('sku'), {}).get('name', '???')
                    filtered_sales.append(sale)
                    # Ensure total_sale_value is treated as float
                    total_sales += float(sale.get('total_sale_value', 0.0))

            except (ValueError, TypeError, KeyError) as e: # Catch KeyError too
                 print(f"Error processing sale entry {sale.get('sale_id')}: {e}")
                 continue # Skip entry with bad data
    elif selected_period == 'all': # Show all if 'all' is selected
         report_range_str = "ทั้งหมด"
         for sale in sales_log:
             try:
                 sale['sku_name'] = skus_data.get(sale.get('sku'), {}).get('name', '???')
                 filtered_sales.append(sale)
                 total_sales += float(sale.get('total_sale_value', 0.0))
             except (TypeError, KeyError) as e:
                  print(f"Error processing sale entry {sale.get('sale_id')} for 'all': {e}")
                  continue
    else: # Likely date parsing error from get_date_range
         report_range_str = "ช่วงวันที่ผิดพลาด"


    # เรียงตามเวลาล่าสุดก่อนส่งไป Template (ถ้าต้องการ)
    filtered_sales.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

    return render_template('sales_report.html',
                           selected_period=selected_period,
                           start_date=start_date_str, # ส่งกลับไปให้ input แสดงค่าเดิม
                           end_date=end_date_str,   # ส่งกลับไปให้ input แสดงค่าเดิม
                           total_sales=total_sales,
                           filtered_sales=filtered_sales,
                           report_range_str=report_range_str) # ข้อความแสดงช่วงเวลา


# --- Main execution ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    use_debug = os.environ.get('FLASK_DEBUG', 'true').lower() == 'true'
    print(f" * Flask App Running on http://0.0.0.0:{port}/ (Debug: {use_debug})")
    # Make sure necessary files exist or are created on startup
    print(" * Checking/Initializing data files...")
    load_data(SKU_FILE)
    load_data(INVENTORY_FILE)
    load_data(PRICE_HISTORY_FILE)
    load_data(SALES_LOG_FILE) # Ensure sales log file check
    print(" * Data files check complete.")
    # Run the Flask development server
    app.run(debug=use_debug, host='0.0.0.0', port=port)