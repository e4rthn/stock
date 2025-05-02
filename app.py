import json
import os
from datetime import datetime, timedelta, timezone
import uuid
from math import floor
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
# **สำคัญ:** เปลี่ยน 'your_secret_key' เป็นค่าลับจริงๆ ของคุณเอง!
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'a_default_secret_key_change_me_plz')

# --- ค่าคงที่ ---
SKU_FILE = 'skus.json'
INVENTORY_FILE = 'inventory.json'
# รายการประเภทสินค้า (เรียงลำดับ)
ALLOWED_CATEGORIES = sorted(['หมู', 'ไก่', 'เนื้อ', 'อาหารทะเล', 'ผัก', 'ผลไม้', 'เครื่องดื่ม', 'อื่นๆ'])

# --- Context Processors (สำหรับ Template Helpers) ---
@app.context_processor
def inject_global_vars():
    """Inject global variables needed in multiple templates."""
    def format_iso_date(date_str, fmt='%Y-%m-%d %H:%M'):
        """Formats ISO date string (UTC) to a more readable local format (naive)."""
        if not date_str: return "-"
        try:
            dt_utc = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt_utc.strftime(fmt) + " UTC"
        except (ValueError, TypeError): return date_str

    def format_time_remaining(expiry_date_str):
        """Calculates and formats remaining time from UTC expiry string."""
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

    return dict(
        current_year=datetime.now(timezone.utc).year,
        format_iso_date=format_iso_date,
        format_time_remaining=format_time_remaining
    )

# --- Helper Functions: Data Loading/Saving ---
def load_data(filename):
    """โหลดข้อมูลจากไฟล์ JSON พร้อมจัดการกรณีไฟล์ไม่มี/ว่าง/เสีย"""
    default_data = {"batches": []} if filename == INVENTORY_FILE else {}
    if not os.path.exists(filename):
        return default_data
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content:
                return default_data
            return json.loads(content)
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error loading data from {filename}: {e}")
        flash(f"เกิดข้อผิดพลาดในการโหลดข้อมูลจาก {filename}, ใช้ข้อมูลเริ่มต้น", "danger")
        return default_data

def save_data(filename, data):
    """บันทึกข้อมูลลงไฟล์ JSON"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except IOError as e:
        print(f"Error saving data to {filename}: {e}")
        flash(f"เกิดข้อผิดพลาดในการบันทึกข้อมูลลง {filename}", "danger")

def load_skus():
    """โหลดข้อมูล SKU"""
    skus = load_data(SKU_FILE)
    # Basic validation: Ensure it's a dictionary
    return skus if isinstance(skus, dict) else {}

def save_skus(skus_data):
    """บันทึกข้อมูล SKU"""
    save_data(SKU_FILE, skus_data)

def load_inventory():
    """โหลดข้อมูล Inventory และตรวจสอบโครงสร้างพื้นฐาน"""
    inventory_data = load_data(INVENTORY_FILE)
    if not isinstance(inventory_data, dict) or 'batches' not in inventory_data or not isinstance(inventory_data.get('batches'), list):
        print(f"Warning: Data in {INVENTORY_FILE} has incorrect structure. Resetting.")
        flash(f"โครงสร้างข้อมูลใน {INVENTORY_FILE} ไม่ถูกต้อง, กำลังรีเซ็ต", "warning")
        inventory = {"batches": []}
        save_inventory(inventory) # Save the correct structure
    else:
        inventory = inventory_data
    return inventory

def save_inventory(inventory_data):
    """บันทึกข้อมูล Inventory"""
    save_data(INVENTORY_FILE, inventory_data)

# --- Helper Function: Update Batch Statuses ---
def update_batch_statuses(batches, skus_data):
    """อัปเดตสถานะ (location) ของแต่ละ Batch ตามวันหมดอายุและกฎ RTC."""
    now = datetime.now(timezone.utc)
    updated_batches = []
    something_changed = False

    for batch in batches:
        current_location = batch.get('location')
        expiry_str = batch.get('expiry_date')
        sku = batch.get('sku')
        qty = batch.get('quantity', 0)
        new_batch_data = batch.copy()

        if not expiry_str or not sku or sku not in skus_data or qty <= 0 or current_location == 'bad': # ไม่ต้องอัปเดตถ้า BAD แล้ว
            updated_batches.append(new_batch_data)
            continue

        try:
            expiry_dt = datetime.fromisoformat(expiry_str.replace('Z', '+00:00'))
            time_until_expiry = expiry_dt - now
            new_location = current_location

            # กฎ RTC/BAD (เรียงจากเงื่อนไขแคบสุดไปกว้างสุด)
            if time_until_expiry <= timedelta(0):
                new_location = 'bad'
            elif current_location == 'back_stock':
                 # Back stock becomes bad directly when expired, no RTC stages
                 pass # Keep as back_stock unless expired (handled above)
            elif time_until_expiry <= timedelta(hours=12, minutes=30): # RTC2 threshold
                 if current_location in ['display', 'rtc1']: new_location = 'rtc2'
            elif time_until_expiry <= timedelta(days=1, hours=1): # RTC1 threshold
                 if current_location == 'display': new_location = 'rtc1'
            # else: keep current location ('display' or 'back_stock' if not expired/RTC yet)

            if new_location != current_location:
                new_batch_data['location'] = new_location
                something_changed = True

            updated_batches.append(new_batch_data)

        except ValueError:
            print(f"Error parsing date for batch {batch.get('batch_id')}, SKU {sku}. Skipping.")
            updated_batches.append(new_batch_data)

    return updated_batches, something_changed

# --- Routes ---

@app.route('/', endpoint='index')
def index():
    """หน้าแสดงภาพรวม Inventory (แสดงตารางเดียว + Filter)"""
    inventory = load_inventory()
    skus_data = load_skus()
    batches = inventory.get('batches', [])

    # อัปเดตสถานะก่อนเสมอ
    updated_batches, changed = update_batch_statuses(batches, skus_data)
    if changed:
        print("Batch statuses updated, saving changes...")
        inventory['batches'] = updated_batches
        save_inventory(inventory)
        batches_to_process = updated_batches
    else:
        batches_to_process = batches

    # กำหนดลำดับการแสดงผล และ Config สำหรับ Template
    location_order = ['display', 'back_stock', 'rtc1', 'rtc2', 'bad']
    location_sort_key = {loc: i for i, loc in enumerate(location_order)}
    location_configs = {
        'display': {'title': 'หน้าร้าน', 'border_status_class': 'status-display', 'icon': 'bi-shop'},
        'back_stock': {'title': 'หลังร้าน', 'border_status_class': 'status-back-stock', 'icon': 'bi-boxes'},
        'rtc1': {'title': 'RTC-1', 'border_status_class': 'status-rtc1', 'icon': 'bi-alarm'},
        'rtc2': {'title': 'RTC-2', 'border_status_class': 'status-rtc2', 'icon': 'bi-alarm-fill'},
        'bad': {'title': 'หมดอายุ', 'border_status_class': 'status-bad', 'icon': 'bi-x-octagon-fill'}
    }

    # กรอง Batch ที่มีจำนวน > 0
    valid_batches = [b for b in batches_to_process if b.get('quantity', 0) > 0]

    # เรียงลำดับ Batch
    valid_batches.sort(key=lambda b: (
        location_sort_key.get(b.get('location'), 99),
        b.get('sku', ''),
        b.get('expiry_date', '')
    ))

    return render_template('index.html',
                           inventory_batches=valid_batches,
                           skus_data=skus_data,
                           location_configs=location_configs,
                           allowed_categories=ALLOWED_CATEGORIES
                           )

# --- SKU Management Routes ---
@app.route('/skus', endpoint='list_skus')
def list_skus():
    skus_data = load_skus()
    return render_template('list_skus.html', skus=skus_data, categories=ALLOWED_CATEGORIES)

@app.route('/add_sku', methods=['GET', 'POST'], endpoint='add_sku')
def add_sku():
    if request.method == 'POST':
        sku_code = request.form.get('sku', '').strip().upper() # Convert SKU to uppercase
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
            skus_data[sku_code] = {'name': name, 'category': category, 'shelf_life_days': shelf_life_days}
            save_skus(skus_data)
            flash(f"เพิ่ม SKU '{name}' ({sku_code}) เรียบร้อยแล้ว", "success")
            return redirect(url_for('list_skus'))
    else:
        return render_template('add_sku.html', categories=ALLOWED_CATEGORIES)

@app.route('/edit_sku/<sku>', methods=['GET', 'POST'], endpoint='edit_sku')
def edit_sku(sku):
    skus_data = load_skus()
    # Ensure comparison is case-insensitive if needed, but saved SKUs are uppercase
    if sku not in skus_data:
        flash(f"ไม่พบ SKU Code: {sku}", "danger")
        return redirect(url_for('list_skus'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()
        shelf_life_str = request.form.get('shelf_life_days', '').strip()

        # Re-populate data for template if validation fails
        sku_data_for_template = skus_data[sku].copy()
        sku_data_for_template['name'] = name
        sku_data_for_template['category'] = category
        sku_data_for_template['shelf_life_days'] = shelf_life_str # Keep as string for form repopulation

        if not name or not category or not shelf_life_str:
            flash("กรุณากรอกข้อมูลให้ครบทุกช่อง (Name, Category, Shelf Life)", "warning")
            return render_template('edit_sku.html', categories=ALLOWED_CATEGORIES, sku_code=sku, sku_data=sku_data_for_template)
        if category not in ALLOWED_CATEGORIES:
             flash("ประเภทสินค้าไม่ถูกต้อง", "danger")
             return render_template('edit_sku.html', categories=ALLOWED_CATEGORIES, sku_code=sku, sku_data=sku_data_for_template)
        try:
            shelf_life_days = int(shelf_life_str)
            if shelf_life_days <= 0: raise ValueError("Shelf life must be positive")
        except ValueError:
            flash("อายุสินค้า (Shelf Life) ต้องเป็นจำนวนเต็มบวก (วัน)", "danger")
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
    skus_data = load_skus()
    inventory = load_inventory()
    sku_in_inventory = any(b.get('sku') == sku and b.get('quantity', 0) > 0 for b in inventory.get('batches', []))

    if sku_in_inventory:
        flash(f"ไม่สามารถลบ SKU '{sku}' ได้ เนื่องจากยังมีสต็อกสินค้าคงเหลืออยู่ในระบบ", "danger")
        return redirect(url_for('list_skus'))

    if sku in skus_data:
        deleted_name = skus_data.pop(sku).get('name', sku) # Use pop to remove and get value
        save_skus(skus_data)
        flash(f"ลบ SKU '{deleted_name}' ({sku}) เรียบร้อยแล้ว", "success")
    else:
        flash(f"ไม่พบ SKU Code: {sku} ที่จะลบ", "warning")
    return redirect(url_for('list_skus'))

# --- Inventory Management Routes ---
@app.route('/add_stock', methods=['GET', 'POST'], endpoint='add_stock')
def add_stock():
    skus_data = load_skus()
    if not skus_data:
         flash("ยังไม่มีข้อมูล SKU กรุณาเพิ่ม SKU ก่อน", "warning")
         return redirect(url_for('add_sku'))

    if request.method == 'POST':
        sku = request.form.get('sku')
        quantity_str = request.form.get('quantity')
        arrival_date_str = request.form.get('arrival_date')

        # --- Prepare data for re-rendering form on error ---
        today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        render_context = {'skus': skus_data, 'current_date': today_str}

        if not sku or not quantity_str or not arrival_date_str:
            flash("กรุณากรอกข้อมูลให้ครบทุกช่อง (SKU, Arrival Date, Quantity)", "warning")
            return render_template('add_stock.html', **render_context)
        if sku not in skus_data:
             flash(f"ไม่พบ SKU Code ในระบบ: {sku}", "danger")
             return render_template('add_stock.html', **render_context)
        try:
            quantity = int(quantity_str)
            if quantity <= 0: raise ValueError("Quantity must be positive")
        except ValueError:
            flash("จำนวนต้องเป็นเลขบวกเท่านั้น", "danger")
            return render_template('add_stock.html', **render_context)
        try:
             arrival_date_part = datetime.strptime(arrival_date_str, '%Y-%m-%d').date()
             now_time_part = datetime.now(timezone.utc).time()
             arrival_date = datetime.combine(arrival_date_part, now_time_part, tzinfo=timezone.utc)
             if arrival_date > datetime.now(timezone.utc) + timedelta(seconds=1): # Add buffer for clock skew
                 flash("วันที่รับสินค้าต้องไม่ใช่วันในอนาคต", "warning")
                 return render_template('add_stock.html', **render_context)
        except ValueError:
             flash("รูปแบบวันที่รับสินค้าไม่ถูกต้อง (ต้องเป็น YYYY-MM-DD)", "danger")
             return render_template('add_stock.html', **render_context)

        # --- Create Batch ---
        try:
            shelf_life_days = int(skus_data[sku].get('shelf_life_days', 0))
            if shelf_life_days <= 0:
                 flash(f"SKU '{sku}' ไม่ได้กำหนด Shelf Life หรือกำหนดไม่ถูกต้อง", "danger")
                 return render_template('add_stock.html', **render_context)

            batch_id = str(uuid.uuid4())
            expiry_date = arrival_date + timedelta(days=shelf_life_days)
            new_batch = {
                "batch_id": batch_id, "sku": sku, "quantity": quantity,
                "location": "back_stock",
                "arrival_date": arrival_date.isoformat().replace('+00:00', 'Z'),
                "expiry_date": expiry_date.isoformat().replace('+00:00', 'Z')
            }
            inventory = load_inventory()
            inventory['batches'].append(new_batch)
            save_inventory(inventory)
            sku_name = skus_data[sku].get('name', sku)
            flash(f"เพิ่มสต็อก '{sku_name}' จำนวน {quantity} ชิ้น (รับวันที่: {arrival_date_str}, Batch: ...{batch_id[-6:]}) เรียบร้อยแล้ว", "success")
            return redirect(url_for('index'))
        except Exception as e:
             print(f"Error creating batch for {sku}: {e}")
             flash(f"เกิดข้อผิดพลาดในการสร้าง Batch สำหรับ {sku}", "danger")
             return render_template('add_stock.html', **render_context)
    else:
        today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        return render_template('add_stock.html', skus=skus_data, current_date=today_str)

@app.route('/move_to_display', methods=['GET', 'POST'], endpoint='move_to_display')
def move_to_display():
    skus_data = load_skus()
    inventory = load_inventory()
    batches = inventory.get('batches', [])

    # Get available SKUs and quantities in back stock
    back_stock_batches = [b for b in batches if b.get('location') == 'back_stock' and b.get('quantity', 0) > 0]
    available_skus_in_back = {}
    aggregated_back_stock = {}
    if back_stock_batches:
        back_stock_batches.sort(key=lambda b: (b.get('expiry_date', ''), b.get('arrival_date', '')))
        unique_skus = sorted(list(set(b['sku'] for b in back_stock_batches)))
        for sku_code in unique_skus:
            if sku_code in skus_data:
                 available_skus_in_back[sku_code] = skus_data[sku_code]
                 aggregated_back_stock[sku_code] = sum(b['quantity'] for b in back_stock_batches if b['sku'] == sku_code)
            else: print(f"!!! คำเตือน: SKU '{sku_code}' มีในสต็อกหลังร้าน แต่ไม่มีข้อมูลใน skus.json !!!")

    render_context = {'skus': available_skus_in_back, 'back_stock_agg': aggregated_back_stock}

    if request.method == 'POST':
        sku_to_move = request.form.get('sku')
        quantity_str = request.form.get('quantity')

        if not sku_to_move or not quantity_str:
            flash("กรุณาเลือก SKU และระบุจำนวน", "warning")
            return render_template('move_to_display.html', **render_context)
        if sku_to_move not in available_skus_in_back:
             flash(f"ไม่พบ SKU '{sku_to_move}' ในสต็อกหลังร้าน", "danger")
             return render_template('move_to_display.html', **render_context)
        try:
            requested_quantity = int(quantity_str)
            if requested_quantity <= 0: raise ValueError("Quantity must be positive")
            # Check against aggregated total first
            if requested_quantity > aggregated_back_stock.get(sku_to_move, 0):
                flash(f"จำนวนที่ต้องการย้าย ({requested_quantity}) มากกว่าจำนวนที่มีในสต็อกหลังร้าน ({aggregated_back_stock.get(sku_to_move, 0)})", "warning")
                return render_template('move_to_display.html', **render_context)
        except ValueError:
            flash("จำนวนต้องเป็นเลขบวกเท่านั้น", "danger")
            return render_template('move_to_display.html', **render_context)

        # --- FIFO Move Logic ---
        quantity_left_to_move = requested_quantity
        moved_count = 0
        indices_to_remove = []
        batches_to_add = []
        source_batches_for_sku = sorted(
            [b for b in back_stock_batches if b.get('sku') == sku_to_move],
            key=lambda b: (b.get('expiry_date', ''), b.get('arrival_date', ''))
        )
        original_batch_indices = {b['batch_id']: i for i, b in enumerate(inventory['batches'])}

        for batch in source_batches_for_sku:
            if quantity_left_to_move <= 0: break
            original_index = original_batch_indices.get(batch['batch_id'])
            if original_index is None: continue

            available_in_batch = inventory['batches'][original_index]['quantity'] # Get current qty from main list
            move_from_this_batch = min(available_in_batch, quantity_left_to_move)

            if move_from_this_batch > 0:
                inventory['batches'][original_index]['quantity'] -= move_from_this_batch
                moved_count += move_from_this_batch
                new_display_batch = {
                    "batch_id": str(uuid.uuid4()), "sku": sku_to_move,
                    "quantity": move_from_this_batch, "location": "display",
                    "arrival_date": batch['arrival_date'], "expiry_date": batch['expiry_date']
                }
                batches_to_add.append(new_display_batch)
                quantity_left_to_move -= move_from_this_batch
                if inventory['batches'][original_index]['quantity'] == 0:
                    if original_index not in indices_to_remove:
                         indices_to_remove.append(original_index)

        if moved_count > 0:
             inventory['batches'].extend(batches_to_add)
             indices_to_remove.sort(reverse=True)
             for index in indices_to_remove:
                 del inventory['batches'][index]
             save_inventory(inventory)
             flash(f"ย้าย SKU '{sku_to_move}' จำนวน {moved_count} ชิ้น ไปยังหน้าร้านเรียบร้อยแล้ว", "success")
             if quantity_left_to_move > 0 : # Should not happen if pre-check works
                  flash(f"ไม่สามารถย้ายได้ครบตามจำนวนที่ขอ (ขาดไป {quantity_left_to_move} ชิ้น)", "warning")
        else:
             flash("ไม่ได้ย้ายสินค้า (อาจเกิดข้อผิดพลาด หรือจำนวนที่ต้องการย้ายไม่ถูกต้อง)", "danger")

        return redirect(url_for('index'))

    else: # GET request
        if not available_skus_in_back:
             flash("ไม่มีสินค้าในสต็อกหลังร้านให้ย้าย", "info")
             return redirect(url_for('index'))
        return render_template('move_to_display.html', **render_context)


@app.route('/record_sale', methods=['GET', 'POST'], endpoint='record_sale')
def record_sale():
    skus_data = load_skus()
    inventory = load_inventory()
    batches = inventory.get('batches', [])

    # --- Get available SKUs and quantities on display (including RTC) ---
    # We sell from RTC2 -> RTC1 -> Display
    sellable_locations = ['rtc2', 'rtc1', 'display']
    sellable_batches = [b for b in batches if b.get('location') in sellable_locations and b.get('quantity', 0) > 0]
    available_skus_to_sell = {}
    aggregated_sellable_stock = {}
    if sellable_batches:
         # Sort by location priority, then expiry, then arrival
         location_sell_prio = {loc: i for i, loc in enumerate(sellable_locations)}
         sellable_batches.sort(key=lambda b: (
             location_sell_prio.get(b.get('location'), 99),
             b.get('expiry_date', ''),
             b.get('arrival_date', '')
         ))
         unique_skus = sorted(list(set(b['sku'] for b in sellable_batches)))
         for sku_code in unique_skus:
             if sku_code in skus_data:
                 available_skus_to_sell[sku_code] = skus_data[sku_code]
                 aggregated_sellable_stock[sku_code] = sum(b['quantity'] for b in sellable_batches if b['sku'] == sku_code)
             else: print(f"!!! คำเตือน: SKU '{sku_code}' มีในสต็อกพร้อมขาย แต่ไม่มีข้อมูลใน skus.json !!!")

    render_context = {'skus': available_skus_to_sell, 'display_stock_agg': aggregated_sellable_stock} # Reuse template variable name

    if request.method == 'POST':
        sku_to_sell = request.form.get('sku')
        quantity_str = request.form.get('quantity')

        if not sku_to_sell or not quantity_str:
            flash("กรุณาเลือก SKU และระบุจำนวน", "warning")
            return render_template('record_sale.html', **render_context)
        if sku_to_sell not in available_skus_to_sell:
             flash(f"ไม่พบ SKU '{sku_to_sell}' ในสต็อกพร้อมขาย (หน้าร้าน/RTC)", "danger")
             return render_template('record_sale.html', **render_context)
        try:
            requested_quantity = int(quantity_str)
            if requested_quantity <= 0: raise ValueError("Quantity must be positive")
            # Check against aggregated total first
            total_available = aggregated_sellable_stock.get(sku_to_sell, 0)
            if requested_quantity > total_available:
                flash(f"จำนวนที่ต้องการขาย ({requested_quantity}) มากกว่าจำนวนที่มีในสต็อกพร้อมขาย ({total_available})", "warning")
                return render_template('record_sale.html', **render_context)
        except ValueError:
            flash("จำนวนต้องเป็นเลขบวกเท่านั้น", "danger")
            return render_template('record_sale.html', **render_context)

        # --- FIFO Sale Logic (RTC2 -> RTC1 -> Display) ---
        quantity_left_to_sell = requested_quantity
        sold_count = 0
        indices_to_remove = []
        # Use the already sorted sellable_batches list, filtered for the specific SKU
        source_batches_for_sku = [b for b in sellable_batches if b.get('sku') == sku_to_sell]
        original_batch_indices = {b['batch_id']: i for i, b in enumerate(inventory['batches'])}

        for batch in source_batches_for_sku:
            if quantity_left_to_sell <= 0: break
            original_index = original_batch_indices.get(batch['batch_id'])
            if original_index is None: continue # Should not happen

            available_in_batch = inventory['batches'][original_index]['quantity']
            sell_from_this_batch = min(available_in_batch, quantity_left_to_sell)

            if sell_from_this_batch > 0:
                 inventory['batches'][original_index]['quantity'] -= sell_from_this_batch
                 sold_count += sell_from_this_batch
                 quantity_left_to_sell -= sell_from_this_batch
                 if inventory['batches'][original_index]['quantity'] == 0:
                     if original_index not in indices_to_remove:
                          indices_to_remove.append(original_index)

        # --- Save and Report ---
        # Since we pre-checked the total, sold_count should equal requested_quantity
        if sold_count == requested_quantity and sold_count > 0:
             indices_to_remove.sort(reverse=True)
             for index in indices_to_remove:
                 del inventory['batches'][index]
             save_inventory(inventory)
             flash(f"บันทึกการขาย SKU '{sku_to_sell}' จำนวน {sold_count} ชิ้น เรียบร้อยแล้ว", "success")
        elif requested_quantity > 0: # Should not happen if pre-check worked
             flash(f"ขาย SKU '{sku_to_sell}' ไม่สำเร็จ (ขายได้ {sold_count}/{requested_quantity}) - เกิดข้อผิดพลาด", "danger")
             # No rollback needed as pre-check failed or logic error occurred
        else: # requested_quantity was 0 or less
            flash("จำนวนที่ขายต้องมากกว่า 0", "warning")


        return redirect(url_for('index'))

    else: # GET request
        if not available_skus_to_sell:
            flash("ไม่มีสินค้าหน้าร้าน/RTC สำหรับขาย", "info")
            return redirect(url_for('index'))
        return render_template('record_sale.html', **render_context)

# --- Main execution ---
if __name__ == '__main__':
    app.run(debug=True, port=5001) # ใช้ port อื่นเผื่อ port 5000 ไม่ว่าง