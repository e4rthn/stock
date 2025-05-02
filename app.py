# app.py (แก้ไข Inventory Routes และลบ Helper เก่า)

import json
import os
from datetime import datetime, timedelta, timezone
import uuid
from math import floor # <--- เพิ่ม import floor
from flask import Flask, render_template, request, redirect, url_for, flash

# --- (ส่วน setup อื่นๆ เหมือนเดิม) ---
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'a_default_secret_key_change_me')

SKU_FILE = 'skus.json'
INVENTORY_FILE = 'inventory.json'
ALLOWED_CATEGORIES = sorted(['หมู', 'ไก่', 'เนื้อ', 'อาหารทะเล', 'ผัก', 'ผลไม้', 'เครื่องดื่ม', 'อื่นๆ'])

# --- Context Processors ---
@app.context_processor
def inject_current_year():
    # ... (เหมือนเดิม) ...
     return {'current_year': datetime.now(timezone.utc).year}

@app.context_processor
def utility_processor():
    # ... (ฟังก์ชัน format_iso_date และ format_time_remaining เหมือนเดิม) ...
    def format_iso_date(date_str, fmt='%Y-%m-%d %H:%M'):
        if not date_str: return "-"
        try:
            dt_utc = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt_utc.strftime(fmt) + " UTC"
        except (ValueError, TypeError): return date_str
    def format_time_remaining(expiry_date_str):
        if not expiry_date_str: return '<span class="text-muted">N/A</span>'
        try:
            now = datetime.now(timezone.utc)
            expiry_dt = datetime.fromisoformat(expiry_date_str.replace('Z', '+00:00'))
            delta = expiry_dt - now
            if delta.total_seconds() <= 0: return '<span class="badge bg-danger">หมดอายุ</span>'
            days = delta.days; hours = floor(delta.seconds / 3600); minutes = floor((delta.seconds % 3600) / 60)
            parts = []; text_class = "text-success"
            if days > 1: parts.append(f"{days} วัน")
            elif days == 1: parts.append(f"{days} วัน"); text_class = "text-warning"
            if days < 2 and hours > 0: parts.append(f"{hours} ชม."); text_class = "text-warning";
            if days == 0 and hours < 13 : text_class = "text-danger"
            if days == 0 and minutes > 0 : parts.append(f"{minutes} นาที");
            if hours < 1: text_class = "text-danger"
            if not parts: return '<span class="badge bg-danger">ใกล้หมดอายุมาก</span>'
            remaining_str = " ".join(parts)
            if text_class == "text-danger": return f'<span class="badge bg-danger-subtle text-danger-emphasis">{remaining_str}</span>'
            elif text_class == "text-warning": return f'<span class="badge bg-warning-subtle text-warning-emphasis">{remaining_str}</span>'
            else: return f'<span class="text-success">{remaining_str}</span>'
        except ValueError: return '<span class="text-muted">Error</span>'
    return dict(format_iso_date=format_iso_date, format_time_remaining=format_time_remaining)


# --- Helper Functions (เหมือนเดิม) ---
# ... (load_data, save_data, load_skus, save_skus, load_inventory, save_inventory) ...
def load_data(filename): #...เหมือนเดิม...
    try:
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read();
                if not content:
                    if filename == INVENTORY_FILE: return {"batches": []}
                    return {}
                return json.loads(content)
        else:
            if filename == INVENTORY_FILE: return {"batches": []}
            return {}
    except (IOError, json.JSONDecodeError) as e: print(f"Error loading data from {filename}: {e}"); flash(f"เกิดข้อผิดพลาดในการโหลดข้อมูลจาก {filename}", "danger");
    if filename == INVENTORY_FILE: return {"batches": []}
    return {}
def save_data(filename, data): #...เหมือนเดิม...
    try:
        with open(filename, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
    except IOError as e: print(f"Error saving data to {filename}: {e}"); flash(f"เกิดข้อผิดพลาดในการบันทึกข้อมูลลง {filename}", "danger")
def load_skus(): return load_data(SKU_FILE)
def save_skus(skus_data): save_data(SKU_FILE, skus_data)
def load_inventory(): #...เหมือนเดิม...
    inventory_data = load_data(INVENTORY_FILE);
    if not isinstance(inventory_data, dict) or 'batches' not in inventory_data or not isinstance(inventory_data['batches'], list):
        print(f"Warning: Data in {INVENTORY_FILE} has incorrect structure. Resetting."); inventory = {"batches": []}
    else: inventory = inventory_data
    return inventory
def save_inventory(inventory_data): save_data(INVENTORY_FILE, inventory_data)


# --- ฟังก์ชัน update_batch_statuses (เหมือนเดิม) ---
def update_batch_statuses(batches, skus_data):
    # ... (โค้ด update_batch_statuses เหมือนเดิมจากขั้นตอน 2.1) ...
    now = datetime.now(timezone.utc); updated_batches = []; something_changed = False
    for batch in batches:
        current_location = batch.get('location'); expiry_str = batch.get('expiry_date'); sku = batch.get('sku'); qty = batch.get('quantity', 0); new_batch_data = batch.copy()
        if not expiry_str or not sku or sku not in skus_data or qty <= 0: updated_batches.append(new_batch_data); continue
        try:
            expiry_dt = datetime.fromisoformat(expiry_str.replace('Z', '+00:00')); time_until_expiry = expiry_dt - now; new_location = current_location
            if time_until_expiry <= timedelta(0):
                if current_location != 'bad': new_location = 'bad'
            elif time_until_expiry <= timedelta(hours=12, minutes=30) and current_location in ['display', 'rtc1']: new_location = 'rtc2'
            elif time_until_expiry <= timedelta(days=1, hours=1) and current_location == 'display': new_location = 'rtc1'
            if current_location == 'back_stock' and time_until_expiry <= timedelta(0):
                if new_location != 'bad': new_location = 'bad'
            if new_location != current_location: new_batch_data['location'] = new_location; something_changed = True
            updated_batches.append(new_batch_data)
        except ValueError: print(f"Error parsing date for batch {batch.get('batch_id')}, SKU {sku}. Skipping."); updated_batches.append(new_batch_data)
    return updated_batches, something_changed


# --- Routes ---

@app.route('/', endpoint='index')
def index():
    """หน้าแสดงภาพรวม Inventory (เพิ่มส่ง categories สำหรับ filter)"""
    inventory = load_inventory()
    skus_data = load_skus()
    batches = inventory.get('batches', [])

    # ... (ส่วน update_batch_statuses และ save เหมือนเดิม) ...
    updated_batches, changed = update_batch_statuses(batches, skus_data)
    if changed:
        print("Batch statuses updated, saving changes...")
        inventory['batches'] = updated_batches
        save_inventory(inventory)
        batches_to_process = updated_batches
    else:
        batches_to_process = batches

    location_order = ['display', 'back_stock', 'rtc1', 'rtc2', 'bad']
    location_sort_key = {loc: i for i, loc in enumerate(location_order)}

    valid_batches = [b for b in batches_to_process if b.get('quantity', 0) > 0]

    valid_batches.sort(key=lambda b: (
        location_sort_key.get(b.get('location'), 99),
        b.get('sku', ''),
        b.get('expiry_date', '')
    ))

    location_configs = {
        'display': {'title': 'หน้าร้าน', 'border_status_class': 'status-display', 'icon': 'bi-shop'},
        'back_stock': {'title': 'หลังร้าน', 'border_status_class': 'status-back-stock', 'icon': 'bi-boxes'},
        'rtc1': {'title': 'RTC-1', 'border_status_class': 'status-rtc1', 'icon': 'bi-alarm'},
        'rtc2': {'title': 'RTC-2', 'border_status_class': 'status-rtc2', 'icon': 'bi-alarm-fill'},
        'bad': {'title': 'หมดอายุ', 'border_status_class': 'status-bad', 'icon': 'bi-x-octagon-fill'}
    }

    # ส่งข้อมูล batches, skus, configs, และ categories
    return render_template('index.html',
                           inventory_batches=valid_batches,
                           skus_data=skus_data,
                           location_configs=location_configs,
                           allowed_categories=ALLOWED_CATEGORIES # <-- เพิ่มอันนี้
                           )

@app.route('/skus', endpoint='list_skus')
def list_skus():
    skus_data = load_skus()
    return render_template('list_skus.html', skus=skus_data, categories=ALLOWED_CATEGORIES)

@app.route('/add_sku', methods=['GET', 'POST'], endpoint='add_sku')
def add_sku():
     # ... (โค้ด add_sku เหมือนเดิมจากขั้นตอนก่อนหน้า) ...
    if request.method == 'POST':
        sku_code = request.form.get('sku', '').strip()
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()
        shelf_life_str = request.form.get('shelf_life_days', '').strip()
        if not sku_code or not name or not category or not shelf_life_str:
            flash("กรุณากรอกข้อมูลให้ครบทุกช่อง (SKU, Name, Category, Shelf Life)", "warning")
            return render_template('add_sku.html', categories=ALLOWED_CATEGORIES, sku=sku_code, name=name, selected_category=category, shelf_life=shelf_life_str)
        if category not in ALLOWED_CATEGORIES:
             flash("ประเภทสินค้าไม่ถูกต้อง", "danger")
             return render_template('add_sku.html', categories=ALLOWED_CATEGORIES, sku=sku_code, name=name, selected_category=category, shelf_life=shelf_life_str)
        try:
            shelf_life_days = int(shelf_life_str)
            if shelf_life_days <= 0: raise ValueError("Shelf life must be positive")
        except ValueError:
            flash("อายุสินค้า (Shelf Life) ต้องเป็นจำนวนเต็มบวก (วัน)", "danger")
            return render_template('add_sku.html', categories=ALLOWED_CATEGORIES, sku=sku_code, name=name, selected_category=category, shelf_life=shelf_life_str)
        skus_data = load_skus()
        if sku_code in skus_data:
            flash(f"SKU Code '{sku_code}' มีอยู่แล้ว", "danger")
            return render_template('add_sku.html', categories=ALLOWED_CATEGORIES, sku=sku_code, name=name, selected_category=category, shelf_life=shelf_life_str)
        else:
            skus_data[sku_code] = {'name': name, 'category': category, 'shelf_life_days': shelf_life_days }
            save_skus(skus_data)
            flash(f"เพิ่ม SKU '{name}' ({sku_code}) เรียบร้อยแล้ว", "success")
            return redirect(url_for('list_skus'))
    else:
        return render_template('add_sku.html', categories=ALLOWED_CATEGORIES)


@app.route('/edit_sku/<sku>', methods=['GET', 'POST'], endpoint='edit_sku')
def edit_sku(sku):
     # ... (โค้ด edit_sku เหมือนเดิมจากขั้นตอนก่อนหน้า) ...
    skus_data = load_skus()
    if sku not in skus_data:
        flash(f"ไม่พบ SKU Code: {sku}", "danger")
        return redirect(url_for('list_skus'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()
        shelf_life_str = request.form.get('shelf_life_days', '').strip()
        if not name or not category or not shelf_life_str:
            flash("กรุณากรอกข้อมูลให้ครบทุกช่อง (Name, Category, Shelf Life)", "warning")
            sku_data_for_template = skus_data[sku].copy(); sku_data_for_template['name'] = name; sku_data_for_template['category'] = category; sku_data_for_template['shelf_life_days'] = shelf_life_str
            return render_template('edit_sku.html', categories=ALLOWED_CATEGORIES, sku_code=sku, sku_data=sku_data_for_template)
        if category not in ALLOWED_CATEGORIES:
             flash("ประเภทสินค้าไม่ถูกต้อง", "danger")
             sku_data_for_template = skus_data[sku].copy(); sku_data_for_template['name'] = name; sku_data_for_template['category'] = category; sku_data_for_template['shelf_life_days'] = shelf_life_str
             return render_template('edit_sku.html', categories=ALLOWED_CATEGORIES, sku_code=sku, sku_data=sku_data_for_template)
        try:
            shelf_life_days = int(shelf_life_str)
            if shelf_life_days <= 0: raise ValueError("Shelf life must be positive")
        except ValueError:
            flash("อายุสินค้า (Shelf Life) ต้องเป็นจำนวนเต็มบวก (วัน)", "danger")
            sku_data_for_template = skus_data[sku].copy(); sku_data_for_template['name'] = name; sku_data_for_template['category'] = category; sku_data_for_template['shelf_life_days'] = shelf_life_str
            return render_template('edit_sku.html', categories=ALLOWED_CATEGORIES, sku_code=sku, sku_data=sku_data_for_template)
        skus_data[sku]['name'] = name
        skus_data[sku]['category'] = category
        skus_data[sku]['shelf_life_days'] = shelf_life_days
        save_skus(skus_data)
        flash(f"แก้ไขข้อมูล SKU '{sku}' เรียบร้อยแล้ว", "success")
        return redirect(url_for('list_skus'))
    else:
        return render_template('edit_sku.html', categories=ALLOWED_CATEGORIES, sku_code=sku, sku_data=skus_data[sku])

@app.route('/delete_sku/<sku>', methods=['POST'], endpoint='delete_sku')
def delete_sku(sku):
    # ... (โค้ด delete_sku เหมือนเดิมจากขั้นตอนก่อนหน้า) ...
    skus_data = load_skus()
    inventory = load_inventory()
    sku_in_inventory = False
    for batch in inventory.get('batches', []):
        if batch.get('sku') == sku and batch.get('quantity', 0) > 0:
            sku_in_inventory = True
            break
    if sku_in_inventory:
        flash(f"ไม่สามารถลบ SKU '{sku}' ได้ เนื่องจากยังมีสต็อกสินค้าคงเหลืออยู่ในระบบ", "danger")
        return redirect(url_for('list_skus'))
    if sku in skus_data:
        deleted_name = skus_data[sku].get('name', sku)
        del skus_data[sku]
        save_skus(skus_data)
        flash(f"ลบ SKU '{deleted_name}' ({sku}) เรียบร้อยแล้ว", "success")
    else:
        flash(f"ไม่พบ SKU Code: {sku} ที่จะลบ", "warning")
    return redirect(url_for('list_skus'))


# --- Inventory Management Routes (แก้ไขใหม่) ---

@app.route('/add_stock', methods=['GET', 'POST'], endpoint='add_stock')
def add_stock():
    """หน้าเพิ่มสต็อกสินค้า (บันทึกเป็น Batch พร้อม Arrival Date จากฟอร์ม)"""
    skus_data = load_skus()
    if not skus_data:
         flash("ยังไม่มีข้อมูล SKU กรุณาเพิ่ม SKU ก่อน", "warning")
         return redirect(url_for('add_sku'))

    if request.method == 'POST':
        sku = request.form.get('sku')
        quantity_str = request.form.get('quantity')
        arrival_date_str = request.form.get('arrival_date') # <-- รับค่าวันที่จากฟอร์ม

        # --- ตรวจสอบ Input ---
        if not sku or not quantity_str or not arrival_date_str: # <-- เช็ค arrival_date_str ด้วย
            flash("กรุณากรอกข้อมูลให้ครบทุกช่อง (SKU, Arrival Date, Quantity)", "warning")
            # ส่งค่าที่กรอกค้างไว้กลับไป
            today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            return render_template('add_stock.html', skus=skus_data, current_date=today_str)
        if sku not in skus_data:
             flash(f"ไม่พบ SKU Code ในระบบ: {sku}", "danger")
             today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
             return render_template('add_stock.html', skus=skus_data, current_date=today_str)
        try:
            quantity = int(quantity_str)
            if quantity <= 0: raise ValueError("Quantity must be positive")
        except ValueError:
            flash("จำนวนต้องเป็นเลขบวกเท่านั้น", "danger")
            today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            return render_template('add_stock.html', skus=skus_data, current_date=today_str)

        # --- แปลงและตรวจสอบ Arrival Date ---
        try:
             # แปลง input date string เป็น date object
             arrival_date_part = datetime.strptime(arrival_date_str, '%Y-%m-%d').date()
             # เอาเวลาปัจจุบัน (UTC) มาใช้ร่วมกับวันที่ที่เลือก
             now_time_part = datetime.now(timezone.utc).time()
             # สร้าง datetime object ที่สมบูรณ์ (timezone-aware UTC)
             arrival_date = datetime.combine(arrival_date_part, now_time_part, tzinfo=timezone.utc)

             # (Optional) เช็คว่าเป็นวันที่ในอดีตหรือปัจจุบันหรือไม่ (ไม่ควรเป็นอนาคต)
             if arrival_date > datetime.now(timezone.utc):
                 flash("วันที่รับสินค้าต้องไม่ใช่วันในอนาคต", "warning")
                 today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                 return render_template('add_stock.html', skus=skus_data, current_date=today_str)

        except ValueError:
             flash("รูปแบบวันที่รับสินค้าไม่ถูกต้อง (ต้องเป็น YYYY-MM-DD)", "danger")
             today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
             return render_template('add_stock.html', skus=skus_data, current_date=today_str)
        # --- จบการแปลง Arrival Date ---


        # --- สร้าง Batch ใหม่ ---
        try:
            shelf_life_days = int(skus_data[sku].get('shelf_life_days', 0))
            if shelf_life_days <= 0:
                 flash(f"SKU '{sku}' ไม่ได้กำหนด Shelf Life หรือกำหนดไม่ถูกต้อง กรุณาแก้ไขข้อมูล SKU", "danger")
                 today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                 return render_template('add_stock.html', skus=skus_data, current_date=today_str)

            batch_id = str(uuid.uuid4())
            # arrival_date คำนวณไว้แล้วจากข้างบน
            expiry_date = arrival_date + timedelta(days=shelf_life_days)

            new_batch = {
                "batch_id": batch_id,
                "sku": sku,
                "quantity": quantity,
                "location": "back_stock",
                "arrival_date": arrival_date.isoformat().replace('+00:00', 'Z'), # ใช้ arrival_date ที่ได้จากฟอร์ม
                "expiry_date": expiry_date.isoformat().replace('+00:00', 'Z')
            }

            inventory = load_inventory()
            inventory['batches'].append(new_batch)
            save_inventory(inventory)

            sku_name = skus_data[sku].get('name', sku)
            flash(f"เพิ่มสต็อก '{sku_name}' จำนวน {quantity} ชิ้น (รับวันที่: {arrival_date_str}, Batch: ...{batch_id[-6:]}) เรียบร้อยแล้ว", "success") # แสดงวันที่รับด้วย
            return redirect(url_for('index'))

        except Exception as e:
             print(f"Error creating batch for {sku}: {e}")
             flash(f"เกิดข้อผิดพลาดในการสร้าง Batch สำหรับ {sku}", "danger")
             today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
             return render_template('add_stock.html', skus=skus_data, current_date=today_str)

    else: # GET request
        # ส่งวันที่ปัจจุบันไปเป็นค่า default ให้ฟอร์ม
        today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        return render_template('add_stock.html', skus=skus_data, current_date=today_str)


@app.route('/move_to_display', methods=['GET', 'POST'], endpoint='move_to_display')
def move_to_display():
    """หน้าย้ายสต็อกจากหลังร้านไปหน้าร้าน (ใช้ระบบ Batch + FIFO)"""
    skus_data = load_skus()
    inventory = load_inventory()
    batches = inventory.get('batches', [])

    # --- สร้างข้อมูลสำหรับ Dropdown และ JS (เฉพาะ SKU ที่มีใน back_stock) ---
    back_stock_batches = [b for b in batches if b.get('location') == 'back_stock' and b.get('quantity', 0) > 0]
    available_skus_in_back = {}
    aggregated_back_stock = {}
    if back_stock_batches:
        # เรียงตามวันหมดอายุ (เก่าสุดก่อน) ถ้าวันหมดอายุเท่ากัน ให้เรียงตามวันที่รับเข้า (เก่าสุดก่อน)
        back_stock_batches.sort(key=lambda b: (b.get('expiry_date', ''), b.get('arrival_date', '')))
        
        unique_skus = sorted(list(set(b['sku'] for b in back_stock_batches)))
        for sku_code in unique_skus:
            if sku_code in skus_data:
             available_skus_in_back[sku_code] = skus_data[sku_code]
             aggregated_back_stock[sku_code] = sum(b['quantity'] for b in back_stock_batches if b['sku'] == sku_code)
        else: # <--- เพิ่มส่วนนี้
             print(f"!!! คำเตือน: SKU '{sku_code}' มีในสต็อกหลังร้าน แต่ไม่มีข้อมูลใน skus.json !!!")

    if request.method == 'POST':
        sku_to_move = request.form.get('sku')
        quantity_str = request.form.get('quantity')

        # --- ตรวจสอบ Input ---
        if not sku_to_move or not quantity_str:
            flash("กรุณาเลือก SKU และระบุจำนวน", "warning")
            return render_template('move_to_display.html', skus=available_skus_in_back, back_stock_agg=aggregated_back_stock)
        if sku_to_move not in available_skus_in_back:
             flash(f"ไม่พบ SKU '{sku_to_move}' ในสต็อกหลังร้าน", "danger")
             return render_template('move_to_display.html', skus=available_skus_in_back, back_stock_agg=aggregated_back_stock)
        try:
            requested_quantity = int(quantity_str)
            if requested_quantity <= 0: raise ValueError("Quantity must be positive")
        except ValueError:
            flash("จำนวนต้องเป็นเลขบวกเท่านั้น", "danger")
            return render_template('move_to_display.html', skus=available_skus_in_back, back_stock_agg=aggregated_back_stock)

        # --- Logic การย้าย (FIFO) ---
        quantity_left_to_move = requested_quantity
        moved_count = 0
        indices_to_remove = [] # เก็บ index ของ batch ที่จะลบ (ถ้าหมด)
        batches_to_add = [] # เก็บ display batch ใหม่ที่จะสร้าง

        # กรอง batch เฉพาะ sku ที่ต้องการ และเรียงลำดับอีกครั้ง (เผื่อมีการเปลี่ยนแปลง)
        source_batches_for_sku = sorted(
            [b for b in back_stock_batches if b.get('sku') == sku_to_move],
            key=lambda b: (b.get('expiry_date', ''), b.get('arrival_date', ''))
        )

        original_batch_indices = {b['batch_id']: i for i, b in enumerate(inventory['batches'])} # Map id กับ index เดิม

        for batch in source_batches_for_sku:
            if quantity_left_to_move <= 0: break # ย้ายครบแล้ว

            original_index = original_batch_indices.get(batch['batch_id'])
            if original_index is None: continue # ไม่ควรเกิดขึ้น

            available_in_batch = batch['quantity']
            move_from_this_batch = min(available_in_batch, quantity_left_to_move)

            if move_from_this_batch > 0:
                # ลดจำนวนใน Batch ต้นทาง (ใน list หลัก)
                inventory['batches'][original_index]['quantity'] -= move_from_this_batch
                moved_count += move_from_this_batch

                # สร้าง Batch ปลายทาง (Display)
                new_display_batch = {
                    "batch_id": str(uuid.uuid4()),
                    "sku": sku_to_move,
                    "quantity": move_from_this_batch,
                    "location": "display",
                    "arrival_date": batch['arrival_date'], # ใช้วันรับเข้าเดิม
                    "expiry_date": batch['expiry_date']   # ใช้วันหมดอายุเดิม
                }
                batches_to_add.append(new_display_batch)

                quantity_left_to_move -= move_from_this_batch

                # ทำเครื่องหมาย batch ต้นทางเพื่อลบ ถ้าหมด
                if inventory['batches'][original_index]['quantity'] == 0:
                    # ใช้ list เก็บ index แทนที่จะลบทันที เพื่อไม่ให้ index เพี้ยนระหว่าง loop
                    if original_index not in indices_to_remove:
                         indices_to_remove.append(original_index)


        # --- สรุปผลและบันทึก ---
        if moved_count < requested_quantity:
             flash(f"ไม่สามารถย้ายได้ครบตามจำนวนที่ขอ (ย้ายได้ {moved_count} จาก {requested_quantity} ชิ้น) เนื่องจากสต็อกหลังร้านไม่พอ", "warning")
        elif moved_count > 0:
             flash(f"ย้าย SKU '{sku_to_move}' จำนวน {moved_count} ชิ้น ไปยังหน้าร้านเรียบร้อยแล้ว", "success")
        else:
             flash("ไม่ได้ย้ายสินค้าใดๆ (อาจเกิดข้อผิดพลาด)", "danger") # กรณีที่ไม่ควรเกิดขึ้น

        # เพิ่ม display batch ใหม่เข้าไป
        inventory['batches'].extend(batches_to_add)

        # ลบ batch เก่าที่หมดแล้ว (เรียง index จากมากไปน้อยเพื่อลบ)
        indices_to_remove.sort(reverse=True)
        for index in indices_to_remove:
            del inventory['batches'][index]

        save_inventory(inventory)
        return redirect(url_for('index'))

    else: # GET request
        if not available_skus_in_back:
             flash("ไม่มีสินค้าในสต็อกหลังร้านให้ย้าย", "info")
             return redirect(url_for('index'))
        # ส่งข้อมูล SKU ที่มีใน back_stock และจำนวนรวมแต่ละ SKU ไปให้ template
        return render_template('move_to_display.html', skus=available_skus_in_back, back_stock_agg=aggregated_back_stock)


@app.route('/record_sale', methods=['GET', 'POST'], endpoint='record_sale')
def record_sale():
    """หน้าบันทึกการขาย (ใช้ระบบ Batch + FIFO จาก display)"""
    skus_data = load_skus()
    inventory = load_inventory()
    batches = inventory.get('batches', [])

    # --- สร้างข้อมูลสำหรับ Dropdown และ JS (เฉพาะ SKU ที่มีใน display) ---
    display_batches = [b for b in batches if b.get('location') == 'display' and b.get('quantity', 0) > 0]
    available_skus_on_display = {}
    aggregated_display_stock = {}
    if display_batches:
        # เรียงตามวันหมดอายุ (เก่าสุดก่อน), ถ้าเท่ากัน เรียงตามวันที่รับเข้า (เก่าสุดก่อน)
        display_batches.sort(key=lambda b: (b.get('expiry_date', ''), b.get('arrival_date', '')))
        
        unique_skus = sorted(list(set(b['sku'] for b in display_batches)))
        for sku_code in unique_skus:
             if sku_code in skus_data:
                 available_skus_on_display[sku_code] = skus_data[sku_code]
                 aggregated_display_stock[sku_code] = sum(b['quantity'] for b in display_batches if b['sku'] == sku_code)

    if request.method == 'POST':
        sku_to_sell = request.form.get('sku')
        quantity_str = request.form.get('quantity')

        # --- ตรวจสอบ Input ---
        if not sku_to_sell or not quantity_str:
            flash("กรุณาเลือก SKU และระบุจำนวน", "warning")
            return render_template('record_sale.html', skus=available_skus_on_display, display_stock_agg=aggregated_display_stock)
        if sku_to_sell not in available_skus_on_display:
             flash(f"ไม่พบ SKU '{sku_to_sell}' ในสต็อกหน้าร้าน", "danger")
             return render_template('record_sale.html', skus=available_skus_on_display, display_stock_agg=aggregated_display_stock)
        try:
            requested_quantity = int(quantity_str)
            if requested_quantity <= 0: raise ValueError("Quantity must be positive")
        except ValueError:
            flash("จำนวนต้องเป็นเลขบวกเท่านั้น", "danger")
            return render_template('record_sale.html', skus=available_skus_on_display, display_stock_agg=aggregated_display_stock)

        # --- Logic การขาย (FIFO) ---
        quantity_left_to_sell = requested_quantity
        sold_count = 0
        indices_to_remove = []

        # กรอง batch เฉพาะ sku ที่ต้องการ และเรียงลำดับอีกครั้ง
        source_batches_for_sku = sorted(
            [b for b in display_batches if b.get('sku') == sku_to_sell],
             key=lambda b: (b.get('expiry_date', ''), b.get('arrival_date', ''))
        )
        original_batch_indices = {b['batch_id']: i for i, b in enumerate(inventory['batches'])}

        for batch in source_batches_for_sku:
            if quantity_left_to_sell <= 0: break

            original_index = original_batch_indices.get(batch['batch_id'])
            if original_index is None: continue

            available_in_batch = batch['quantity']
            sell_from_this_batch = min(available_in_batch, quantity_left_to_sell)

            if sell_from_this_batch > 0:
                 # ลดจำนวนใน Batch (ใน list หลัก)
                 inventory['batches'][original_index]['quantity'] -= sell_from_this_batch
                 sold_count += sell_from_this_batch
                 quantity_left_to_sell -= sell_from_this_batch

                 # ทำเครื่องหมาย batch เพื่อลบ ถ้าหมด
                 if inventory['batches'][original_index]['quantity'] == 0:
                     if original_index not in indices_to_remove:
                          indices_to_remove.append(original_index)

        # --- สรุปผลและบันทึก ---
        if sold_count < requested_quantity:
             flash(f"ไม่สามารถขายได้ครบตามจำนวนที่ขอ (ขายได้ {sold_count} จาก {requested_quantity} ชิ้น) เนื่องจากสต็อกหน้าร้านไม่พอ", "warning")
             # *** สำคัญ: ต้อง rollback การเปลี่ยนแปลงจำนวนใน batches ก่อนหน้านี้ ***
             # การ rollback ซับซ้อน ควรจะเช็คให้ดีก่อนแก้ข้อมูล หรือใช้ transaction ถ้าเป็น DB
             # ในกรณี JSON แบบนี้ การทำ rollback ยาก อาจจะต้องโหลดข้อมูลใหม่แล้วทำเฉพาะส่วนที่ทำได้
             # หรือแค่ flash ข้อความเตือน แต่ข้อมูลอาจจะเพี้ยนถ้าขายบางส่วนไปแล้ว
             # --> เพื่อความง่ายใน Phase 1: ถ้าขายไม่ครบ ให้ถือว่า *ไม่เกิดการขายเลย* แล้วแจ้งเตือน
             # เราต้องปรับ logic ข้างบนใหม่: ให้คำนวณก่อนว่าจะขายได้ครบไหม ถ้าครบ ค่อยไปลดจำนวนทีหลัง
             # --> กลับไปใช้ logic เดิมที่ง่ายกว่า: เช็คยอดรวมก่อน ถ้าพอ ค่อยไปวนลดยอด
             if sold_count > 0: # ถ้ามีการลดจำนวนไปแล้ว ให้โหลดใหม่ (เป็นการ rollback แบบง่าย)
                 inventory = load_inventory() # โหลดข้อมูลเดิม ไม่บันทึกส่วนที่ลดไป
                 flash(f"ขาย SKU '{sku_to_sell}' ไม่สำเร็จ เนื่องจากสต็อกหน้าร้านไม่พอ ({aggregated_display_stock.get(sku_to_sell, 0)} ชิ้น)", "warning")
                 return render_template('record_sale.html', skus=available_skus_on_display, display_stock_agg=aggregated_display_stock)


        elif sold_count > 0:
             # ลบ batch ที่หมดแล้ว (เรียง index จากมากไปน้อย)
             indices_to_remove.sort(reverse=True)
             for index in indices_to_remove:
                 del inventory['batches'][index]
             save_inventory(inventory) # บันทึกเฉพาะกรณีขายสำเร็จ
             flash(f"บันทึกการขาย SKU '{sku_to_sell}' จำนวน {sold_count} ชิ้น เรียบร้อยแล้ว", "success")
        else:
             # กรณี requested_quantity > 0 แต่ sold_count == 0 (ไม่ควรเกิดถ้าเช็คยอดรวมก่อน)
             flash(f"ขาย SKU '{sku_to_sell}' ไม่สำเร็จ เนื่องจากสต็อกหน้าร้านไม่พอ ({aggregated_display_stock.get(sku_to_sell, 0)} ชิ้น)", "warning")
             return render_template('record_sale.html', skus=available_skus_on_display, display_stock_agg=aggregated_display_stock)


        return redirect(url_for('index'))

    else: # GET request
        if not available_skus_on_display:
            flash("ไม่มีสินค้าหน้าร้านสำหรับขาย", "info")
            return redirect(url_for('index'))
        # ส่งข้อมูล SKU ที่มีใน display และจำนวนรวมแต่ละ SKU ไปให้ template
        return render_template('record_sale.html', skus=available_skus_on_display, display_stock_agg=aggregated_display_stock)


if __name__ == '__main__':
    app.run(debug=True)