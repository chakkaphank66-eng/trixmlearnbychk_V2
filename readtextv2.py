import streamlit as st
import fitz  # PyMuPDF
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold, GenerationConfig
from PIL import Image, ImageChops # 🔥 เพิ่ม ImageChops เพื่อทำระบบ Auto-Crop ภาพให้แม่นยำ
import io
import time
import markdown
import re
import os
import pickle

# --- 1. การตั้งค่าเริ่มต้น และ Session State ---
keys_to_init = {
    'processed_data': {}, # เก็บ {'ai_text', 'user_text', 'img', 'extracted_images', 'raw_text'}
    'page_idx': 0, 'is_running': False, 'stop_clicked': False, 'full_summaries': "",
    'exhausted_models': {}, 'current_active_model': None, 'flash_models_list': [], 
    'pdf_bytes': None, 'pdf_name': "", 'selected_pages': [],
    'show_reset_confirm': False, 'settings_changed_alert': False, 'last_settings': {},
    'show_start_popup': False, 'estimated_tokens_used': 0, 'status_mode': 'blue',
    'user_api_key': "", 'phase': 'idle', 'global_data': {}, 
    'use_custom_prompt': False, 'custom_prompt_text': "",
    'use_custom_summary_prompt': False, 'custom_summary_prompt_1': "", 'custom_summary_prompt_2': "",
    'show_download_modal': False, 'base_pdf_doc_bytes': None
}

for k, v in keys_to_init.items():
    if k not in st.session_state: st.session_state[k] = v

st.set_page_config(page_title="Textbook Note Space 📚", layout="wide")

# --- 2. Custom CSS ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');
    html, body, [class*="st-"] { font-family: 'Sarabun', sans-serif !important; }
    .stApp { background-color: #F8FAFC; }
    .main-header { font-size: 2.2rem; font-weight: 800; color: #0F172A; margin-bottom: 1rem; letter-spacing: -0.5px; }
    
    /* 🔥 ปรับปรุงกล่องอ่านให้เป็นสไตล์สมุดโน้ตสะอาดตา ไม่มีสีฉูดฉาด */
    .reading-box { 
        background: #FFFFFF; border-radius: 12px; padding: 30px; 
        box-shadow: 0 4px 15px rgba(0,0,0,0.03); border: 1px solid #E2E8F0;
        font-size: 17px; line-height: 1.8; color: #1E293B; margin-bottom: 20px;
    }
    .reading-box h1, .reading-box h2, .reading-box h3 { color: #0F172A; margin-top: 1.5em; margin-bottom: 0.5em; border-bottom: 1px solid #F1F5F9; padding-bottom: 5px; }
    .reading-box strong, .reading-box b { color: #2563EB; font-weight: 700; background: #EFF6FF; padding: 0 4px; border-radius: 4px; }
    .reading-box table { width: 100%; border-collapse: collapse; margin: 20px 0; border-radius: 8px; overflow: hidden; }
    .reading-box th { background-color: #F8FAFC; padding: 12px; border-bottom: 2px solid #CBD5E1; color: #334155; text-align: left; }
    .reading-box td { border: 1px solid #E2E8F0; padding: 12px; }
    .reading-box ul, .reading-box ol { padding-left: 24px; } 
    .reading-box li { margin-bottom: 8px; }
    
    .status-blue { background: #EBF8FF; border-left: 5px solid #3182CE; color: #2B6CB0; padding: 15px; border-radius: 10px; margin-bottom: 15px;}
    .status-yellow { background: #FFFFF0; border-left: 5px solid #D69E2E; color: #B7791F; padding: 15px; border-radius: 10px; margin-bottom: 15px;}
    .status-red { background: #FFF5F5; border-left: 5px solid #E53E3E; color: #C53030; padding: 15px; border-radius: 10px; margin-bottom: 15px;}
    .status-purple { background: #FAF5FF; border-left: 5px solid #805AD5; color: #553C9A; padding: 15px; border-radius: 10px; margin-bottom: 15px;}
</style>
""", unsafe_allow_html=True)

# --- 3. ฟังก์ชันสกัดภาพและ Helper Functions ---

# 🔥 ตัดขอบขาว/โปร่งใสอัตโนมัติ เพื่อให้ภาพเข้ารูปพอดี
def auto_crop_image(img):
    try:
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
            bg.paste(img, (0, 0), img)
            img = bg.convert('RGB')
        elif img.mode != 'RGB': img = img.convert('RGB')
            
        bg = Image.new('RGB', img.size, (255, 255, 255))
        diff = ImageChops.difference(img, bg)
        bbox = diff.getbbox()
        if bbox: return img.crop(bbox)
    except: pass
    return img

# 🔥 สกัดเฉพาะภาพเนื้อหาจริงๆ (เตะพื้นหลังและขยะตกแต่งทิ้ง)
def extract_images_from_page(doc, page_num):
    page = doc[page_num]
    page_area = page.rect.width * page.rect.height
    image_list = page.get_image_info(xrefs=True)
    extracted_images = []
    seen_xrefs = set()
    
    for img_info in image_list:
        xref = img_info.get("xref")
        if not xref or xref in seen_xrefs: continue
        seen_xrefs.add(xref)
        
        bbox = img_info.get("bbox")
        if not bbox: continue
        rect = fitz.Rect(bbox)
        
        # 1. กรองภาพพื้นหลัง (ถ้าภาพกินพื้นที่เกิน 70% ของกระดาษ ถือว่าเป็น Background)
        if (rect.width * rect.height) > (page_area * 0.70): continue
        # 2. กรองจุดหรือไอคอนเล็กๆ ทิ้ง
        if rect.width < 80 or rect.height < 80: continue
        # 3. กรองแบนเนอร์/เส้นตกแต่ง (สัดส่วนแคบยาวผิดปกติ)
        ratio = rect.width / rect.height
        if ratio > 5.0 or ratio < 0.2: continue
        
        try:
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            im = Image.open(io.BytesIO(image_bytes))
            
            # 4. กรองสีพื้นล้วน (เช่น พื้นหลังสีเนื้อ/ขาวล้วน)
            extrema = im.convert("L").getextrema()
            if extrema and abs(extrema[1] - extrema[0]) < 15: continue
                
            # 5. Crop ขอบขาวทิ้ง
            cropped_im = auto_crop_image(im)
            if cropped_im.width < 50 or cropped_im.height < 50: continue
            
            img_byte_arr = io.BytesIO()
            cropped_im.save(img_byte_arr, format='PNG')
            extracted_images.append(img_byte_arr.getvalue())
        except: pass
    return extracted_images

def save_workspace():
    data = {k: st.session_state[k] for k in ['pdf_bytes', 'pdf_name', 'processed_data', 'global_data', 'selected_pages', 'full_summaries', 'user_api_key', 'custom_prompt_text', 'use_custom_prompt', 'custom_summary_prompt_1', 'custom_summary_prompt_2', 'use_custom_summary_prompt']}
    try:
        with open("autosave_workspace.pkl", "wb") as f: pickle.dump(data, f)
    except: pass

def load_workspace():
    if os.path.exists("autosave_workspace.pkl"):
        try:
            with open("autosave_workspace.pkl", "rb") as f:
                for k, v in pickle.load(f).items(): st.session_state[k] = v
            return True
        except: return False
    return False

def clear_workspace():
    if os.path.exists("autosave_workspace.pkl"):
        try: os.remove("autosave_workspace.pkl")
        except: pass

def get_best_available_model(models_list):
    current_time = time.time()
    st.session_state.exhausted_models = {k: v for k, v in st.session_state.exhausted_models.items() if v > current_time}
    preferred = ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash"]
    sorted_models = sorted(models_list, key=lambda x: next((i for i, p in enumerate(preferred) if p in x), 99))
    for m in sorted_models:
        if m not in st.session_state.exhausted_models: return m
    return "gemini-3.1-flash-lite" 

def calc_dynamic_fontsize(text, rect_width, rect_height):
    if not text or rect_width <= 0 or rect_height <= 0: return 18
    area = rect_width * rect_height
    char_count = max(1, len(text))
    return max(16, min(42, int((area / (char_count * 0.35)) ** 0.5)))

# --- 4. Sidebar: Settings ---
with st.sidebar:
    st.markdown("<h2 style='color: #2D3748;'>⚙️ ระบบอ่านอัจฉริยะ</h2>", unsafe_allow_html=True)
    is_locked = st.session_state.is_running
    
    api_input = st.text_input("🔑 ใส่ Gemini API Key:", type="password", value=st.session_state.user_api_key, disabled=is_locked)
    if api_input != st.session_state.user_api_key:
        st.session_state.user_api_key = api_input; save_workspace(); st.rerun()
        
    api_key = st.session_state.user_api_key
    if api_key:
        try:
            genai.configure(api_key=api_key)
            all_models = [m.name.replace("models/", "") for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            flash_models = [m for m in all_models if "flash-lite" in m.lower() or "3.1" in m.lower() or "flash" in m.lower()] 
            if not flash_models: flash_models = ["gemini-3.1-flash-lite"]
            flash_models = sorted(flash_models, key=lambda x: 0 if "3.1-flash-lite" in x else (1 if "2.5-flash-lite" in x else 2))
            st.session_state.flash_models_list = flash_models
            
            if is_locked: st.info("🔒 ระบบล็อกการตั้งค่าขณะรัน")
            else:
                display_options = []
                model_map = {}
                for m in flash_models:
                    status = f"⏳ [รอ]" if m in st.session_state.exhausted_models else "✅ [พร้อม]"
                    opt = f"{status} {m}"
                    display_options.append(opt)
                    model_map[opt] = m
                st.session_state.current_active_model = model_map[st.selectbox("AI Model:", display_options, index=0)]
        except: st.error("API Key ไม่ถูกต้อง")

    st.markdown("### 💳 Token Tracker")
    st.progress(min(st.session_state.estimated_tokens_used / 1000000, 1.0)) 
    st.caption(f"ใช้ไปแล้ว: **{st.session_state.estimated_tokens_used:,} Tokens**")

    st.divider()
    med_year = st.selectbox("ระดับ นสพ.", [2, 3, 4, 5, 6], index=2, disabled=is_locked)
    max_tokens = st.number_input("Max Output Tokens", min_value=100, max_value=8192, value=6000, step=500, disabled=is_locked)
    
    st.markdown("### 📐 จัดสรรพื้นที่ (Export PDF)")
    margin_right_pct = st.slider("เพิ่มพื้นที่ด้านขวา (%)", 0, 150, 60, disabled=is_locked)
    margin_bottom_pct = st.slider("เพิ่มพื้นที่ด้านล่าง (%)", 0, 150, 20, disabled=is_locked)

    st.markdown("### 📋 ตั้งค่ารูปแบบการอ่าน")
    want_original_flow = st.checkbox("📑 คงลำดับและเลขหัวข้อตามต้นฉบับเป๊ะๆ", value=True, disabled=is_locked)
    want_image_desc = st.checkbox("🖼️ อธิบายรูปภาพ/ตารางอย่างละเอียด", value=True, disabled=is_locked)
    want_continuous = st.checkbox("🔗 อ่านต่อเนื่อง (ตัดคำเกริ่นนำที่ไม่จำเป็น)", value=True, disabled=is_locked)
    want_clean_text = st.checkbox("🧹 ย่อยพารากราฟเป็น Bullet ให้อ่านง่าย", value=True, disabled=is_locked)
    want_summary = st.checkbox("🚨 ดึงคีย์เวิร์ดสรุปท้ายหน้า (High-Yield)", value=True, disabled=is_locked)

    st.markdown("### 🛠️ ปรับแต่ง Prompt วิศวกรข้อมูล")
    use_custom_prompt = st.checkbox("เปิดแก้ไข Prompt หลัก", value=st.session_state.use_custom_prompt, disabled=is_locked)
    
    # 🔥 ปรับ Prompt ใหม่ เน้นความต่อเนื่อง อ่านง่าย และไม่ใส่ตาราง/โครงสร้างประหลาด
    base_prompt_template = f"""คุณคือผู้เชี่ยวชาญการสรุปและเรียบเรียง Textbook / เอกสารการแพทย์ ตอบเป็นภาษาไทย
เป้าหมาย: เรียบเรียงเนื้อหาในหน้านี้ใหม่ให้ **สะอาดตา อ่านง่าย รวดเร็วกว่าการอ่านเต็ม แต่ความรู้ต้องครบถ้วน 100%**

**บริบทเนื้อหาความเชื่อมโยงของเอกสาร (+/- 10 หน้า):**
{{global_context}}

**ข้อความ Text ดิบจากหน้าปัจจุบัน (เพื่อความแม่นยำ):**
---
{{raw_text}}
---

**กฎการจัดเนื้อหา (ต้องทำตามอย่างเคร่งครัด):**
{{strict_pattern}}"""

    if use_custom_prompt:
        st.session_state.custom_prompt_text = st.text_area("แก้ไข Prompt", value=st.session_state.custom_prompt_text or base_prompt_template, height=350, disabled=is_locked)
    else:
        st.session_state.custom_prompt_text = base_prompt_template
    st.session_state.use_custom_prompt = use_custom_prompt

    st.markdown("### 📝 ปรับแต่ง Prompt One-Sheet")
    use_custom_summary_prompt = st.checkbox("เปิดแก้ไข Summary Prompt", value=st.session_state.use_custom_summary_prompt, disabled=is_locked)
    default_summary_prompt_1 = f"สรุป High-yield สำหรับ นสพ.ปี {med_year} จัดรูปแบบมินิมอล **มีข้อมูลเปรียบเทียบให้ทำเป็น Markdown Table**:\nข้อมูลอ้างอิง:\n{{full_summaries}} เรียงเนื้อหาตามเอกสาร จัดเรียงหัวข้อให้ชัดเจน"
    default_summary_prompt_2 = "สร้าง Clinical One-Sheet Summary แผ่นที่ 2 (เน้นเจาะลึกโรคและการวินิจฉัย)\nสกัดข้อมูลโรคสำคัญออกมา นำเสนอเป็นตาราง Markdown:\n1. โรค\n2. อาการเด่น\n3. เกณฑ์วินิจฉัย/Mnemonic\n4. Differential diagnosis\n5. Management/ยา\nข้อมูลอ้างอิง:\n{full_summaries}"

    if use_custom_summary_prompt:
        st.session_state.custom_summary_prompt_1 = st.text_area("Prompt แผ่น 1", value=st.session_state.custom_summary_prompt_1 or default_summary_prompt_1, height=150, disabled=is_locked)
        st.session_state.custom_summary_prompt_2 = st.text_area("Prompt แผ่น 2", value=st.session_state.custom_summary_prompt_2 or default_summary_prompt_2, height=150, disabled=is_locked)
    else:
        st.session_state.custom_summary_prompt_1 = default_summary_prompt_1
        st.session_state.custom_summary_prompt_2 = default_summary_prompt_2
    st.session_state.use_custom_summary_prompt = use_custom_summary_prompt

    if st.button("💾 บันทึกการตั้งค่า", use_container_width=True): save_workspace(); st.toast("บันทึกแล้ว!")

# --- 5. Main UI: การอัปโหลดไฟล์ ---
st.markdown("<div class='main-header'>📚 Textbook Note Space: ทุบกำแพงตัวหนังสือ</div>", unsafe_allow_html=True)

if not st.session_state.pdf_bytes:
    if os.path.exists("autosave_workspace.pkl"):
        st.info("💾 **พบงานที่ทำค้างไว้!**")
        if st.button("🔄 กู้คืนงานที่ทำค้างไว้", type="primary"):
            if load_workspace(): st.success("กู้คืนสำเร็จ!"); time.sleep(1); st.rerun()
    
    uploaded_file = st.file_uploader("อัปโหลด Textbook/Paper/Slides (PDF)", type="pdf")
    if uploaded_file:
        st.session_state.pdf_bytes = uploaded_file.getvalue()
        st.session_state.pdf_name = uploaded_file.name
        doc_tmp = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
        st.session_state.selected_pages = list(range(len(doc_tmp)))
        save_workspace(); st.rerun()
else:
    st.info(f"📄 ไฟล์ปัจจุบัน: **{st.session_state.pdf_name}**")
    if st.button("🗑️ เปลี่ยนเอกสาร (Reset)"): st.session_state.show_reset_confirm = True

    if st.session_state.show_reset_confirm:
        st.warning("ยืนยันการล้างข้อมูลทั้งหมด?")
        c1, c2 = st.columns(2)
        if c1.button("✅ ยืนยัน", type="primary"): clear_workspace(); [st.session_state.pop(k) for k in keys_to_init if k in st.session_state]; st.rerun()
        if c2.button("❌ ยกเลิก"): st.session_state.show_reset_confirm = False; st.rerun()

# --- 6. ระบบหน้าตาแอป & เลือกหน้า ---
if st.session_state.pdf_bytes and not is_locked:
    doc_in = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
    total_pages = len(doc_in)
    
    with st.expander("🖼️ เลือกหน้าที่จะให้ AI จัดโครงสร้างใหม่", expanded=True):
        c_btn1, c_btn2, c_btn3 = st.columns([1,1,2])
        if c_btn1.button("✅ เลือกทั้งหมด"): st.session_state.selected_pages = list(range(total_pages)); st.rerun()
        if c_btn2.button("❌ ไม่เลือกเลย"): st.session_state.selected_pages = []; st.rerun()
        if c_btn3.button("💾 ยืนยันการเลือกหน้า", type="primary"): save_workspace(); st.rerun()
        
        st.write("---")
        for row_idx in range(0, total_pages, 5):
            cols = st.columns(5)
            for col_idx in range(5):
                page_num = row_idx + col_idx
                if page_num < total_pages:
                    with cols[col_idx]:
                        st.image(doc_in[page_num].get_pixmap(dpi=40).tobytes("png"), use_container_width=True) 
                        is_checked = st.checkbox(f"หน้า {page_num+1}", value=(page_num in st.session_state.selected_pages), key=f"sel_{page_num}")
                        if is_checked and page_num not in st.session_state.selected_pages: st.session_state.selected_pages.append(page_num)
                        elif not is_checked and page_num in st.session_state.selected_pages: st.session_state.selected_pages.remove(page_num)

# --- 7. แถบสถานะ และ ปุ่มรัน ---
if st.session_state.pdf_bytes:
    doc_in = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
    total_pages = len(doc_in)
    
    if st.session_state.show_start_popup:
        with st.container():
            pages_to_do = len([i for i in st.session_state.selected_pages if i not in st.session_state.processed_data])
            st.info(f"📊 หน้าที่ต้องประมวลผลเพิ่ม: **{pages_to_do} หน้า**")
            c_start1, c_start2 = st.columns(2)
            if c_start1.button("✅ ยืนยันรันงาน", type="primary"):
                if not st.session_state.current_active_model or st.session_state.current_active_model in st.session_state.exhausted_models:
                    st.session_state.current_active_model = get_best_available_model(st.session_state.flash_models_list)
                if st.session_state.phase == 'idle': st.session_state.phase = 'global_scan'
                st.session_state.is_running = True; st.session_state.stop_clicked = False; st.session_state.show_start_popup = False; st.rerun()
            if c_start2.button("❌ ยกเลิก"): st.session_state.show_start_popup = False; st.rerun()
    
    action_placeholder = st.empty() 

    col_run1, col_ctrl2, col_ctrl3 = st.columns([1,1,1])
    if col_run1.button("🚀 Start / Continue อัตโนมัติ", type="primary", disabled=is_locked): st.session_state.show_start_popup = True; st.rerun()
    if col_ctrl2.button("🛑 Stop / Pause", disabled=not st.session_state.is_running): st.session_state.is_running = False; st.session_state.stop_clicked = True; st.rerun()

    # --- 8. E-BOOK READER & EDITING ---
    st.write("---")
    st.subheader(f"📖 เนื้อหา: หน้า {st.session_state.page_idx + 1}")
    
    c_nav1, c_nav2, c_nav3 = st.columns([1, 2, 1])
    with c_nav1:
        if st.button("⬅️ หน้าก่อนหน้า") and st.session_state.page_idx > 0: st.session_state.page_idx -= 1; st.rerun()
    with c_nav2:
        new_page = st.slider("กระโดดไปหน้า:", 1, total_pages, st.session_state.page_idx + 1, label_visibility="collapsed")
        if new_page - 1 != st.session_state.page_idx: st.session_state.page_idx = new_page - 1; st.rerun()
    with c_nav3:
        if st.button("หน้าถัดไป ➡️") and st.session_state.page_idx < total_pages - 1: st.session_state.page_idx += 1; st.rerun()

    curr = st.session_state.page_idx
    col_left, col_right = st.columns([1, 1.3])
    
    with col_left:
        st.markdown(f"**ภาพต้นฉบับ**")
        st.image(doc_in[curr].get_pixmap(dpi=100).tobytes("png"), use_container_width=True)

    with col_right:
        if curr in st.session_state.processed_data:
            data = st.session_state.processed_data[curr]
            st.markdown(f"**✨ เนื้อหาที่ AI จัดโครงสร้างใหม่**")
            
            ai_content = data["ai_text"]
            ext_images = data.get("extracted_images", [])
            
            st.markdown("<div class='reading-box'>", unsafe_allow_html=True)
            
            # ระบบแทรกรูปภาพ
            parts = ai_content.split("[IMAGE_PLACEHOLDER]")
            for i, text_part in enumerate(parts):
                st.markdown(markdown.markdown(text_part, extensions=['tables']), unsafe_allow_html=True)
                if i < len(parts) - 1:
                    if i < len(ext_images):
                        st.image(ext_images[i], use_container_width=True, caption="รูปภาพประกอบจากต้นฉบับ")
                    else: st.info("🖼️ [รูปภาพเพิ่มเติมดูได้จากต้นฉบับฝั่งซ้าย]")
            
            st.markdown("</div>", unsafe_allow_html=True)
            
            with st.expander("🔍 ดูข้อความ Text ดิบ (กันข้อมูลตกหล่น)"):
                st.text(data.get("raw_text", ""))
        else:
            st.info(f"⏳ หน้าที่ {curr+1} ยังไม่ได้ประมวลผล (อยู่ในคิว)...")

    # --- 9. Export PDF & Compression ---
    st.write("---")
    if len(st.session_state.processed_data) > 0:
        if st.button("📦 รวบรวมและเตรียมดาวน์โหลด PDF (พร้อมภาพประกอบ + สรุป 2 แผ่น)"):
            with st.spinner("กำลังประกอบร่างไฟล์ PDF ฉบับสมบูรณ์... (อาจใช้เวลา 1-2 นาที)"):
                doc_out = fitz.open()
                arch_path = "."
                
                for i in range(total_pages):
                    p_in = doc_in[i]; w, h = p_in.rect.width, p_in.rect.height
                    new_w, new_h = w * (1 + margin_right_pct/100), max(h, h * (1 + margin_bottom_pct/100))
                    p_out = doc_out.new_page(width=new_w, height=new_h)
                    p_out.show_pdf_page(fitz.Rect(0, 0, w, h), doc_in, i)
                    
                    # ระบายสีพื้นหลังให้ส่วนที่งอกออกมา
                    bg_color = (0.97, 0.98, 0.99)
                    if margin_right_pct > 0: p_out.draw_rect(fitz.Rect(w, 0, new_w, new_h), color=bg_color, fill=bg_color, width=0)
                    if margin_bottom_pct > 0: p_out.draw_rect(fitz.Rect(0, h, w, new_h), color=bg_color, fill=bg_color, width=0)
                    
                    # 🔥 กล่องสำหรับเนื้อหา (ลากยาวขวาลงล่างสุด เป็นพื้นที่อ่านเนื้อหาล้วนๆ)
                    content_box = fitz.Rect(w + 10, 10, new_w - 10, new_h - 10) if margin_right_pct > 0 else fitz.Rect(10, h + 10, w - 10, new_h - 10)
                    
                    if i in st.session_state.processed_data:
                        data = st.session_state.processed_data[i]
                        ai_text = data["ai_text"]
                        images = data.get("extracted_images", [])
                        
                        if ai_text and "⚠️" not in ai_text:
                            # เขียนรูปลงไฟล์ชั่วคราว เพื่อเตรียมให้ HTML ดึงไปใช้
                            html_parts = ai_text.split("[IMAGE_PLACEHOLDER]")
                            final_html_str = ""
                            temp_image_files = []
                            
                            for idx, part in enumerate(html_parts):
                                final_html_str += markdown.markdown(part, extensions=['tables'])
                                if idx < len(html_parts) - 1 and idx < len(images):
                                    tmp_filename = f"tmp_export_img_p{i}_{idx}.png"
                                    try:
                                        with open(tmp_filename, "wb") as f: f.write(images[idx])
                                        temp_image_files.append(tmp_filename)
                                        # แทรก tag <img> วางรูปให้อยู่ตรงกลาง สวยงาม ไม่ล้นขอบ
                                        final_html_str += f"<div style='text-align:center; margin: 15px 0;'><img src='{tmp_filename}' style='max-width: 90%; max-height: 350px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);'></div>"
                                    except: pass
                            
                            # CSS แนว Textbook สะอาดตา
                            f_size = max(14, min(36, int(((content_box.width * content_box.height) / (max(1, len(final_html_str)) * 0.35)) ** 0.5)))
                            css = f"@font-face {{ font-family: 'T'; src: url('THSarabunNew.ttf'); }} @font-face {{ font-family: 'T'; font-weight: bold; src: url('THSarabunNew Bold.ttf'); }} body {{ font-family: 'T'; font-size: {f_size}px; line-height: 1.6; color: #1E293B; margin: 0; padding: 0; }} h1, h2, h3, h4 {{ color: #0F172A; margin-top: 1em; margin-bottom: 0.5em; }} b, strong {{ font-weight: bold; color: #2563EB; }} ul, ol {{ margin: 8px 0; padding-left: 20px; }} li {{ margin-bottom: 6px; }} table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }} th {{ background: #F8FAFC; border: 1px solid #CBD5E1; padding: 8px; text-align: left; }} td {{ border: 1px solid #E2E8F0; padding: 8px; }}"
                            
                            try: p_out.insert_htmlbox(content_box, f"<style>{css}</style><body>{final_html_str}</body>", archive=fitz.Archive(arch_path))
                            except: p_out.insert_textbox(content_box, ai_text.replace("[IMAGE_PLACEHOLDER]", "[ภาพประกอบ]"), fontsize=f_size)
                            
                            for tmp_file in temp_image_files:
                                try: os.remove(tmp_file)
                                except: pass
                
                # --- One-Sheet Summary (2 แผ่นสุดท้ายเท่านั้น ตามสั่ง) ---
                if st.session_state.full_summaries:
                    model_os = genai.GenerativeModel(get_best_available_model(st.session_state.flash_models_list) or "gemini-3.1-flash-lite")
                    safety = { HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE }
                    data_chunk = st.session_state.full_summaries[:30000]
                    
                    try: os_res_1 = model_os.generate_content(st.session_state.custom_summary_prompt_1.replace("{full_summaries}", data_chunk), safety_settings=safety); os_html_1 = markdown.markdown(os_res_1.text, extensions=['tables'])
                    except: os_html_1 = "Summary 1 ไม่พร้อม"
                    p_os_1 = doc_out.new_page(width=595, height=842)
                    css_os = f"@font-face {{ font-family: 'T'; src: url('THSarabunNew.ttf'); }} body {{ font-family: 'T'; font-size: 16px; color: #334155; }} h2 {{ text-align: center; border-bottom: 2px solid #0EA5E9; padding-bottom: 5px;}} table {{ width: 100%; border-collapse: collapse; margin: 10px 0;}} th, td {{ border: 1px solid #E2E8F0; padding: 6px; }} th {{ background-color: #F8FAFC; }}"
                    p_os_1.insert_htmlbox(fitz.Rect(40,40,555,802), f"<style>{css_os}</style><body><h2>⭐ CLINICAL ONE-SHEET (OVERVIEW) ⭐</h2>{os_html_1}</body>", archive=fitz.Archive("."))

                    try: os_res_2 = model_os.generate_content(st.session_state.custom_summary_prompt_2.replace("{full_summaries}", data_chunk), safety_settings=safety); os_html_2 = markdown.markdown(os_res_2.text, extensions=['tables'])
                    except: os_html_2 = "Summary 2 ไม่พร้อม"
                    p_os_2 = doc_out.new_page(width=595, height=842)
                    css_os_2 = f"@font-face {{ font-family: 'T'; src: url('THSarabunNew.ttf'); }} body {{ font-family: 'T'; font-size: 16px; color: #334155; }} h2 {{ text-align: center; border-bottom: 2px solid #14B8A6; padding-bottom: 5px;}} table {{ width: 100%; border-collapse: collapse; margin: 10px 0;}} th, td {{ border: 1px solid #E2E8F0; padding: 6px; }} th {{ background-color: #F0FDFA; }}"
                    p_os_2.insert_htmlbox(fitz.Rect(40,40,555,802), f"<style>{css_os_2}</style><body><h2>⭐ CLINICAL ONE-SHEET (DISEASE FOCUS) ⭐</h2>{os_html_2}</body>", archive=fitz.Archive("."))

                st.session_state.base_pdf_doc_bytes = doc_out.tobytes()
                st.session_state.show_download_modal = True

        if st.session_state.get('show_download_modal') and st.session_state.get('base_pdf_doc_bytes'):
            st.markdown("""<div style="border: 2px solid #3182CE; border-radius: 12px; padding: 25px; background-color: #F8FAFC; margin-top: 15px;">
                <h3 style="color: #2B6CB0; margin-top: 0;">🗜️ ตั้งค่าการบีบอัดไฟล์ PDF</h3>""", unsafe_allow_html=True)
            
            raw_bytes = st.session_state.base_pdf_doc_bytes
            temp_doc = fitz.open(stream=raw_bytes, filetype="pdf")
            orig_size_mb = len(raw_bytes) / (1024 * 1024)
            st.markdown(f"📁 ขนาดต้นฉบับ: **{orig_size_mb:.2f} MB**")
            
            comp_choice = st.radio("เลือกระดับการบีบอัด:", ["2. แนะนำ (สมดุล)", "1. ขั้นสุด (เล็กสุด)", "3. ปกติ (คุณภาพสูง)"])
            with st.spinner("กำลังบีบอัด..."):
                if "ขั้นสุด" in comp_choice: final_bytes = temp_doc.tobytes(garbage=4, deflate=True, clean=True)
                elif "แนะนำ" in comp_choice: final_bytes = temp_doc.tobytes(garbage=3, deflate=True)
                else: final_bytes = temp_doc.tobytes(garbage=1, deflate=True)
                final_size_mb = len(final_bytes) / (1024 * 1024)

            st.markdown(f"📉 หลังบีบอัด: <strong style='color: #E53E3E;'>{final_size_mb:.2f} MB</strong>", unsafe_allow_html=True)
            st.download_button("💾 ดาวน์โหลดไฟล์ PDF", data=final_bytes, file_name=f"ReStructured_{st.session_state.pdf_name}", mime="application/pdf", type="primary")
            if st.button("❌ ปิด"): st.session_state.show_download_modal = False; st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    # --- 10. ระบบประมวลผลหลังบ้าน (Background Worker - 2 Phases) ---
    if st.session_state.is_running and not st.session_state.stop_clicked:
        active_m = st.session_state.current_active_model
        model = genai.GenerativeModel(active_m)
        config = GenerationConfig(max_output_tokens=max_tokens)
        safety = { HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE }

        # --- PHASE 1: GLOBAL SCAN (Triage) ---
        if st.session_state.phase == 'global_scan':
            target_global = next((i for i in st.session_state.selected_pages if i not in st.session_state.global_data), None)
            if target_global is None:
                st.session_state.phase = 'detail_scan'; save_workspace(); st.rerun()
            else:
                action_placeholder.markdown(f"<div class='status-purple'><b>🔍 [Phase 1/2] ประเมินโครงสร้างภาพรวม (หน้า {target_global+1}/{total_pages})</b></div>", unsafe_allow_html=True)
                img = Image.open(io.BytesIO(doc_in[target_global].get_pixmap(dpi=50).tobytes("png")))
                
                prompt_global = """วิเคราะห์สไลด์/หน้าหนังสือนู้นี้อย่างรวดเร็ว ตอบกลับตามรูปแบบนี้เท่านั้น:
                TOPIC: (ชื่อหัวข้อเรื่องสั้นๆ)
                SUMMARY: (สรุปใจความสำคัญสั้นๆ 1 ประโยค)
                PRIORITY: (ประเมินเป็น HIGH, MEDIUM, LOW)"""
                try:
                    resp = model.generate_content([prompt_global, img], safety_settings=safety, generation_config=GenerationConfig(max_output_tokens=150))
                    text = resp.text.strip()
                    st.session_state.estimated_tokens_used += len(text)
                    topic = text.split("TOPIC:")[1].split("SUMMARY:")[0].strip() if "TOPIC:" in text else f"หน้า {target_global+1}"
                    summary_raw = text.split("SUMMARY:")[1] if "SUMMARY:" in text else "ข้อมูล"
                    if "PRIORITY:" in summary_raw:
                        summary, priority = summary_raw.split("PRIORITY:")[0].strip(), summary_raw.split("PRIORITY:")[1].strip().upper()
                    else: summary, priority = summary_raw.strip(), "MEDIUM"
                    st.session_state.global_data[target_global] = {'topic': topic, 'summary': summary, 'priority': priority}
                    save_workspace() 
                except: st.session_state.global_data[target_global] = {'topic': f"หน้า {target_global+1}", 'summary': "", 'priority': 'MEDIUM'}
                time.sleep(0.1); st.rerun()

        # --- PHASE 2: DETAIL SCAN (-10 ถึง +10 Context + Data Extraction) ---
        elif st.session_state.phase == 'detail_scan':
            target = next((i for i in range(total_pages) if i in st.session_state.processed_data and "⚠️" in st.session_state.processed_data[i].get("ai_text", "")), None)
            is_recheck = target is not None
            if target is None: target = next((i for i in range(total_pages) if i not in st.session_state.processed_data and i in st.session_state.selected_pages), None)

            if target is not None:
                st.session_state.status_mode = 'yellow' if is_recheck else 'blue'
                msg = f"🔄 ซ่อมหน้าที่ Error (หน้า {target+1})" if is_recheck else f"⚡ จัดโครงสร้างข้อมูลหน้าที่ {target+1} / {total_pages}"
                action_placeholder.markdown(f"<div class='status-{st.session_state.status_mode}'><b>{msg}</b><br>🤖 วิเคราะห์ Context อดีต 10 - อนาคต 10 | <code>{active_m}</code></div>", unsafe_allow_html=True)
                
                # 1. สร้าง Context Window (-10 ถึง +10 หน้า)
                start_idx, end_idx = max(0, target - 10), min(total_pages, target + 11)
                local_context_lines = []
                for idx in range(start_idx, end_idx):
                    if idx in st.session_state.global_data:
                        g_info = st.session_state.global_data[idx]
                        prefix = "👉 [หน้านี้กำลังแปล]" if idx == target else "-"
                        local_context_lines.append(f"{prefix} หน้า {idx+1} ({g_info['topic']}): {g_info['summary']} [Priority: {g_info.get('priority','MEDIUM')}]")
                local_context_text = "\n".join(local_context_lines)

                # 2. สกัดรูปภาพและ Text ดิบ
                raw_text = doc_in[target].get_text()
                extracted_images = extract_images_from_page(doc_in, target)
                
                p_img = doc_in[target].get_pixmap(dpi=75)
                img = Image.open(io.BytesIO(p_img.tobytes("png")))

                # 3. เตรียมกฎการเขียนโครงสร้างตามที่ตั้งค่า
                pattern_parts = []
                pattern_parts.append("1. **ห้ามใช้คำทักทายเด็ดขาด** และไม่ต้องเกริ่นนำ ให้เริ่มเนื้อหาทันที")
                
                if want_original_flow:
                    pattern_parts.append("2. **ลำดับเนื้อหา:** อิงตามลำดับหัวข้อและเลขหัวข้อของต้นฉบับเป๊ะๆ หากต้นฉบับมีเลขข้อ ให้ใช้เลขเดิม ถ้าไม่มีให้เรียบเรียงใหม่เป็นข้อๆ ให้เข้าใจง่าย")
                if want_clean_text:
                    pattern_parts.append("3. **รูปแบบ:** ย่อยเนื้อหาเป็น Bullet ให้อ่านง่าย กระชับ สะอาดตา และเน้น **ตัวหนา** ที่คีย์เวิร์ดสำคัญ ไม่ต้องสร้างตารางขึ้นมาเองถ้าในต้นฉบับไม่มี")
                if want_image_desc:
                    pattern_parts.append("4. **อธิบายรูปภาพ/ตาราง:** หากในสไลด์ต้นฉบับมีรูปภาพ แผนภาพ หรือตาราง ให้คุณอธิบายรูปนั้นอย่างละเอียดให้ผู้อ่านเข้าใจและเห็นภาพ และ **บังคับพิมพ์คำว่า `[IMAGE_PLACEHOLDER]`** แทรกไว้ในตำแหน่งนั้นเสมอ เพื่อให้ระบบนำรูปจริงมาแปะ")
                if want_continuous:
                    pattern_parts.append("5. **ความต่อเนื่อง (สำคัญมาก):** เช็คเนื้อหาจากหน้าก่อนหน้าและหน้าถัดไป ห้ามเกริ่นนำใหม่ถ้าเนื้อหายังต่อเนื่องจากหน้าเดิม และถ้าเนื้อหาหน้านี้ยังไม่จบ ห้ามพูดสรุปตัดจบเด็ดขาด ให้เขียนเนื้อหาเชื่อมโยงลื่นไหลไปเลย")
                if want_summary:
                    pattern_parts.append("6. **High-Yield:** ตอนท้ายสุดของเนื้อหา ให้สรุปประเด็นคีย์เวิร์ดที่สำคัญที่สุด 1-2 ข้อ (เพื่อดึงไปทำสรุปท้ายเล่ม)")
                
                strict_pattern = "\n".join(pattern_parts)

                # 4. รวมร่าง Prompt
                prompt = st.session_state.custom_prompt_text.replace("{global_context}", local_context_text).replace("{raw_text}", raw_text).replace("{strict_pattern}", strict_pattern)
                
                is_success, retry_count = False, 0
                while retry_count < 2 and not is_success:
                    try:
                        resp = model.generate_content([prompt, img], safety_settings=safety, generation_config=config)
                        final_text = resp.text.strip()
                        st.session_state.estimated_tokens_used += len(final_text) 
                        
                        # เก็บสะสมข้อมูลทำ One-sheet summary 2 แผ่นท้าย
                        if want_summary and "High-Yield:" in final_text:
                            st.session_state.full_summaries += f"\n[Page {target+1}] " + final_text.split("High-Yield:")[-1].strip()
                        
                        st.session_state.processed_data[target] = {
                            "ai_text": final_text, "user_text": "", "img": p_img.tobytes("png"),
                            "extracted_images": extracted_images, "raw_text": raw_text
                        }
                        save_workspace(); is_success = True
                    except Exception as e:
                        if "429" in str(e) or "Quota" in str(e):
                            st.session_state.exhausted_models[active_m] = time.time() + 60
                            action_placeholder.markdown(f"<div class='status-yellow'><b>⚠️ คิวเต็ม! กำลังหาโมเดลสำรอง...</b></div>", unsafe_allow_html=True); time.sleep(2)
                            new_model = get_best_available_model(st.session_state.flash_models_list)
                            if new_model: active_m = st.session_state.current_active_model = new_model; model = genai.GenerativeModel(new_model); retry_count += 1
                            else: st.session_state.processed_data[target] = {"ai_text": "⚠️ โควต้าเต็มทุกโมเดล กด Pause รอ 1 นาที", "user_text": "", "img": p_img.tobytes("png")}; is_success = True
                        else: st.session_state.processed_data[target] = {"ai_text": f"⚠️ Error: {str(e)}", "user_text": "", "img": p_img.tobytes("png")}; is_success = True
                time.sleep(0.1); st.rerun()
            else:
                st.session_state.is_running, st.session_state.phase = False, 'idle'
                action_placeholder.markdown(f"<div class='status-blue' style='border-left-color: #38A169; color: #2F855A; background: #F0FFF4;'><b>✅ ประมวลผลเสร็จสิ้น!</b></div>", unsafe_allow_html=True)
