# -*- coding: utf-8 -*-
import json
import os
from datetime import datetime, timedelta, timezone # Standard library timezone
import pytz # For Bangkok timezone handling
import uuid
from math import floor
from collections import defaultdict # For grouping
from flask import Flask, render_template, request, redirect, url_for, flash

# --- App Setup ---
app = Flask(__name__)
# **สำคัญ:** เปลี่ยนค่านี้เป็น Secret Key ที่สร้างขึ้นเองและเก็บเป็นความลับ!
# ควรตั้งค่าผ่าน Environment Variable ใน Production
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'โปรดเปลี่ยน_secret_key_นี้_final_version_01') # <-- เปลี่ยนค่านี้!

# --- ค่าคงที่ ---
SKU_FILE = 'skus.json'
INVENTORY_FILE = 'inventory.json'
ALLOWED_CATEGORIES = sorted(['หมู', 'ไก่', 'เนื้อ', 'อาหารทะเล', 'ผัก', 'ผลไม้', 'เครื่องดื่ม', 'อื่นๆ'])
BANGKOK_TZ = pytz.timezone('Asia/Bangkok') # <-- Timezone กรุงเทพฯ

# --- Context Processors (สำหรับ Template Helpers) ---
@app.context_processor
def inject_global_vars():
    """Inject global variables and helper functions needed in templates."""
    def format_iso_date(date_str, fmt='%Y-%m-%d %H:%M'):
        """Formats ISO date string (UTC) to Bangkok time display format."""
        if not date_str: return "-"
        try:
            # ทำให้รองรับทั้งแบบมี Z และไม่มี Z (ตามมาตรฐาน ISO 8601)
            if date_str.endswith('Z'):
                dt_utc = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            else:
                # หากไม่มี Z ลอง assume ว่าเป็น UTC หรือตาม format ที่คาดหวัง
                # อาจต้องปรับปรุงถ้ามี format อื่นเข้ามา
                dt_utc = datetime.fromisoformat(date_str)
                if dt_utc.tzinfo is None: # ถ้าไม่มี timezone info, assume UTC
                    dt_utc = dt_utc.replace(tzinfo=timezone.utc)

            dt_bkk = dt_utc.astimezone(BANGKOK_TZ)
            return dt_bkk.strftime(fmt) + ""
        except (ValueError, TypeError) as e:
            print(f"Error formatting date string '{date_str}': {e}")
            # Consider logging this error instead of just printing
            return date_str # Return original string on error

    def format_time_remaining(expiry_date_str):
        """Calculates and formats remaining time from UTC expiry string."""
        if not expiry_date_str: return '<span class="text-muted">N/A</span>'
        try:
            now_utc = datetime.now(timezone.utc)
            # ทำให้รองรับทั้งแบบมี Z และไม่มี Z
            if expiry_date_str.endswith('Z'):
                expiry_dt_utc = datetime.fromisoformat(expiry_date_str.replace('Z', '+00:00'))
            else:
                expiry_dt_utc = datetime.fromisoformat(expiry_date_str)
                if expiry_dt_utc.tzinfo is None:
                   expiry_dt_utc = expiry_dt_utc.replace(tzinfo=timezone.utc) # Assume UTC if no tzinfo

            delta = expiry_dt_utc - now_utc

            if delta.total_seconds() <= 0:
                return '<span class="badge bg-danger">หมดอายุ</span>'

            days = delta.days
            seconds_rem = delta.seconds
            hours = floor(seconds_rem / 3600)
            minutes = floor((seconds_rem % 3600) / 60)

            parts = []
            text_class = "text-success" # Default

            # กำหนด Class ตามความเร่งด่วน (ปรับปรุง logic เล็กน้อยเพื่อความชัดเจน)
            if delta <= timedelta(hours=1): text_class = "text-danger"
            elif delta <= timedelta(hours=12): text_class = "text-danger" # อาจจะยังแดงอยู่?
            elif delta <= timedelta(days=1, hours=1): text_class = "text-warning" # < 25 hours
            elif delta <= timedelta(days=3): text_class = "text-warning" # 1-3 days left

            # สร้างข้อความแสดงผล
            if days > 0:
                parts.append(f"{days} วัน")
            if hours > 0 and days < 3: # แสดง ชม. ถ้าเหลือน้อยกว่า 3 วัน
                 parts.append(f"{hours} ชม.")
            if minutes > 0 and days == 0 and hours < 1: # แสดง นาที ถ้าเหลือน้อยกว่า 1 ชม.
                 parts.append(f"{minutes} นาที")

            # กรณี edge case ที่คำนวณแล้วไม่มี part แต่ยังไม่หมดอายุ (เช่น เหลือ < 1 นาที)
            if not parts and delta.total_seconds() > 0:
                 return '<span class="badge bg-danger">ใกล้หมดอายุมาก</span>'
            elif not parts: # Should not happen if delta > 0 but check anyway
                 return '<span class="badge bg-danger">หมดอายุ</span>'


            remaining_str = " ".join(parts)

            # เลือก badge ตาม class
            if text_class == "text-danger":
                return f'<span class="badge bg-danger-subtle text-danger-emphasis">{remaining_str}</span>'
            elif text_class == "text-warning":
                return f'<span class="badge bg-warning-subtle text-warning-emphasis">{remaining_str}</span>'
            else: # text-success
                return f'<span class="text-success">{remaining_str}</span>'

        except (ValueError, TypeError) as e:
            print(f"Error calculating time remaining for '{expiry_date_str}': {e}")
            # Consider logging this error
            return '<span class="text-muted">Date Error</span>'

    return dict(
        current_year=datetime.now(BANGKOK_TZ).year,
        format_iso_date=format_iso_date,
        format_time_remaining=format_time_remaining
    )

# --- Helper Functions: Data Loading/Saving ---
def load_data(filename):
    """โหลดข้อมูลจากไฟล์ JSON พร้อมจัดการกรณีไฟล์ไม่มี/ว่าง/เสีย"""
    default_data = {"batches": []} if filename == INVENTORY_FILE else {}
    if not os.path.exists(filename):
        print(f"File {filename} not found, returning default.")
        return default_data
    try:
        # ใช้ utf-8-sig เพื่อจัดการ BOM (Byte Order Mark) ที่อาจมีตอนต้นไฟล์
        with open(filename, 'r', encoding='utf-8-sig') as f:
            content = f.read()
            if not content.strip(): # ตรวจสอบว่ามีเนื้อหาจริงๆ (ไม่นับ whitespace)
                print(f"File {filename} is empty, returning default.")
                return default_data
            return json.loads(content)
    except (IOError) as e:
        print(f"Error loading data from {filename} (IOError): {e}")
        flash(f"เกิดข้อผิดพลาดในการอ่านไฟล์ {filename}", "danger")
        return default_data
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {filename}: {e}")
        flash(f"ไฟล์ข้อมูล {filename} เสียหายหรือไม่ใช่รูปแบบ JSON", "danger")
        return default_data
    except Exception as e:
        print(f"Unexpected error loading {filename}: {e}")
        flash(f"เกิดข้อผิดพลาดไม่คาดคิดในการโหลด {filename}", "danger")
        # Consider logging the full traceback here for debugging
        return default_data

def save_data(filename, data):
    """บันทึกข้อมูลลงไฟล์ JSON"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            # indent=4 เพื่อให้อ่านง่าย, ensure_ascii=False เพื่อให้ภาษาไทยแสดงผลถูกต้อง
            json.dump(data, f, indent=4, ensure_ascii=False)
    except IOError as e:
        print(f"Error saving data to {filename}: {e}")
        flash(f"เกิดข้อผิดพลาดในการบันทึกข้อมูลลง {filename}", "danger")
    except Exception as e:
        print(f"Unexpected error saving {filename}: {e}")
        flash(f"เกิดข้อผิดพลาดไม่คาดคิดในการบันทึก {filename}", "danger")
        # Consider logging the full traceback

def load_skus():
    """โหลดข้อมูล SKU และตรวจสอบ/แปลงค่าเบื้องต้น"""
    skus = load_data(SKU_FILE)
    if isinstance(skus, dict):
        cleaned_skus = {}
        for sku_code, sku_data in skus.items():
            if isinstance(sku_data, dict):
                cleaned_data = sku_data.copy()
                # แปลงราคาเป็น float, ถ้าไม่ได้ให้เป็น None
                for field in ['price_b2c', 'price_b2b']:
                    price_val = cleaned_data.get(field)
                    if price_val is not None and price_val != '':
                        try:
                            cleaned_data[field] = float(price_val)
                        except (ValueError, TypeError):
                             print(f"Warning: Could not convert {field} '{price_val}' to float for SKU '{sku_code}'. Setting to None.")
                             cleaned_data[field] = None
                    else:
                        cleaned_data[field] = None # Treat empty string as None

                # แปลง reorder_point เป็น int, ถ้าไม่ได้ให้เป็น None
                reorder_point = cleaned_data.get('reorder_point')
                if reorder_point is not None and reorder_point != '':
                    try:
                        cleaned_data['reorder_point'] = int(reorder_point)
                    except (ValueError, TypeError):
                        print(f"Warning: Could not convert reorder_point '{reorder_point}' to int for SKU '{sku_code}'. Setting to None.")
                        cleaned_data['reorder_point'] = None
                else:
                     cleaned_data['reorder_point'] = None # Treat empty string as None

                # ตรวจสอบ shelf_life_days เป็น int > 0
                shelf_life = cleaned_data.get('shelf_life_days')
                if shelf_life is not None and shelf_life != '':
                    try:
                        sl_int = int(shelf_life)
                        if sl_int > 0:
                             cleaned_data['shelf_life_days'] = sl_int
                        else:
                             print(f"Warning: shelf_life_days '{shelf_life}' is not positive for SKU '{sku_code}'. Setting to None.")
                             cleaned_data['shelf_life_days'] = None
                    except (ValueError, TypeError):
                        print(f"Warning: Could not convert shelf_life_days '{shelf_life}' to int for SKU '{sku_code}'. Setting to None.")
                        cleaned_data['shelf_life_days'] = None
                else:
                    cleaned_data['shelf_life_days'] = None # Treat empty string as None

                cleaned_skus[sku_code] = cleaned_data
            else:
                print(f"Warning: Invalid data structure for SKU '{sku_code}' in {SKU_FILE}. Skipping.")
        return cleaned_skus
    else:
        print(f"Warning: Data in {SKU_FILE} is not a dictionary. Returning empty.")
        # อาจจะสร้างไฟล์เปล่าให้เลยถ้าต้องการ
        # save_data(SKU_FILE, {})
        return {}


def save_skus(skus_data):
    """บันทึกข้อมูล SKU"""
    save_data(SKU_FILE, skus_data)

def load_inventory():
    """โหลดข้อมูล Inventory และตรวจสอบโครงสร้างพื้นฐาน"""
    inventory_data = load_data(INVENTORY_FILE)
    # ตรวจสอบให้ละเอียดขึ้น
    if not isinstance(inventory_data, dict) or 'batches' not in inventory_data or not isinstance(inventory_data.get('batches'), list):
        print(f"Warning: Data in {INVENTORY_FILE} has incorrect structure or missing 'batches' list. Resetting to default.")
        flash(f"โครงสร้างข้อมูลใน {INVENTORY_FILE} ไม่ถูกต้อง, กำลังรีเซ็ตเป็นค่าเริ่มต้น", "warning")
        inventory = {"batches": []}
        save_inventory(inventory) # สร้างไฟล์ให้ถูกต้องเลย
    else:
        # อาจจะเพิ่มการตรวจสอบ batch แต่ละอันใน list ถ้าต้องการความ robust มากขึ้น
        inventory = inventory_data
    return inventory

def save_inventory(inventory_data):
    """บันทึกข้อมูล Inventory"""
    # ตรวจสอบก่อนบันทึกว่า 'batches' key ยังอยู่และเป็น list
    if 'batches' not in inventory_data or not isinstance(inventory_data.get('batches'), list):
       print(f"Error: Attempting to save inventory data without a valid 'batches' list. Aborting save.")
       flash("เกิดข้อผิดพลาดร้ายแรง: ไม่สามารถบันทึกข้อมูลสต็อกได้เนื่องจากโครงสร้างข้อมูลผิดพลาด", "danger")
       return # ไม่บันทึกถ้าโครงสร้างผิด
    save_data(INVENTORY_FILE, inventory_data)

# --- Helper Function: Update Batch Statuses ---
def update_batch_statuses(batches, skus_data):
    """อัปเดตสถานะ (location) ของแต่ละ Batch ตามวันหมดอายุและกฎ RTC."""
    now_utc = datetime.now(timezone.utc)
    updated_batches = []
    something_changed = False

    for batch in batches:
        current_location = batch.get('location')
        expiry_str = batch.get('expiry_date')
        sku = batch.get('sku')
        qty = batch.get('quantity', 0) # ให้ default เป็น 0
        batch_id_short = batch.get('batch_id', 'N/A')[:8] # สำหรับ logging

        # สร้าง copy เพื่อป้องกันการแก้ไข original โดยตรงใน loop
        new_batch_data = batch.copy()

        # เงื่อนไขที่ไม่ต้อง process: ไม่มี expiry, ไม่มี sku, sku ไม่ถูกต้อง, จำนวน <= 0, หรือเป็น 'bad' อยู่แล้ว
        if not expiry_str or not sku or sku not in skus_data or qty <= 0 or current_location == 'bad':
            updated_batches.append(new_batch_data) # เพิ่มอันเดิมเข้าไป
            continue

        try:
            # Parse expiry date (handle Z)
            if expiry_str.endswith('Z'):
                expiry_dt_utc = datetime.fromisoformat(expiry_str.replace('Z', '+00:00'))
            else:
                 expiry_dt_utc = datetime.fromisoformat(expiry_str)
                 if expiry_dt_utc.tzinfo is None:
                    expiry_dt_utc = expiry_dt_utc.replace(tzinfo=timezone.utc)

            time_until_expiry = expiry_dt_utc - now_utc
            new_location = current_location # Default location คืออันเดิม

            # ตรวจสอบเงื่อนไขการเปลี่ยนสถานะ
            # 1. หมดอายุ -> bad
            if time_until_expiry <= timedelta(0):
                new_location = 'bad'
            # 2. ถ้ายังไม่หมดอายุ และอยู่ที่ back_stock -> ไม่ต้องทำอะไร รอการ move
            elif current_location == 'back_stock':
                pass # ไม่เปลี่ยนสถานะอัตโนมัติจาก back_stock
            # 3. ถ้าเหลือ <= 12 ชม. 30 นาที และอยู่ที่ display หรือ rtc1 -> rtc2
            elif time_until_expiry <= timedelta(hours=12, minutes=30) and current_location in ['display', 'rtc1']:
                new_location = 'rtc2'
            # 4. ถ้าเหลือ <= 1 วัน 1 ชม. (25 ชม.) และอยู่ที่ display -> rtc1
            elif time_until_expiry <= timedelta(days=1, hours=1) and current_location == 'display':
                new_location = 'rtc1'

            # ถ้ามีการเปลี่ยนแปลงสถานะ
            if new_location != current_location:
                print(f"Status Change: Batch {batch_id_short} ({sku}) {current_location} -> {new_location}")
                new_batch_data['location'] = new_location
                something_changed = True

            updated_batches.append(new_batch_data)

        except (ValueError, TypeError) as e:
            print(f"Error parsing date or processing batch {batch_id_short}, SKU {sku}. Skipping status update. Error: {e}")
            updated_batches.append(new_batch_data) # เก็บ batch เดิมไว้ถ้ามีปัญหา

    return updated_batches, something_changed

# --- Routes ---

@app.route('/', endpoint='index')
def index():
    """หน้าแสดงภาพรวม Inventory"""
    inventory = load_inventory()
    skus_data = load_skus()
    batches = inventory.get('batches', []) # ใช้ .get ป้องกันกรณี key ไม่มี

    # อัปเดตสถานะก่อนแสดงผลเสมอ
    updated_batches, changed = update_batch_statuses(batches, skus_data)
    if changed:
        print("Index: Batch statuses updated, saving changes...")
        inventory['batches'] = updated_batches
        save_inventory(inventory)
        batches_to_process = updated_batches # ใช้ข้อมูลที่อัปเดตแล้ว
    else:
        batches_to_process = batches # ใช้ข้อมูลเดิมถ้าไม่มีการเปลี่ยนแปลง

    # Configuration สำหรับการแสดงผลแต่ละ location
    location_configs = {
        'display': {'title': 'หน้าร้าน', 'border_status_class': 'status-display', 'badge_class': 'text-bg-primary', 'icon': 'bi-shop'},
        'back_stock': {'title': 'หลังร้าน', 'border_status_class': 'status-back-stock', 'badge_class': 'text-bg-secondary', 'icon': 'bi-boxes'},
        'rtc1': {'title': 'RTC-1', 'border_status_class': 'status-rtc1', 'badge_class': 'text-bg-warning', 'icon': 'bi-alarm'},
        'rtc2': {'title': 'RTC-2', 'border_status_class': 'status-rtc2', 'badge_class': 'text-bg-danger', 'icon': 'bi-alarm-fill'},
        'bad': {'title': 'หมดอายุ', 'border_status_class': 'status-bad', 'badge_class': 'text-bg-dark', 'icon': 'bi-x-octagon-fill'}
    }
    location_order = ['display', 'back_stock', 'rtc1', 'rtc2', 'bad']
    location_sort_key = {loc: i for i, loc in enumerate(location_order)}

    # กรองเฉพาะ batch ที่มีจำนวน > 0
    valid_batches = [b for b in batches_to_process if b.get('quantity', 0) > 0]

    # เรียงลำดับ: ตาม Location -> SKU -> วันหมดอายุ (เก่าไปใหม่)
    valid_batches.sort(key=lambda b: (
        location_sort_key.get(b.get('location'), 99), # จัดกลุ่มตาม location ที่กำหนด
        b.get('sku', ''),                           # จัดเรียงตาม SKU
        b.get('expiry_date', '')                    # จัดเรียงตามวันหมดอายุ (เก่าสุดมาก่อน)
    ))

    return render_template(
        'index.html',
        inventory_batches=valid_batches,
        skus_data=skus_data,
        location_configs=location_configs,
        allowed_categories=ALLOWED_CATEGORIES # ส่งไปเผื่อใช้ใน template อื่นๆ ผ่าน base template
    )

# --- SKU Management Routes ---
@app.route('/skus', endpoint='list_skus')
def list_skus():
    """แสดงรายการ SKU ทั้งหมด"""
    skus_data = load_skus()
    # เรียงตามชื่อ SKU ก่อนส่งไป template
    sorted_skus = dict(sorted(skus_data.items(), key=lambda item: item[1].get('name', item[0])))
    return render_template('list_skus.html', skus=sorted_skus, categories=ALLOWED_CATEGORIES)

@app.route('/add_sku', methods=['GET', 'POST'], endpoint='add_sku')
def add_sku():
    """หน้าฟอร์มสำหรับเพิ่ม SKU ใหม่"""
    # ค่าเริ่มต้นสำหรับ context ที่จะส่งไป template
    render_context = {
        'categories': ALLOWED_CATEGORIES,
        'errors': {},
        'form_data': {} # เก็บข้อมูลที่ user กรอกล่าสุด (กรณี validation ไม่ผ่าน)
    }

    if request.method == 'POST':
        # ดึงข้อมูลจากฟอร์ม
        form_data = request.form.to_dict()
        render_context['form_data'] = form_data # เก็บข้อมูลฟอร์ม

        sku_code = form_data.get('sku', '').strip().upper()
        name = form_data.get('name', '').strip()
        category = form_data.get('category', '').strip()
        shelf_life_str = form_data.get('shelf_life_days', '').strip()
        reorder_point_str = form_data.get('reorder_point', '').strip()
        price_b2c_str = form_data.get('price_b2c', '').strip()
        price_b2b_str = form_data.get('price_b2b', '').strip()

        errors = {} # Dictionary เก็บ error message

        # --- Validation ---
        if not sku_code: errors['sku'] = "ต้องระบุ SKU Code"
        if not name: errors['name'] = "ต้องระบุชื่อสินค้า"
        if not category: errors['category'] = "ต้องเลือกประเภทสินค้า"
        elif category not in ALLOWED_CATEGORIES: errors['category'] = "ประเภทสินค้าไม่ถูกต้อง"

        shelf_life_days = None
        if not shelf_life_str:
            errors['shelf_life_days'] = "ต้องระบุอายุสินค้า (วัน)"
        else:
            try:
                sl_val = int(shelf_life_str)
                if sl_val <= 0:
                    errors['shelf_life_days'] = "อายุสินค้าต้องเป็นจำนวนเต็มบวก"
                else:
                    shelf_life_days = sl_val
            except ValueError:
                errors['shelf_life_days'] = "อายุสินค้าต้องเป็นตัวเลข (จำนวนวัน)"

        reorder_point = None # อนุญาตให้เป็นค่าว่างได้
        if reorder_point_str: # ถ้ามีการกรอกค่ามา
            try:
                rp_val = int(reorder_point_str)
                if rp_val < 0:
                    errors['reorder_point'] = "จุดสั่งซื้อต้องไม่ติดลบ (ใส่ 0 หรือมากกว่า)"
                else:
                    reorder_point = rp_val
            except ValueError:
                errors['reorder_point'] = "จุดสั่งซื้อต้องเป็นตัวเลข"

        price_b2c = None # อนุญาตให้เป็นค่าว่างได้
        if price_b2c_str:
            try:
                p_val = float(price_b2c_str)
                if p_val < 0:
                    errors['price_b2c'] = "ราคา B2C ต้องไม่ติดลบ"
                else:
                    price_b2c = p_val
            except ValueError:
                errors['price_b2c'] = "รูปแบบราคา B2C ไม่ถูกต้อง (ตัวเลขทศนิยม)"

        price_b2b = None # อนุญาตให้เป็นค่าว่างได้
        if price_b2b_str:
            try:
                p_val = float(price_b2b_str)
                if p_val < 0:
                    errors['price_b2b'] = "ราคา B2B ต้องไม่ติดลบ"
                else:
                    price_b2b = p_val
            except ValueError:
                errors['price_b2b'] = "รูปแบบราคา B2B ไม่ถูกต้อง (ตัวเลขทศนิยม)"

        # ตรวจสอบ SKU ซ้ำ (หลังจากผ่าน validation อื่นๆ แล้ว)
        if not errors:
            skus_data = load_skus()
            if sku_code in skus_data:
                errors['sku'] = f"SKU Code '{sku_code}' นี้มีอยู่ในระบบแล้ว"

        render_context['errors'] = errors

        # ถ้ามี errors ให้แสดง flash message และ render ฟอร์มใหม่พร้อม errors
        if errors:
            for field, msg in errors.items():
                 flash(f"{field.replace('_', ' ').title()}: {msg}", "warning")
            return render_template('add_sku.html', **render_context)

        # --- ถ้าไม่มี errors ---
        # เตรียมข้อมูล SKU ใหม่
        new_sku_data = {
            'name': name,
            'category': category,
            'shelf_life_days': shelf_life_days,
            'reorder_point': reorder_point,
            'price_b2c': price_b2c,
            'price_b2b': price_b2b
        }
        # โหลดข้อมูลล่าสุด, เพิ่ม SKU ใหม่, แล้วบันทึก
        skus_data = load_skus() # โหลดอีกครั้ง เผื่อมีการเปลี่ยนแปลง
        skus_data[sku_code] = new_sku_data
        save_skus(skus_data)

        flash(f"เพิ่ม SKU '{name}' ({sku_code}) เรียบร้อยแล้ว", "success")
        return redirect(url_for('list_skus')) # Redirect ไปหน้า list_skus

    else: # GET request
        return render_template('add_sku.html', **render_context)


@app.route('/edit_sku/<sku>', methods=['GET', 'POST'], endpoint='edit_sku')
def edit_sku(sku):
    """หน้าฟอร์มสำหรับแก้ไขข้อมูล SKU ที่มีอยู่"""
    skus_data = load_skus()

    # ตรวจสอบว่า SKU ที่ต้องการแก้ไขมีอยู่จริงหรือไม่
    if sku not in skus_data:
        flash(f"ไม่พบ SKU Code: {sku}", "danger")
        return redirect(url_for('list_skus'))

    # ค่าเริ่มต้นสำหรับ context
    render_context = {
        'categories': ALLOWED_CATEGORIES,
        'errors': {},
        'sku_code': sku, # ส่ง sku code ไปด้วย
        'form_data': skus_data[sku].copy() # ใช้ข้อมูลเดิมเป็นค่าเริ่มต้นของฟอร์ม
    }

    if request.method == 'POST':
        # ดึงข้อมูลจากฟอร์ม
        form_data = request.form.to_dict()
        render_context['form_data'] = form_data # อัปเดต form_data ด้วยค่าที่ user กรอกล่าสุด

        # ดึงค่าต่างๆ จาก form_data (เหมือนตอน Add)
        name = form_data.get('name', '').strip()
        category = form_data.get('category', '').strip()
        shelf_life_str = form_data.get('shelf_life_days', '').strip()
        reorder_point_str = form_data.get('reorder_point', '').strip()
        price_b2c_str = form_data.get('price_b2c', '').strip()
        price_b2b_str = form_data.get('price_b2b', '').strip()

        errors = {}

        # --- Validation (เหมือนตอน Add แต่ไม่ต้องเช็ค SKU ซ้ำ) ---
        if not name: errors['name'] = "ต้องระบุชื่อสินค้า"
        if not category: errors['category'] = "ต้องเลือกประเภทสินค้า"
        elif category not in ALLOWED_CATEGORIES: errors['category'] = "ประเภทสินค้าไม่ถูกต้อง"

        shelf_life_days = None
        if not shelf_life_str:
            errors['shelf_life_days'] = "ต้องระบุอายุสินค้า (วัน)"
        else:
            try:
                sl_val = int(shelf_life_str)
                if sl_val <= 0: errors['shelf_life_days'] = "อายุสินค้าต้องเป็นจำนวนเต็มบวก"
                else: shelf_life_days = sl_val
            except ValueError: errors['shelf_life_days'] = "อายุสินค้าต้องเป็นตัวเลข (จำนวนวัน)"

        reorder_point = None
        if reorder_point_str:
            try:
                rp_val = int(reorder_point_str)
                if rp_val < 0: errors['reorder_point'] = "จุดสั่งซื้อต้องไม่ติดลบ"
                else: reorder_point = rp_val
            except ValueError: errors['reorder_point'] = "จุดสั่งซื้อต้องเป็นตัวเลข"

        price_b2c = None
        if price_b2c_str:
            try:
                p_val = float(price_b2c_str)
                if p_val < 0: errors['price_b2c'] = "ราคา B2C ต้องไม่ติดลบ"
                else: price_b2c = p_val
            except ValueError: errors['price_b2c'] = "รูปแบบราคา B2C ไม่ถูกต้อง"

        price_b2b = None
        if price_b2b_str:
            try:
                p_val = float(price_b2b_str)
                if p_val < 0: errors['price_b2b'] = "ราคา B2B ต้องไม่ติดลบ"
                else: price_b2b = p_val
            except ValueError: errors['price_b2b'] = "รูปแบบราคา B2B ไม่ถูกต้อง"

        render_context['errors'] = errors

        # ถ้ามี errors
        if errors:
            for field, msg in errors.items():
                flash(f"{field.replace('_', ' ').title()}: {msg}", "warning")
            # Render ฟอร์มเดิมพร้อม error และข้อมูลที่ user กรอก
            return render_template('edit_sku.html', **render_context)

        # --- ถ้าไม่มี errors ---
        # อัปเดตข้อมูลใน dictionary ของ skus_data
        skus_data[sku]['name'] = name
        skus_data[sku]['category'] = category
        skus_data[sku]['shelf_life_days'] = shelf_life_days
        skus_data[sku]['reorder_point'] = reorder_point
        skus_data[sku]['price_b2c'] = price_b2c
        skus_data[sku]['price_b2b'] = price_b2b

        # บันทึกข้อมูลที่อัปเดตแล้ว
        save_skus(skus_data)

        flash(f"แก้ไขข้อมูล SKU '{sku}' เรียบร้อยแล้ว", "success")
        return redirect(url_for('list_skus'))

    else: # GET request
        # แสดงฟอร์มพร้อมข้อมูลเดิมของ SKU นั้นๆ
        # form_data ถูกตั้งค่าไว้แล้วตอนต้นด้วยข้อมูลปัจจุบัน
        return render_template('edit_sku.html', **render_context)


@app.route('/delete_sku/<sku>', methods=['POST'], endpoint='delete_sku')
def delete_sku(sku):
    """จัดการการลบ SKU (ต้องไม่มีสต็อกคงเหลือ)"""
    skus_data = load_skus()
    inventory = load_inventory()

    # ตรวจสอบว่า SKU มีอยู่ในรายการ SKU หรือไม่
    if sku not in skus_data:
         flash(f"ไม่พบ SKU Code: {sku} ที่จะลบ", "warning")
         return redirect(url_for('list_skus'))

    # ตรวจสอบว่ามีสต็อกของ SKU นี้เหลืออยู่หรือไม่ (ที่ไม่ใช่ bad location)
    sku_in_active_inventory = any(
        b.get('sku') == sku and b.get('quantity', 0) > 0 and b.get('location') != 'bad'
        for b in inventory.get('batches', [])
    )

    if sku_in_active_inventory:
        flash(f"ไม่สามารถลบ SKU '{sku}' ได้ เนื่องจากยังมีสต็อกสินค้าคงเหลือ (ที่ไม่หมดอายุ)", "danger")
        return redirect(url_for('list_skus'))

    # ถ้าไม่มีสต็อก หรือมีแต่หมดอายุแล้ว -> สามารถลบได้
    deleted_name = skus_data.pop(sku).get('name', sku) # ลบออกจาก dict และเก็บชื่อไว้แสดงผล
    save_skus(skus_data) # บันทึกข้อมูล SKU ที่ลบออกไปแล้ว
    flash(f"ลบ SKU '{deleted_name}' ({sku}) เรียบร้อยแล้ว", "success")

    # พิจารณา: อาจจะต้องการลบ batch ที่เป็น 'bad' ของ SKU นี้ออกจาก inventory ด้วยหรือไม่?
    # current logic ไม่ได้ลบ batch 'bad' อัตโนมัติ

    return redirect(url_for('list_skus'))

# --- Inventory Management Routes ---

@app.route('/add_stock', methods=['GET', 'POST'], endpoint='add_stock')
def add_stock():
    """หน้าฟอร์มสำหรับเพิ่มสต็อกสินค้า (รับเข้า)"""
    skus_data = load_skus()

    # ถ้ายังไม่มี SKU เลย ให้ redirect ไปหน้าเพิ่ม SKU ก่อน
    if not skus_data:
        flash("ยังไม่มีข้อมูล SKU ในระบบ กรุณาเพิ่ม SKU ก่อนทำการเพิ่มสต็อก", "warning")
        return redirect(url_for('add_sku'))

    # ค่าเริ่มต้นสำหรับ context
    today_bkk_str = datetime.now(BANGKOK_TZ).strftime('%Y-%m-%d')
    render_context = {
        'skus': skus_data,
        'current_date': today_bkk_str, # แสดงวันที่ปัจจุบันเป็นค่าเริ่มต้น
        'errors': {},
        'form_data': {'arrival_date': today_bkk_str} # ใส่ค่า default วันที่
    }

    if request.method == 'POST':
        form_data = request.form.to_dict()
        render_context['form_data'] = form_data

        sku = form_data.get('sku')
        quantity_str = form_data.get('quantity')
        arrival_date_str = form_data.get('arrival_date') # format YYYY-MM-DD จาก input type="date"

        errors = {}

        # --- Validation ---
        selected_sku_info = skus_data.get(sku)
        if not sku:
            errors['sku'] = "ต้องเลือก SKU ของสินค้า"
        elif not selected_sku_info:
            errors['sku'] = f"ไม่พบข้อมูลสำหรับ SKU Code: {sku}" # ควรจะไม่เกิดถ้า dropdown ถูกสร้างถูกต้อง

        quantity = 0
        if not quantity_str:
            errors['quantity'] = "ต้องระบุจำนวนที่รับเข้า"
        else:
            try:
                quantity = int(quantity_str)
                if quantity <= 0:
                    errors['quantity'] = "จำนวนต้องเป็นเลขจำนวนเต็มบวก"
            except ValueError:
                errors['quantity'] = "จำนวนต้องเป็นตัวเลข"

        arrival_dt_utc = None
        if not arrival_date_str:
            errors['arrival_date'] = "ต้องระบุวันที่รับสินค้า"
        else:
            try:
                # แปลง string YYYY-MM-DD เป็น datetime object (naive)
                arrival_date_naive = datetime.strptime(arrival_date_str, '%Y-%m-%d').date()
                # กำหนด timezone เป็น Bangkok (ตั้งเวลาเป็น 00:00:00)
                arrival_dt_bkk = BANGKOK_TZ.localize(datetime.combine(arrival_date_naive, datetime.min.time()))
                # แปลงเป็น UTC เพื่อเก็บในระบบ
                arrival_dt_utc = arrival_dt_bkk.astimezone(pytz.utc)

                # ตรวจสอบว่าวันที่รับเข้าไม่ใช่วันในอนาคต (เทียบ date() เพื่อไม่สนเวลา)
                if arrival_date_naive > datetime.now(BANGKOK_TZ).date():
                    errors['arrival_date'] = "วันที่รับสินค้าต้องไม่ใช่วันในอนาคต"

            except ValueError:
                errors['arrival_date'] = "รูปแบบวันที่รับสินค้าไม่ถูกต้อง (YYYY-MM-DD)"

        # ตรวจสอบ Shelf life หลังจากผ่าน validation อื่นๆ
        shelf_life_days = None
        if not errors and selected_sku_info:
            shelf_life_days = selected_sku_info.get('shelf_life_days')
            if not shelf_life_days or not isinstance(shelf_life_days, int) or shelf_life_days <= 0:
                 errors['sku'] = f"SKU '{sku}' ไม่ได้กำหนดอายุสินค้า (Shelf Life Days) หรือกำหนดไม่ถูกต้อง กรุณาแก้ไขข้อมูล SKU"
                 # อาจจะเพิ่ม error field เฉพาะ shelf_life ด้วยก็ได้
                 # errors['shelf_life'] = "Shelf life ไม่ถูกต้องสำหรับ SKU นี้"


        render_context['errors'] = errors
        # ถ้ามี error
        if errors:
             for field, msg in errors.items(): flash(f"{field.replace('_', ' ').title()}: {msg}", "warning")
             # ส่ง skus ทั้งหมดกลับไปให้ template อีกครั้ง
             render_context['skus'] = skus_data
             return render_template('add_stock.html', **render_context)

        # --- ถ้าไม่มี errors ---
        try:
            # คำนวณวันหมดอายุ (UTC)
            expiry_date_utc = arrival_dt_utc + timedelta(days=shelf_life_days)

            # สร้าง Batch ID ที่ไม่ซ้ำกัน
            batch_id = str(uuid.uuid4())

            # สร้างข้อมูล Batch ใหม่
            new_batch = {
                "batch_id": batch_id,
                "sku": sku,
                "quantity": quantity,
                "location": "back_stock", # สินค้าใหม่เข้า Back Stock ก่อนเสมอ
                "arrival_date": arrival_dt_utc.isoformat(timespec='seconds').replace('+00:00', 'Z'), # เก็บเป็น ISO format UTC
                "expiry_date": expiry_date_utc.isoformat(timespec='seconds').replace('+00:00', 'Z') # เก็บเป็น ISO format UTC
            }

            # โหลด inventory ล่าสุด, เพิ่ม batch ใหม่, และบันทึก
            inventory = load_inventory()
            inventory['batches'].append(new_batch)
            save_inventory(inventory)

            sku_name = selected_sku_info.get('name', sku)
            flash(f"เพิ่มสต็อก '{sku_name}' จำนวน {quantity} ชิ้น (รับวันที่: {arrival_date_str}, Batch ID: ...{batch_id[-6:]}) เข้าสู่หลังร้านเรียบร้อยแล้ว", "success")
            return redirect(url_for('index')) # กลับไปหน้าหลัก

        except Exception as e:
            print(f"Error creating batch for SKU {sku}: {e}")
            flash(f"เกิดข้อผิดพลาดในการสร้าง Batch: {e}", "danger")
            # ส่ง skus กลับไป template ด้วย
            render_context['skus'] = skus_data
            return render_template('add_stock.html', **render_context)

    else: # GET request
        # ส่ง skus ไปให้ template สำหรับ dropdown
        render_context['skus'] = skus_data
        return render_template('add_stock.html', **render_context)


@app.route('/move_to_display', methods=['GET', 'POST'], endpoint='move_to_display')
def move_to_display():
    """หน้าฟอร์มสำหรับย้ายสินค้าจาก Back Stock ไป Display (หน้าร้าน)"""
    skus_data = load_skus()
    inventory = load_inventory()
    batches = inventory.get('batches', [])

    # 1. กรองหา Batch ที่อยู่ใน Back Stock และมีจำนวน > 0
    back_stock_batches = [
        b for b in batches
        if b.get('location') == 'back_stock' and b.get('quantity', 0) > 0
    ]

    # 2. เตรียมข้อมูลสำหรับ Dropdown และการตรวจสอบจำนวน
    available_skus_in_back = {} # เก็บข้อมูล SKU ที่มีใน back stock
    aggregated_back_stock = {} # เก็บจำนวนรวมของแต่ละ SKU ใน back stock

    if back_stock_batches:
        # เรียง Batch ตามวันหมดอายุ (เก่าไปใหม่) -> วันรับเข้า (เก่าไปใหม่) เพื่อใช้หลัก FIFO
        back_stock_batches.sort(key=lambda b: (
            b.get('expiry_date', ''), # หมดอายุก่อน ย้ายก่อน
            b.get('arrival_date', '') # ถ้าหมดอายุวันเดียวกัน ให้เอาของเข้าก่อนออกก่อน
        ))

        # รวบรวม SKU และจำนวนที่มีใน back stock
        unique_skus_in_back = sorted(list(set(b['sku'] for b in back_stock_batches)))
        for sku_code in unique_skus_in_back:
            if sku_code in skus_data:
                available_skus_in_back[sku_code] = skus_data[sku_code]
                # คำนวณจำนวนรวมของ SKU นี้ใน back stock
                aggregated_back_stock[sku_code] = sum(
                    b['quantity'] for b in back_stock_batches if b['sku'] == sku_code
                )
            else:
                # กรณีข้อมูลไม่สอดคล้องกัน (มี batch แต่ไม่มีข้อมูล SKU)
                print(f"!!! Warning: SKU '{sku_code}' exists in back stock batches but not found in {SKU_FILE} !!!")
                # อาจจะไม่แสดง SKU นี้ให้ย้าย หรือแสดงพร้อมคำเตือน

    # ค่าเริ่มต้นสำหรับ context
    render_context = {
        'skus': available_skus_in_back, # ส่งเฉพาะ SKU ที่มีใน back stock
        'back_stock_agg': aggregated_back_stock, # ส่งจำนวนรวมแต่ละ SKU
        'errors': {},
        'form_data': {}
    }

    # --- POST Request Handling ---
    if request.method == 'POST':
        form_data = request.form.to_dict()
        render_context['form_data'] = form_data

        sku_to_move = form_data.get('sku')
        quantity_str = form_data.get('quantity')
        errors = {}

        # --- Validation ---
        if not sku_to_move:
            errors['sku'] = "ต้องเลือก SKU ที่ต้องการย้าย"
        elif sku_to_move not in available_skus_in_back:
            # ควรจะไม่เกิดถ้า dropdown ถูกสร้างถูกต้อง
            errors['sku'] = f"ไม่พบ SKU '{sku_to_move}' ในสต็อกหลังร้าน หรือข้อมูล SKU ไม่ถูกต้อง"

        requested_quantity = 0
        total_available_for_sku = aggregated_back_stock.get(sku_to_move, 0)
        if not quantity_str:
            errors['quantity'] = "ต้องระบุจำนวนที่ต้องการย้าย"
        else:
            try:
                requested_quantity = int(quantity_str)
                if requested_quantity <= 0:
                    errors['quantity'] = "จำนวนต้องเป็นเลขจำนวนเต็มบวก"
                elif sku_to_move in aggregated_back_stock and requested_quantity > total_available_for_sku:
                     errors['quantity'] = f"จำนวนที่ต้องการย้าย ({requested_quantity}) มากกว่าจำนวนที่มีในหลังร้าน ({total_available_for_sku})"
            except ValueError:
                errors['quantity'] = "จำนวนต้องเป็นตัวเลข"

        render_context['errors'] = errors
        # ถ้ามี errors
        if errors:
            for field, msg in errors.items(): flash(f"{field.replace('_', ' ').title()}: {msg}", "warning")
            # ส่งข้อมูล skus และ back_stock_agg กลับไปใหม่
            render_context['skus'] = available_skus_in_back
            render_context['back_stock_agg'] = aggregated_back_stock
            return render_template('move_to_display.html', **render_context)

        # --- ถ้าไม่มี errors: ทำการย้าย ---
        # โหลดข้อมูล inventory ล่าสุดเพื่อป้องกัน race condition (ถ้ามี user อื่นใช้งานพร้อมกัน)
        # ใน simple app นี้ อาจจะไม่จำเป็นต้องโหลดซ้ำ แต่เป็น practice ที่ดี
        current_inventory = load_inventory()
        all_current_batches = current_inventory.get('batches', [])

        quantity_left_to_move = requested_quantity
        moved_count = 0
        indices_to_update = {} # เก็บ index และจำนวนใหม่ของ batch เดิม
        batches_to_add = []    # เก็บ batch ใหม่ที่จะสร้างสำหรับ display
        indices_of_source_batches = [] # เก็บ index ของ batch ที่เป็น source

        # หา Batch ต้นทางที่เกี่ยวข้อง (เฉพาะ SKU ที่เลือก, อยู่ back_stock, มีของ) และเรียงลำดับ FIFO
        source_batches_info = sorted(
            [
                (i, b) for i, b in enumerate(all_current_batches)
                if b.get('sku') == sku_to_move
                and b.get('location') == 'back_stock'
                and b.get('quantity', 0) > 0
            ],
            key=lambda item: (item[1].get('expiry_date', ''), item[1].get('arrival_date', ''))
        )

        # วน loop ตามลำดับ FIFO เพื่อดึงของออกมา
        for original_index, batch_data in source_batches_info:
            if quantity_left_to_move <= 0:
                break # ย้ายครบตามจำนวนที่ต้องการแล้ว

            available_in_this_batch = batch_data['quantity']
            # จำนวนที่จะย้ายจาก batch นี้ คือ จำนวนที่น้อยกว่าระหว่าง ของที่มี กับ ของที่ยังต้องการ
            move_from_this_batch = min(available_in_this_batch, quantity_left_to_move)

            if move_from_this_batch > 0:
                # ลดจำนวนใน Batch เดิม (เก็บข้อมูล update ไว้ก่อน)
                new_quantity_original = available_in_this_batch - move_from_this_batch
                indices_to_update[original_index] = new_quantity_original
                if original_index not in indices_of_source_batches:
                    indices_of_source_batches.append(original_index)

                # สร้าง Batch ใหม่สำหรับ Display
                # ใช้ Batch ID ใหม่ แต่คง arrival/expiry เดิมไว้
                new_display_batch = {
                    "batch_id": str(uuid.uuid4()), # ID ใหม่เสมอสำหรับ display batch
                    "sku": sku_to_move,
                    "quantity": move_from_this_batch,
                    "location": "display", # ย้ายไป display
                    "arrival_date": batch_data['arrival_date'],
                    "expiry_date": batch_data['expiry_date']
                    # อาจจะเพิ่ม field 'source_batch_id': batch_data['batch_id'] ถ้าต้องการ track กลับ
                }
                batches_to_add.append(new_display_batch)

                # อัปเดตจำนวนที่ย้ายไปแล้ว และจำนวนที่ยังต้องการย้าย
                moved_count += move_from_this_batch
                quantity_left_to_move -= move_from_this_batch

        # --- อัปเดต Inventory จริง ---
        if moved_count > 0:
            final_batches = []
            indices_processed = set()

            # อัปเดต batch เดิมที่ถูกดึงของออกไป
            for idx, qty in indices_to_update.items():
                 if qty > 0: # ถ้า batch เดิมยังเหลือของ
                      updated_batch = all_current_batches[idx].copy()
                      updated_batch['quantity'] = qty
                      final_batches.append(updated_batch)
                 # ถ้า qty == 0 คือ batch เดิมหมด จะไม่ถูกเพิ่มกลับเข้ามา (เหมือนเป็นการลบ)
                 indices_processed.add(idx)


            # เพิ่ม batch อื่นๆ ที่ไม่เกี่ยวข้องกับการย้ายครั้งนี้
            for i, batch in enumerate(all_current_batches):
                 if i not in indices_to_update: # Batch ที่ไม่ได้เป็น source ของการย้ายครั้งนี้
                     final_batches.append(batch)

            # เพิ่ม batch ใหม่ที่สร้างสำหรับ display
            final_batches.extend(batches_to_add)

            # บันทึก inventory ที่ปรับปรุงแล้ว
            current_inventory['batches'] = final_batches
            save_inventory(current_inventory)

            sku_name = skus_data.get(sku_to_move, {}).get('name', sku_to_move)
            flash(f"ย้าย '{sku_name}' จำนวน {moved_count} ชิ้น จากหลังร้านไปยังหน้าร้านเรียบร้อยแล้ว", "success")
        elif requested_quantity > 0:
            # กรณีที่ requested > 0 แต่ moved_count = 0 (อาจเกิดจาก race condition หรือ logic error)
             flash("เกิดข้อผิดพลาด: ไม่สามารถย้ายสินค้าได้ตามที่ร้องขอ", "danger")
        else:
             # กรณี requested_quantity <= 0 (ไม่ควรเกิดถ้า validation ทำงาน)
             flash("จำนวนที่ต้องการย้ายต้องมากกว่า 0", "warning")


        return redirect(url_for('index'))

    else: # GET request
        # ถ้าไม่มีของใน back stock เลย ให้แจ้ง user และ redirect กลับ
        if not available_skus_in_back:
            flash("ไม่มีสินค้าในสต็อกหลังร้านให้ย้ายในขณะนี้", "info")
            return redirect(url_for('index'))
        # แสดงฟอร์ม
        return render_template('move_to_display.html', **render_context)


@app.route('/record_sale', methods=['GET', 'POST'], endpoint='record_sale')
def record_sale():
    """หน้าฟอร์มสำหรับบันทึกการขายสินค้า (ตัดสต็อก FIFO จาก RTC2->RTC1->Display)"""
    skus_data = load_skus()
    inventory = load_inventory()
    batches = inventory.get('batches', [])

    # 1. กำหนดลำดับความสำคัญของ Location ในการขาย
    sellable_locations = ['rtc2', 'rtc1', 'display']
    location_sell_priority = {loc: i for i, loc in enumerate(sellable_locations)} # RTC2 (0) -> RTC1 (1) -> Display (2)

    # 2. กรองหา Batch ที่พร้อมขาย (อยู่ใน location ที่กำหนด และมีจำนวน > 0)
    sellable_batches = [
        b for b in batches
        if b.get('location') in sellable_locations and b.get('quantity', 0) > 0
    ]

    # 3. เตรียมข้อมูลสำหรับ Dropdown และการตรวจสอบจำนวน
    available_skus_to_sell = {} # เก็บข้อมูล SKU ที่มีขาย
    aggregated_sellable_stock = {} # เก็บจำนวนรวมของแต่ละ SKU ที่ขายได้

    if sellable_batches:
        # เรียง Batch ตาม: ลำดับความสำคัญ Location -> วันหมดอายุ (เก่าไปใหม่) -> วันรับเข้า (เก่าไปใหม่)
        sellable_batches.sort(key=lambda b: (
            location_sell_priority.get(b.get('location'), 99), # ขายจาก RTC2 -> RTC1 -> Display ก่อน
            b.get('expiry_date', ''),                        # ถ้า location เดียวกัน เอาหมดอายุก่อน
            b.get('arrival_date', '')                         # ถ้าหมดอายุวันเดียวกัน เอาของเข้าก่อน
        ))

        # รวบรวม SKU และจำนวนที่พร้อมขาย
        unique_sellable_skus = sorted(list(set(b['sku'] for b in sellable_batches)))
        for sku_code in unique_sellable_skus:
            if sku_code in skus_data:
                available_skus_to_sell[sku_code] = skus_data[sku_code]
                # คำนวณจำนวนรวมของ SKU นี้ที่ขายได้
                aggregated_sellable_stock[sku_code] = sum(
                    b['quantity'] for b in sellable_batches if b['sku'] == sku_code
                )
            else:
                print(f"!!! Warning: SKU '{sku_code}' is sellable but not found in {SKU_FILE} !!!")

    # ค่าเริ่มต้นสำหรับ context
    render_context = {
        'skus': available_skus_to_sell, # ส่งเฉพาะ SKU ที่มีขาย
        'sellable_stock_agg': aggregated_sellable_stock, # ส่งจำนวนรวมแต่ละ SKU
        'errors': {},
        'form_data': {}
    }

    # --- POST Request Handling ---
    if request.method == 'POST':
        form_data = request.form.to_dict()
        render_context['form_data'] = form_data

        sku_to_sell = form_data.get('sku')
        quantity_str = form_data.get('quantity')
        errors = {}

        # --- Validation ---
        if not sku_to_sell:
            errors['sku'] = "ต้องเลือก SKU ที่ต้องการบันทึกการขาย"
        elif sku_to_sell not in available_skus_to_sell:
            errors['sku'] = f"ไม่พบ SKU '{sku_to_sell}' ในสต็อกที่พร้อมขาย (หน้าร้าน/RTC)"

        requested_quantity = 0
        total_available_for_sku = aggregated_sellable_stock.get(sku_to_sell, 0)
        if not quantity_str:
            errors['quantity'] = "ต้องระบุจำนวนที่ขาย"
        else:
            try:
                requested_quantity = int(quantity_str)
                if requested_quantity <= 0:
                    errors['quantity'] = "จำนวนต้องเป็นเลขจำนวนเต็มบวก"
                elif sku_to_sell in aggregated_sellable_stock and requested_quantity > total_available_for_sku:
                     errors['quantity'] = f"จำนวนที่ต้องการขาย ({requested_quantity}) มากกว่าจำนวนที่มีในสต็อกพร้อมขาย ({total_available_for_sku})"
            except ValueError:
                errors['quantity'] = "จำนวนต้องเป็นตัวเลข"

        render_context['errors'] = errors
        # ถ้ามี errors
        if errors:
            for field, msg in errors.items(): flash(f"{field.replace('_', ' ').title()}: {msg}", "warning")
            render_context['skus'] = available_skus_to_sell
            render_context['sellable_stock_agg'] = aggregated_sellable_stock
            return render_template('record_sale.html', **render_context)

        # --- ถ้าไม่มี errors: ทำการตัดสต็อก ---
        current_inventory = load_inventory()
        all_current_batches = current_inventory.get('batches', [])

        quantity_left_to_sell = requested_quantity
        sold_count = 0
        indices_to_update = {} # เก็บ index และจำนวนใหม่ของ batch เดิม
        indices_of_source_batches = [] # เก็บ index ของ batch ที่เป็น source

        # หา Batch ต้นทาง (เฉพาะ SKU, อยู่ใน location ที่ขายได้, มีของ) และเรียงลำดับตาม Priority + FIFO
        source_batches_info = sorted(
            [
                (i, b) for i, b in enumerate(all_current_batches)
                if b.get('sku') == sku_to_sell
                and b.get('location') in sellable_locations
                and b.get('quantity', 0) > 0
            ],
             key=lambda item: (
                location_sell_priority.get(item[1].get('location'), 99),
                item[1].get('expiry_date', ''),
                item[1].get('arrival_date', '')
            )
        )

        # วน loop ตามลำดับเพื่อตัดสต็อก
        for original_index, batch_data in source_batches_info:
            if quantity_left_to_sell <= 0:
                break

            available_in_this_batch = batch_data['quantity']
            sell_from_this_batch = min(available_in_this_batch, quantity_left_to_sell)

            if sell_from_this_batch > 0:
                # ลดจำนวนใน Batch เดิม (เก็บข้อมูล update)
                new_quantity_original = available_in_this_batch - sell_from_this_batch
                indices_to_update[original_index] = new_quantity_original
                if original_index not in indices_of_source_batches:
                     indices_of_source_batches.append(original_index)


                sold_count += sell_from_this_batch
                quantity_left_to_sell -= sell_from_this_batch

        # --- อัปเดต Inventory จริง (เฉพาะเมื่อขายได้ครบตามจำนวนที่ต้องการ) ---
        # **สำคัญ:** เราจะบันทึกก็ต่อเมื่อ `sold_count == requested_quantity` เพื่อป้องกันการบันทึกการขายบางส่วน
        if sold_count == requested_quantity and sold_count > 0:
            final_batches = []
            # สร้าง list ใหม่โดยอัปเดต/ลบ batch ที่เกี่ยวข้อง
            for i, batch in enumerate(all_current_batches):
                 if i in indices_to_update: # ถ้าเป็น batch ที่ถูกแก้ไข
                      new_qty = indices_to_update[i]
                      if new_qty > 0: # ถ้ายังเหลือของ
                           updated_batch = batch.copy()
                           updated_batch['quantity'] = new_qty
                           final_batches.append(updated_batch)
                      # ถ้า new_qty == 0 คือ batch หมด ไม่ต้องเพิ่มกลับ
                 else: # ถ้าเป็น batch อื่นที่ไม่เกี่ยว
                      final_batches.append(batch)


            current_inventory['batches'] = final_batches
            save_inventory(current_inventory)

            sku_name = skus_data.get(sku_to_sell, {}).get('name', sku_to_sell)
            flash(f"บันทึกการขาย '{sku_name}' จำนวน {sold_count} ชิ้น เรียบร้อยแล้ว (ตัดสต็อกสำเร็จ)", "success")

        elif requested_quantity > 0:
            # กรณีนี้อาจเกิดเมื่อมีการเปลี่ยนแปลงสต็อกระหว่างที่ user เปิดฟอร์มกับตอนกด submit
            # หรืออาจจะ logic error
            # ไม่ควรบันทึกถ้าขายได้ไม่ครบ
             flash(f"ขาย SKU '{sku_to_sell}' ไม่สำเร็จตามจำนวนที่ต้องการ ({sold_count}/{requested_quantity}) - สต็อกอาจมีการเปลี่ยนแปลง กรุณาลองใหม่ **ไม่ได้บันทึกการขาย**", "danger")
        else:
             flash("จำนวนที่ขายต้องมากกว่า 0", "warning")

        return redirect(url_for('index'))

    else: # GET request
        if not available_skus_to_sell:
            flash("ไม่มีสินค้าพร้อมขายในขณะนี้ (หน้าร้าน/RTC)", "info")
            return redirect(url_for('index'))
        return render_template('record_sale.html', **render_context)


# --- Dashboard Route ---
@app.route('/dashboard', endpoint='dashboard')
def dashboard():
    """หน้าแสดงข้อมูลสรุปภาพรวมและแจ้งเตือน"""
    inventory = load_inventory()
    skus_data = load_skus()
    batches = inventory.get('batches', [])

    # อัปเดตสถานะก่อนคำนวณ Dashboard
    updated_batches, changed = update_batch_statuses(batches, skus_data)
    if changed:
        print("Dashboard: Batch statuses updated, saving changes...")
        inventory['batches'] = updated_batches
        save_inventory(inventory)
        batches_to_process = updated_batches
    else:
        batches_to_process = batches

    # --- เตรียมข้อมูลสำหรับ Dashboard ---
    now_utc = datetime.now(timezone.utc)
    expiring_soon_threshold_days = 3 # สินค้าที่หมดอายุภายใน X วัน
    expiring_soon_batches = []      # รายการ batch ที่ใกล้หมดอายุ
    status_summary = {loc: {'total_qty': 0, 'sku_count': set()} for loc in ['display', 'back_stock', 'rtc1', 'rtc2', 'bad']}
    category_summary = {cat: {'total_qty': 0, 'sku_count': set()} for cat in ALLOWED_CATEGORIES}
    bad_stock_summary = {}        # สรุปจำนวนสินค้าหมดอายุ (แยกตาม SKU)
    current_stock_totals = {}     # จำนวนรวมของแต่ละ SKU (ไม่นับ bad) สำหรับเช็ค low stock

    # เรียงตามวันหมดอายุเพื่อแสดงรายการใกล้หมดอายุให้ชัดเจน
    batches_to_process.sort(key=lambda b: b.get('expiry_date', ''))

    for batch in batches_to_process:
        sku = batch.get('sku')
        qty = batch.get('quantity', 0)
        loc = batch.get('location')
        expiry_str = batch.get('expiry_date')
        sku_info = skus_data.get(sku)

        # ข้าม batch ที่ไม่มีจำนวน, ไม่มี SKU, หรือหาข้อมูล SKU ไม่เจอ
        if qty <= 0 or not sku or not sku_info:
            continue

        # 1. สรุปตามสถานะ (Location)
        if loc in status_summary:
            status_summary[loc]['total_qty'] += qty
            status_summary[loc]['sku_count'].add(sku)

        # 2. สรุปตาม Category
        category = sku_info.get('category')
        if category and category in category_summary: # ตรวจสอบว่า category ไม่ใช่ None และอยู่ใน list ที่อนุญาต
             category_summary[category]['total_qty'] += qty
             category_summary[category]['sku_count'].add(sku)
        elif category: # ถ้ามี category แต่ไม่อยู่ใน ALLOWED_CATEGORIES (อาจเป็นข้อมูลเก่า)
             # อาจจะรวมไว้ใน 'อื่นๆ' หรือ category พิเศษ
             if 'อื่นๆ' in category_summary:
                 category_summary['อื่นๆ']['total_qty'] += qty
                 category_summary['อื่นๆ']['sku_count'].add(sku)
             print(f"Warning: Batch with SKU '{sku}' has unknown category '{category}'. Grouping under 'อื่นๆ'.")


        # 3. ตรวจสอบสินค้าใกล้หมดอายุ (Expiring Soon) - รวมทุก location ที่ยังไม่ bad
        if loc != 'bad' and expiry_str:
            try:
                if expiry_str.endswith('Z'):
                    expiry_dt_utc = datetime.fromisoformat(expiry_str.replace('Z', '+00:00'))
                else:
                    expiry_dt_utc = datetime.fromisoformat(expiry_str)
                    if expiry_dt_utc.tzinfo is None: expiry_dt_utc = expiry_dt_utc.replace(tzinfo=timezone.utc)

                time_until_expiry = expiry_dt_utc - now_utc

                # เช็คว่าหมดอายุภายใน X วัน แต่ยังไม่หมดอายุ
                if timedelta(0) < time_until_expiry <= timedelta(days=expiring_soon_threshold_days):
                    expiring_soon_batches.append(batch) # เก็บ batch ทั้งหมดไปแสดง
            except (ValueError, TypeError):
                 print(f"Warning: Could not parse expiry date '{expiry_str}' for SKU '{sku}' in dashboard.")
                 pass # ข้ามไปถ้า parse date ไม่ได้

        # 4. สรุปสินค้าหมดอายุ (Bad Stock)
        if loc == 'bad':
            bad_stock_summary[sku] = bad_stock_summary.get(sku, 0) + qty

        # 5. คำนวณจำนวนรวมปัจจุบัน (ไม่นับ Bad) เพื่อใช้เช็ค Low Stock
        if loc != 'bad':
            current_stock_totals[sku] = current_stock_totals.get(sku, 0) + qty

    # 6. ตรวจสอบสินค้าที่ถึงจุดสั่งซื้อ (Low Stock)
    low_stock_items = []
    for sku, sku_info in skus_data.items():
        reorder_point = sku_info.get('reorder_point')
        # ตรวจสอบว่าเป็นตัวเลข int และไม่ติดลบ
        if isinstance(reorder_point, int) and reorder_point >= 0:
            current_qty = current_stock_totals.get(sku, 0) # จำนวนปัจจุบัน (ไม่รวม bad)
            if current_qty <= reorder_point:
                low_stock_items.append({
                    'sku': sku,
                    'name': sku_info.get('name', '???'),
                    'current_qty': current_qty,
                    'reorder_point': reorder_point
                })

    # เรียงรายการ Low Stock ตามชื่อ
    low_stock_items.sort(key=lambda item: item['name'])

    # แปลง set ของ sku_count เป็นจำนวน (length)
    for data in status_summary.values():
        data['sku_count'] = len(data['sku_count'])
    for data in category_summary.values():
        data['sku_count'] = len(data['sku_count'])

    # Configuration สำหรับการแสดงผล Location ใน Dashboard (อาจจะเหมือนกับ index)
    location_configs = {
        'display': {'title': 'หน้าร้าน', 'icon': 'bi-shop', 'badge_class': 'text-bg-primary'},
        'back_stock': {'title': 'หลังร้าน', 'icon': 'bi-boxes', 'badge_class': 'text-bg-secondary'},
        'rtc1': {'title': 'RTC-1', 'icon': 'bi-alarm', 'badge_class': 'text-bg-warning'},
        'rtc2': {'title': 'RTC-2', 'icon': 'bi-alarm-fill', 'badge_class': 'text-bg-danger'},
        'bad': {'title': 'หมดอายุ', 'icon': 'bi-x-octagon-fill', 'badge_class': 'text-bg-dark'}
    }

    # รวบรวมข้อมูลทั้งหมดเพื่อส่งไป Template
    dashboard_data = {
        'status_summary': status_summary,
        'expiring_soon': expiring_soon_batches, # ส่งรายการ batch ไปเลย
        'expiring_threshold_days': expiring_soon_threshold_days,
        'bad_stock': bad_stock_summary, # dict {sku: qty}
        'category_summary': {k: v for k, v in category_summary.items() if v['total_qty'] > 0}, # กรองเอาเฉพาะ category ที่มีของ
        'low_stock': low_stock_items # list of dicts
    }

    return render_template(
        'dashboard.html',
        dashboard_data=dashboard_data,
        skus_data=skus_data, # ส่งไปเพื่อใช้แสดงชื่อ SKU จาก bad_stock/low_stock
        location_configs=location_configs
    )

# --- Pricing Route ---
@app.route('/pricing', endpoint='view_pricing')
def view_pricing():
    """หน้าแสดงตารางราคา B2C/B2B แยกตาม Category"""
    skus_data = load_skus()

    # ใช้ defaultdict(list) เพื่อความสะดวกในการ group
    grouped_prices = defaultdict(list)

    # เรียง SKU ตามชื่อก่อนทำการ group (เพื่อให้ในแต่ละ category เรียงตามชื่อด้วย)
    sorted_skus = sorted(skus_data.items(), key=lambda item: item[1].get('name', item[0]))

    for sku_code, sku_info in sorted_skus:
        category = sku_info.get('category', None) # ดึง category
        if not category or category not in ALLOWED_CATEGORIES:
             category = 'อื่นๆ' # จัดเข้ากลุ่ม 'อื่นๆ' ถ้าไม่มี หรือไม่อยู่ใน list

        # ดึงราคาและพยายามแปลงเป็น float (ถ้ามีค่า)
        price_b2c = sku_info.get('price_b2c')
        price_b2b = sku_info.get('price_b2b')

        try:
            price_b2c_float = float(price_b2c) if price_b2c is not None else None
        except (ValueError, TypeError):
            price_b2c_float = None # ถ้าแปลงไม่ได้ให้เป็น None

        try:
            price_b2b_float = float(price_b2b) if price_b2b is not None else None
        except (ValueError, TypeError):
            price_b2b_float = None

        # เพิ่มข้อมูล SKU ลงใน group ของ category นั้นๆ
        grouped_prices[category].append({
            'sku': sku_code,
            'name': sku_info.get('name', '???'), # ใช้ชื่อ SKU หรือ ??? ถ้าไม่มี
            'price_b2c': price_b2c_float,
            'price_b2b': price_b2b_float
        })

    # สร้างลำดับ Category สำหรับการแสดงผล (เอาตาม ALLOWED_CATEGORIES ก่อน แล้วตามด้วย อื่นๆ ถ้ามี)
    category_order = ALLOWED_CATEGORIES + ['อื่นๆ']

    # เรียง grouped_prices ตาม category_order
    ordered_grouped_prices = {
        cat: grouped_prices[cat] for cat in category_order if cat in grouped_prices
    }

    return render_template(
        'pricing.html',
        grouped_prices=ordered_grouped_prices,
        categories=ordered_grouped_prices.keys() # ส่ง list ของ category ที่มีข้อมูลไป
    )


# --- Main execution ---
if __name__ == '__main__':
    # ควรตั้งค่า Port ผ่าน Environment Variable ด้วย
    port = int(os.environ.get('PORT', 5001))
    # debug=True เหมาะสำหรับ Development เท่านั้น
    # ใน Production ควรใช้ Waitress หรือ Gunicorn และตั้ง debug=False
    use_debug = os.environ.get('FLASK_DEBUG', 'true').lower() == 'true'
    print(f" * Running on http://0.0.0.0:{port}/ (Debug: {use_debug})")
    app.run(debug=use_debug, host='0.0.0.0', port=port)