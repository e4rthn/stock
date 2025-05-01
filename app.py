import json
import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
import os # เพิ่มเข้ามาเพื่อสร้าง Secret Key

# --- สร้าง Flask App ---
app = Flask(__name__)
# ตั้งค่า secret key แบบสุ่ม เพื่อความปลอดภัยของ flash message
app.secret_key = os.urandom(24)
SKU_FILE = 'skus.json' # ชื่อไฟล์ที่จะใช้เก็บข้อมูล SKU
INVENTORY_FILE = 'inventory.json' # ชื่อไฟล์สำหรับเก็บข้อมูลสต็อก

# --- นิยามฟังก์ชัน load/save ก่อน ---
def load_skus():
    """โหลดข้อมูล SKU จากไฟล์ JSON"""
    try:
        # พยายามเปิดและอ่านไฟล์ SKU_FILE
        with open(SKU_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # ถ้าไฟล์ไม่มี หรือไฟล์ไม่ใช่ JSON ที่ถูกต้อง ให้คืนค่าเริ่มต้น (กัน Error)
        print(f"คำเตือน: ไม่พบไฟล์ {SKU_FILE} หรือไฟล์เสียหาย กำลังใช้ข้อมูล SKU เริ่มต้น")
        # คืนค่าข้อมูลเริ่มต้นที่เราเคย Hardcode ไว้
        return {
            "FP001": {"name": "กล้วยหอม", "shelf_life": 5},
            "FP002": {"name": "มะม่วงน้ำดอกไม้", "shelf_life": 7},
            "VG001": {"name": "ผักกาดขาว", "shelf_life": 4}
            }        
def save_skus(skus_data):
    """บันทึกข้อมูล SKU ลงไฟล์ JSON"""
    try:
        # เปิดไฟล์ SKU_FILE เพื่อเขียนทับ ('w')
        with open(SKU_FILE, 'w', encoding='utf-8') as f:
            # บันทึก dictionary ลงไฟล์แบบ JSON โดยให้สวยงาม (indent=4)
            json.dump(skus_data, f, ensure_ascii=False, indent=4)
        return True # คืนค่า True ถ้าบันทึกสำเร็จ
    except IOError as e:
        print(f"เกิดข้อผิดพลาดในการบันทึกไฟล์ {SKU_FILE}: {e}")
        flash(f"เกิดข้อผิดพลาดในการบันทึกข้อมูล SKU!", "error")
        return False # คืนค่า False ถ้ามีปัญหาในการบันทึก
# --- ส่วน Logic เดิม ---
skus_info = load_skus() # โหลดข้อมูล SKU จากไฟล์ หรือใช้ค่าเริ่มต้น

def load_inventory():
    """โหลดข้อมูล Inventory จากไฟล์ JSON และแปลงวันที่กลับ"""
    try:
        with open(INVENTORY_FILE, 'r', encoding='utf-8') as f:
            inventory_data = json.load(f)
            # แปลง date string กลับเป็น date object
            for batch in inventory_data:
                if 'receive_date' in batch and isinstance(batch['receive_date'], str):
                    batch['receive_date'] = datetime.datetime.strptime(batch['receive_date'], '%Y-%m-%d').date()
                if 'expiry_date' in batch and isinstance(batch['expiry_date'], str):
                    batch['expiry_date'] = datetime.datetime.strptime(batch['expiry_date'], '%Y-%m-%d').date()
            return inventory_data
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"คำเตือน: ไม่พบไฟล์ {INVENTORY_FILE} หรือไฟล์เสียหาย กำลังเริ่มด้วย Inventory ว่าง")
        return [] # ถ้าไม่มีไฟล์หรือมีปัญหา คืนค่า List ว่าง
    
def save_inventory(inventory_data):
    """แปลงวันที่เป็น string แล้วบันทึก Inventory ลงไฟล์ JSON"""
    try:
        # สร้าง List ใหม่เพื่อเก็บข้อมูลที่จะแปลงวันที่
        data_to_save = []
        for batch in inventory_data:
            batch_copy = batch.copy() # ทำสำเนาเพื่อไม่แก้ original
            if 'receive_date' in batch_copy and isinstance(batch_copy['receive_date'], datetime.date):
                batch_copy['receive_date'] = batch_copy['receive_date'].isoformat() # แปลงเป็น YYYY-MM-DD
            if 'expiry_date' in batch_copy and isinstance(batch_copy['expiry_date'], datetime.date):
                batch_copy['expiry_date'] = batch_copy['expiry_date'].isoformat() # แปลงเป็น YYYY-MM-DD
            data_to_save.append(batch_copy)

        # บันทึก List ที่แปลงวันที่แล้ว
        with open(INVENTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=4)
        return True
    except (IOError, TypeError) as e: # ดัก TypeError เผื่อการแปลงผิดพลาด
        print(f"เกิดข้อผิดพลาดในการบันทึกไฟล์ {INVENTORY_FILE}: {e}")
        flash(f"เกิดข้อผิดพลาดในการบันทึกข้อมูล Inventory!", "error")
        return False    
    
inventory = load_inventory() # โหลดข้อมูล Inventory จากไฟล์ (ถ้ามี)

def add_stock(sku_code, receive_date_str, quantity_kg):
    if sku_code not in skus_info:
        flash(f"ข้อผิดพลาด: ไม่พบข้อมูล SKU '{sku_code}'", "error")
        return False
    try:
        receive_date = datetime.datetime.strptime(receive_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash(f"ข้อผิดพลาด: รูปแบบวันที่รับเข้าไม่ถูกต้อง '{receive_date_str}' (ต้องเป็น YYYY-MM-DD)", "error")
        return False
    try:
        qty = float(quantity_kg)
        if qty <= 0:
             flash("ข้อผิดพลาด: ปริมาณรับเข้าต้องมากกว่า 0", "error")
             return False
    except ValueError:
         flash("ข้อผิดพลาด: ปริมาณรับเข้าไม่ถูกต้อง", "error")
         return False

    sku_details = skus_info[sku_code]
    shelf_life = sku_details["shelf_life"]
    expiry_date = receive_date + datetime.timedelta(days=shelf_life)
    new_batch = {
        "batch_id": f"{sku_code}-{receive_date_str}-{len(inventory)+1}",
        "sku_code": sku_code, "sku_name": sku_details["name"],
        "receive_date": receive_date, "expiry_date": expiry_date,
        "initial_qty_kg": qty, "current_qty_kg": qty
    }
    inventory.append(new_batch)
    inventory.sort(key=lambda batch: batch["receive_date"])
    save_inventory(inventory) # บันทึก inventory ล่าสุดลงไฟล์
    flash(f"เพิ่มสต็อกสำเร็จ: {qty:.2f} กก. {sku_details['name']}, หมดอายุ {expiry_date.strftime('%Y-%m-%d')}", "success")
    save_inventory(inventory) # บันทึก inventory ล่าสุดลงไฟล์
    # ---------------------------------------
    return True

def record_sale(sku_code, quantity_sold_kg):
    try:
        qty_sold = float(quantity_sold_kg)
        if qty_sold <= 0:
            flash("ข้อผิดพลาด: ปริมาณขายต้องมากกว่า 0", "error")
            return False
    except ValueError:
        flash("ข้อผิดพลาด: ปริมาณขายไม่ถูกต้อง", "error")
        return False

    relevant_batches = sorted(
        [b for b in inventory if b["sku_code"] == sku_code and b["current_qty_kg"] > 0],
        key=lambda batch: batch["receive_date"]
    )
    if not relevant_batches:
        flash(f"แจ้งเตือน: ไม่พบสต็อก SKU '{sku_code}' ให้ขาย", "warning")
        return False

    remaining_to_sell = qty_sold
    sold_summary = []
    total_sold_actually = 0
    for batch in relevant_batches:
        if remaining_to_sell <= 0: break
        sell_from_this = min(batch["current_qty_kg"], remaining_to_sell)
        batch["current_qty_kg"] -= sell_from_this
        remaining_to_sell -= sell_from_this
        total_sold_actually += sell_from_this
        sold_summary.append(f"ล็อต {batch['batch_id']}: {sell_from_this:.2f} กก.")

    flash(f"บันทึกการขาย {total_sold_actually:.2f} กก. SKU '{sku_code}' จาก: {', '.join(sold_summary)}", "success")
    if remaining_to_sell > 0:
        flash(f"คำเตือน: สินค้า SKU '{sku_code}' ไม่พอขาย ขาดอีก {remaining_to_sell:.2f} กก.", "warning")
    save_inventory(inventory) # บันทึก inventory ล่าสุดลงไฟล์
    return True

# --- ฟังก์ชันคำนวณการแจ้งเตือน (เวอร์ชันรวม) ---
def get_alerts(expiry_days_list=[3, 1], in_stock_days_list=[3]):
    """คำนวณและจัดรูปแบบการแจ้งเตือนทั้งแบบใกล้หมดอายุ และแบบอยู่ในสต็อกครบกำหนด"""
    today = datetime.date.today()
    # ใช้ global inventory ที่โหลด/อัปเดตล่าสุด
    global inventory
    alerts = {'expiry': {}, 'in_stock': {}} # แยกประเภทการแจ้งเตือน

    # เตรียม list สำหรับเก็บผลแต่ละวัน
    for days in expiry_days_list:
        alerts['expiry'][days] = []
    alerts['expiry'][0] = [] # สำหรับหมดอายุวันนี้/หมดอายุแล้ว

    for days in in_stock_days_list:
        alerts['in_stock'][days] = []

    # ใช้เฉพาะ inventory ที่มีของเหลือ
    active_inventory = [batch for batch in inventory if batch.get("current_qty_kg", 0) > 0]

    for batch in active_inventory:
        # ตรวจสอบว่ามีข้อมูลวันที่ครบถ้วนหรือไม่
        if not isinstance(batch.get('expiry_date'), datetime.date) or \
           not isinstance(batch.get('receive_date'), datetime.date):
            print(f"คำเตือน: ข้อมูลวันที่ใน batch_id '{batch.get('batch_id')}' ไม่ถูกต้อง ข้ามการคำนวณแจ้งเตือน")
            continue # ข้ามไป batch ถัดไปถ้าข้อมูลวันที่ผิดพลาด

        # --- ตรวจสอบวันหมดอายุ ---
        days_to_expiry = (batch["expiry_date"] - today).days
        expiry_alert_added = False
        for days_target in expiry_days_list:
            if days_to_expiry == days_target:
                alerts['expiry'][days_target].append(batch)
                expiry_alert_added = True
                break
        # เงื่อนไขสำหรับหมดอายุแล้ว (<=0)
        if not expiry_alert_added and days_to_expiry <= 0:
             # เช็คว่ายังไม่ได้เพิ่ม batch เดิมเข้าไปในกลุ่ม 0 วันแล้ว
             if not any(existing['batch_id'] == batch.get('batch_id') for existing in alerts['expiry'][0]):
                 alerts['expiry'][0].append(batch)

        # --- ตรวจสอบจำนวนวันที่อยู่ในสต็อก ---
        days_in_stock = (today - batch['receive_date']).days
        for days_target in in_stock_days_list:
            if days_in_stock == days_target:
                # เช็คว่ายังไม่ได้เพิ่ม batch เดิมเข้าไปในการแจ้งเตือน in_stock ประเภทเดียวกัน
                if not any(existing['batch_id'] == batch.get('batch_id') for existing in alerts['in_stock'][days_target]):
                     alerts['in_stock'][days_target].append(batch)
                # ไม่ต้อง break เพราะอาจเข้าหลายเงื่อนไข (เช่น ครบ 3 วัน และครบ 7 วัน ถ้ากำหนดไว้)

    # --- จัดรูปแบบข้อมูล alerts เพื่อส่งไปแสดงผล ---
    formatted_alerts = {'expiry': {}, 'in_stock': {}}
    global skus_info # ต้องใช้ skus_info สำหรับดึงชื่อ

    # จัดรูปแบบ Expiry Alerts
    expiry_alert_order = sorted([days for days in alerts['expiry'] if alerts['expiry'][days]], reverse=True)
    if 0 in alerts['expiry'] and alerts['expiry'][0]:
        if 0 not in expiry_alert_order: expiry_alert_order.append(0)

    for days in expiry_alert_order:
        label = f"จะหมดอายุใน {days} วัน" if days > 0 else "หมดอายุวันนี้ / หมดอายุแล้ว"
        grouped_batches = {}
        # เรียงตาม SKU -> วันหมดอายุ
        for batch in sorted(alerts['expiry'][days], key=lambda b: (b.get('sku_code', ''), b.get('expiry_date', datetime.date.min))):
             sku = batch.get("sku_code")
             if sku: # ตรวจสอบว่ามี sku code
                 sku_name = skus_info.get(sku, {}).get('name', 'Unknown SKU') # ดึงชื่อจาก skus_info
                 if sku not in grouped_batches: grouped_batches[sku] = {'name': sku_name, 'batches': []}
                 grouped_batches[sku]['batches'].append(batch)
        if grouped_batches: # เพิ่ม label เฉพาะเมื่อมีข้อมูลจริงๆ
            formatted_alerts['expiry'][label] = grouped_batches

    # จัดรูปแบบ In-Stock Duration Alerts
    in_stock_alert_order = sorted([days for days in alerts['in_stock'] if alerts['in_stock'][days]])
    for days in in_stock_alert_order:
        label = f"อยู่ในสต็อกครบ {days} วัน"
        grouped_batches = {}
         # เรียงตาม SKU -> วันที่รับเข้า
        for batch in sorted(alerts['in_stock'][days], key=lambda b: (b.get('sku_code', ''), b.get('receive_date', datetime.date.min))):
             sku = batch.get("sku_code")
             if sku:
                 sku_name = skus_info.get(sku, {}).get('name', 'Unknown SKU')
                 if sku not in grouped_batches: grouped_batches[sku] = {'name': sku_name, 'batches': []}
                 grouped_batches[sku]['batches'].append(batch)
        if grouped_batches:
             formatted_alerts['in_stock'][label] = grouped_batches

    return formatted_alerts, today # คืนค่า dict ที่มีทั้ง expiry และ in_stock

# โหลดข้อมูล SKU จากไฟล์ JSON (หรือใช้ข้อมูลเริ่มต้นถ้าไม่พบไฟล์)
@app.route('/')
def index():
    current_stock = sorted([b for b in inventory if b["current_qty_kg"] > 0], key=lambda b: b['expiry_date'])
    all_alerts_data, today_date = get_alerts(expiry_days_list=[3, 1], in_stock_days_list=[3])
    return render_template('index.html', inventory=current_stock,
                       alerts_data=all_alerts_data, # <--- แก้ไขตรงนี้
                       today_date=today_date, skus=skus_info)

@app.route('/add', methods=['GET', 'POST'])
def add_stock_route():
    if request.method == 'POST':
        add_stock(request.form.get('sku_code'), request.form.get('receive_date'), request.form.get('quantity_kg'))
        return redirect(url_for('index'))
    return render_template('add_stock.html', skus=skus_info)

@app.route('/sell', methods=['GET', 'POST'])
def record_sale_route():
    if request.method == 'POST':
        record_sale(request.form.get('sku_code'), request.form.get('quantity_kg'))
        return redirect(url_for('index'))
    available_skus = sorted(list(set(b['sku_code'] for b in inventory if b['current_qty_kg'] > 0)))
    sku_choices = {sku: skus_info.get(sku, {'name': 'Unknown'})['name'] for sku in available_skus}
    return render_template('record_sale.html', skus=sku_choices)

# --- เพิ่ม Routes สำหรับจัดการ SKU ---

@app.route('/skus')
def manage_skus():
    """แสดงหน้ารายการ SKU ทั้งหมด"""
    # ใช้ skus_info ที่โหลดมาตอนเริ่มแอป หรือโหลดใหม่ก็ได้ (ถ้าต้องการความสด)
    # current_skus = load_skus() # ตัวเลือกโหลดใหม่ทุกครั้ง
    current_skus = skus_info # ใช้ตัวแปร global ที่อัปเดตใน memory
    return render_template('list_skus.html', skus=current_skus)

@app.route('/skus/add', methods=['GET', 'POST'])
def add_sku_route():
    """จัดการหน้าเพิ่ม SKU ใหม่"""
    if request.method == 'POST':
        sku_code = request.form.get('sku_code', '').strip().upper() # รับค่า, ตัดช่องว่าง, แปลงเป็นตัวใหญ่
        sku_name = request.form.get('sku_name', '').strip()
        shelf_life_str = request.form.get('shelf_life', '').strip()

        # --- การตรวจสอบข้อมูล (Validation) ---
        if not sku_code or not sku_name or not shelf_life_str:
            flash("กรุณากรอกข้อมูลให้ครบทุกช่อง", "error")
            return render_template('add_sku.html') # กลับไปหน้าฟอร์ม

        if sku_code in skus_info:
            flash(f"รหัส SKU '{sku_code}' นี้มีอยู่แล้วในระบบ", "error")
            # ส่งข้อมูลที่กรอกกลับไปแสดงในฟอร์ม
            return render_template('add_sku.html', sku_code=sku_code, sku_name=sku_name, shelf_life=shelf_life_str)

        try:
            shelf_life = int(shelf_life_str)
            if shelf_life <= 0:
                raise ValueError("Shelf life must be positive")
        except ValueError:
            flash("อายุสินค้า (Shelf Life) ต้องเป็นตัวเลขจำนวนเต็มบวกเท่านั้น", "error")
            return render_template('add_sku.html', sku_code=sku_code, sku_name=sku_name, shelf_life=shelf_life_str)
        # --- สิ้นสุดการตรวจสอบ ---

        # ถ้าข้อมูลถูกต้อง
        skus_info[sku_code] = {"name": sku_name, "shelf_life": shelf_life} # เพิ่ม/อัปเดตใน Dict
        if save_skus(skus_info): # บันทึกลงไฟล์
             flash(f"เพิ่ม SKU '{sku_code}' ({sku_name}) สำเร็จ!", "success")
        # else: save_skus จะ flash error เอง

        return redirect(url_for('manage_skus')) # กลับไปหน้ารายการ SKU

    else: # ถ้าเป็น GET request
        return render_template('add_sku.html')

@app.route('/skus/edit/<sku_code>', methods=['GET', 'POST'])
def edit_sku_route(sku_code):
    """จัดการหน้าแก้ไข SKU"""
    # ตรวจสอบก่อนว่า SKU ที่จะแก้ไขมีอยู่จริงไหม
    if sku_code not in skus_info:
        flash(f"ไม่พบ SKU '{sku_code}' ที่ต้องการแก้ไข", "error")
        return redirect(url_for('manage_skus'))

    if request.method == 'POST':
        # รับข้อมูลใหม่จากฟอร์ม
        sku_name = request.form.get('sku_name', '').strip()
        shelf_life_str = request.form.get('shelf_life', '').strip()

        # --- การตรวจสอบข้อมูล (Validation) ---
        if not sku_name or not shelf_life_str:
            flash("กรุณากรอกข้อมูลให้ครบทุกช่อง", "error")
            # ส่งข้อมูล *ปัจจุบัน* กลับไปแสดงในฟอร์มแก้ไข
            return render_template('edit_sku.html', sku_code=sku_code, sku_data=skus_info[sku_code])

        try:
            shelf_life = int(shelf_life_str)
            if shelf_life <= 0:
                raise ValueError("Shelf life must be positive")
        except ValueError:
            flash("อายุสินค้า (Shelf Life) ต้องเป็นตัวเลขจำนวนเต็มบวกเท่านั้น", "error")
            return render_template('edit_sku.html', sku_code=sku_code, sku_data=skus_info[sku_code])
        # --- สิ้นสุดการตรวจสอบ ---

        # ถ้าข้อมูลถูกต้อง
        skus_info[sku_code]['name'] = sku_name      # อัปเดตชื่อ
        skus_info[sku_code]['shelf_life'] = shelf_life # อัปเดตอายุ
        if save_skus(skus_info): # บันทึกลงไฟล์
            flash(f"แก้ไข SKU '{sku_code}' สำเร็จ!", "success")

        return redirect(url_for('manage_skus')) # กลับไปหน้ารายการ

    else: # ถ้าเป็น GET request
        # ดึงข้อมูล SKU ปัจจุบันเพื่อไปแสดงในฟอร์ม
        sku_data = skus_info[sku_code]
        return render_template('edit_sku.html', sku_code=sku_code, sku_data=sku_data)


@app.route('/skus/delete/<sku_code>', methods=['POST']) # ใช้ POST ป้องกันการลบโดยบังเอิญ
def delete_sku_route(sku_code):
    """จัดการการลบ SKU"""
    if sku_code in skus_info:
        del skus_info[sku_code] # ลบออกจาก Dictionary
        if save_skus(skus_info): # บันทึกลงไฟล์
            flash(f"ลบ SKU '{sku_code}' สำเร็จ!", "success")
    else:
        flash(f"ไม่พบ SKU '{sku_code}' ที่ต้องการลบ", "error")

    return redirect(url_for('manage_skus')) # กลับไปหน้ารายการเสมอ
# --- เพิ่ม Route สำหรับลบสต็อกล็อต ---
@app.route('/stock/delete/<batch_id>', methods=['POST'])
def delete_stock_batch(batch_id):
    """ลบสต็อกล็อตที่ระบุด้วย batch_id"""
    global inventory # บอกว่าจะใช้ตัวแปร inventory ด้านนอก

    batch_to_delete = None
    # วนหา batch ที่มี id ตรงกัน
    for batch in inventory:
        if batch.get('batch_id') == batch_id:
            batch_to_delete = batch
            break # เจอแล้ว หยุดหา

    if batch_to_delete:
        inventory.remove(batch_to_delete) # ลบออกจาก list inventory
        if save_inventory(inventory): # บันทึก inventory ล่าสุดลงไฟล์
            flash(f"ลบล็อตสินค้า '{batch_id}' สำเร็จ!", "success")
        # ถ้า save_inventory ไม่สำเร็จ มันจะ flash error เอง
    else:
        flash(f"ไม่พบล็อตสินค้า '{batch_id}' ที่ต้องการลบ", "error")

    return redirect(url_for('index')) # กลับไปหน้าหลักเสมอ
# --- สิ้นสุด Route ลบสต็อกล็อต ---

# --- สิ้นสุด Routes สำหรับจัดการ SKU ---
if __name__ == '__main__':
    app.run(debug=True)
# --- จบโค้ดสำหรับ app.py --