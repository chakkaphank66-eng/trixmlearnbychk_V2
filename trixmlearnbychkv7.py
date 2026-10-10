import streamlit as st
import fitz  # PyMuPDF
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold, GenerationConfig
from PIL import Image, ImageChops # 🔥 เพิ่ม ImageChops เพื่อทำระบบ Auto-Crop
import io
import time
import datetime
import markdown
import re
import os
import pickle

# --- 1. การตั้งค่าเริ่มต้น และ Session State ---
keys_to_init = {
    'processed_data': {}, 
    'page_idx': 0,
    'is_running': False,
    'stop_clicked': False,
    'full_summaries': "",
    'exhausted_models': {},
    'current_active_model': None,
    'flash_models_list': [], 
    'pdf_bytes': None,
    'pdf_name': "",
    'selected_pages': [],
    'show_reset_confirm': False,
    'settings_changed_alert': False,
    'last_settings': {},
    'show_start_popup': False, 
    'estimated_tokens_used': 0,
    'status_mode': 'blue',
    'user_api_key': "",
    
    # Context & Triage
    'phase': 'idle', 
    'global_data': {}, # เก็บ {'topic': '', 'summary': '', 'priority': ''} ของแต่ละหน้า
    
    # Custom Prompts
    'use_custom_prompt': False,
    'custom_prompt_text': "",
    'use_custom_summary_prompt': False,
    'custom_summary_prompt_1': "",
    'custom_summary_prompt_2': "",
    
    # PDF compression
    'show_download_modal': False,
    'base_pdf_doc_bytes': None
}

for k, v in keys_to_init.items():
    if k not in st.session_state:
        st.session_state[k] = v

st.set_page_config(page_title="PDF Note Space 🩺", layout="wide")

# --- 2. Custom CSS & Minimalist Design ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');
    
    html, body, [class*="st-"] { font-family: 'Sarabun', sans-serif !important; }
    .stApp { background-color: #F8FAFC; }
    .main-header { font-size: 2.2rem; font-weight: 800; color: #0F172A; margin-bottom: 1rem; letter-spacing: -0.5px; }
    .stButton>button { border-radius: 8px; transition: all 0.3s; font-weight: 600; }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
    
    .edit-box { 
        border: 1px solid #F1F5F9; border-radius: 16px; padding: 24px; 
        background: #FFFFFF; font-size: 17px; line-height: 1.8; color: #334155;
        box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.04);
    }
    .edit-box strong, .edit-box b { color: #0F172A; font-weight: 700; }
    
    .box-intro { background-color: #F8FAFC; border-left: 4px solid #94A3B8; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; }
    .box-concept { background-color: #EEF2FF; border-left: 4px solid #6366F1; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; }
    .box-mech { background-color: #F1F5F9; border-left: 4px solid #475569; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; }
    .box-clinic { background-color: #F0FDFA; border-left: 4px solid #14B8A6; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; }
    .box-warn { background-color: #FFF7ED; border-left: 4px solid #F97316; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; }
    .box-trick { background-color: #FEF9C3; border-left: 4px solid #EAB308; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; }
    .box-hy { background-color: #FFF1F2; border-left: 4px solid #F43F5E; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; }
    .box-quiz { background-color: #F0F9FF; border-left: 4px solid #0EA5E9; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; }
    .box-ans { background-color: #F0FDF4; border-left: 4px solid #22C55E; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; }
    
    .box-hy strong, .box-hy b { font-weight: 700; }
    .edit-box ul, .edit-box ol { margin-top: 0.5rem; margin-bottom: 1rem; padding-left: 1.5rem; }
    .edit-box li, .edit-box p { margin-bottom: 12px; }
    .edit-box table { width: 100%; border-collapse: collapse; margin: 20px 0; border-radius: 8px; overflow: hidden; font-size: 16px; }
    .edit-box th { background-color: #F8FAFC; padding: 12px; border-bottom: 2px solid #E2E8F0; color: #475569; text-align: left; }
    .edit-box td { padding: 12px; border-bottom: 1px solid #F1F5F9; }
    
    .status-blue { background: #EBF8FF; border-left: 5px solid #3182CE; color: #2B6CB0; padding: 15px; border-radius: 10px; margin-bottom: 15px;}
    .status-yellow { background: #FFFFF0; border-left: 5px solid #D69E2E; color: #B7791F; padding: 15px; border-radius: 10px; margin-bottom: 15px;}
    .status-red { background: #FFF5F5; border-left: 5px solid #E53E3E; color: #C53030; padding: 15px; border-radius: 10px; margin-bottom: 15px;}
    .status-purple { background: #FAF5FF; border-left: 5px solid #805AD5; color: #553C9A; padding: 15px; border-radius: 10px; margin-bottom: 15px;}
</style>
""", unsafe_allow_html=True)

# --- 3. ฟังก์ชันอัจฉริยะ (Helper Functions) ---

# 🔥 ระบบตัดขอบขาว/โปร่งใสอัตโนมัติ
def auto_crop_image(img):
    try:
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
            bg.paste(img, (0, 0), img)
            img = bg.convert('RGB')
        elif img.mode != 'RGB':
            img = img.convert('RGB')
            
        bg = Image.new('RGB', img.size, (255, 255, 255))
        diff = ImageChops.difference(img, bg)
        bbox = diff.getbbox()
        if bbox:
            return img.crop(bbox)
    except: pass
    return img

# 🔥 อัปเกรดระบบสกัดภาพ: ป้องกันพื้นหลัง และ ครอปให้แม่นยำ
def extract_images_from_page(doc, page_num):
    page = doc[page_num]
    page_rect = page.rect
    page_area = page_rect.width * page_rect.height
    
    image_list = page.get_image_info(xrefs=True)
    extracted_images = []
    seen_xrefs = set()
    
    for img_info in image_list:
        xref = img_info.get("xref")
        if not xref or xref in seen_xrefs: 
            continue
        seen_xrefs.add(xref)
        
        bbox = img_info.get("bbox")
        if not bbox: 
            continue
            
        rect = fitz.Rect(bbox)
        img_area = rect.width * rect.height
        
        # 1. กรองภาพพื้นหลัง (Background Filter): พื้นที่รูปกินสัดส่วนเกิน 70% ของหน้า = ทิ้ง
        if img_area > (page_area * 0.70):
            continue
            
        # 2. กรองจุดเล็กๆ ไอคอน โลโก้
        if rect.width < 80 or rect.height < 80:
            continue
            
        # 3. กรองแบนเนอร์หรือเส้นคั่น (สัดส่วนความกว้าง:ยาว ผิดปกติ)
        ratio = rect.width / rect.height
        if ratio > 5.0 or ratio < 0.2:
            continue
        
        try:
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            im = Image.open(io.BytesIO(image_bytes))
            
            # 4. กรองสีพื้นล้วน (Solid Color Blocks / Textures)
            extrema = im.convert("L").getextrema()
            if extrema and abs(extrema[1] - extrema[0]) < 15:
                continue
                
            # 5. ระบบตัดขอบให้ภาพเข้ารูปพอดีเป๊ะ (Auto-Crop)
            cropped_im = auto_crop_image(im)
            
            # เช็คอีกครั้งว่าหลัง Crop แล้วเหลือภาพใหญ่พอไหม
            if cropped_im.width < 50 or cropped_im.height < 50:
                continue
            
            # Save กลับเป็น Byte
            img_byte_arr = io.BytesIO()
            cropped_im.save(img_byte_arr, format='PNG')
            extracted_images.append(img_byte_arr.getvalue())
            
        except Exception as e:
            pass
            
    return extracted_images

def distribute_content(text, layout_prefs):
    boxes = {"ด้านขวา": "", "ด้านล่าง": "", "ด้านซ้าย": "", "ด้านบน": ""}
    current_box = layout_prefs.get("Intro", "ด้านขวา") 
    
    lines = text.split('\n')
    for line in lines:
        lower_line = line.lower()
        if "intro:" in lower_line or "concept หลัก:" in lower_line:
            current_box = layout_prefs["Intro"]
        elif "กลไก" in lower_line or "ตัวอย่าง:" in lower_line or "การนำไปใช้" in lower_line:
            current_box = layout_prefs["Mech"]
        elif "ระวัง:" in lower_line or "ข้ามได้เพราะ:" in lower_line:
            current_box = layout_prefs["Warn"]
        elif "high-yield:" in lower_line or "trick:" in lower_line:
            current_box = layout_prefs["HY"]
        elif "quiz:" in lower_line or "เฉลย:" in lower_line:
            current_box = layout_prefs["Quiz"]
        
        boxes[current_box] += line + "\n"
        
    return {k: v.strip() for k, v in boxes.items()}

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

def apply_custom_tags(text):
    lines = text.split('\n')
    colors = ["#DC2626", "#2563EB", "#059669", "#7C3AED", "#EA580C", "#0891B2", "#DB2777"] 
    color_idx = 0
    in_high_yield = False
    new_lines = []
    
    for line in lines:
        if "High-Yield:" in line or "🚨 High-Yield" in line:
            in_high_yield = True
            color_idx = 0
        elif any(sec in line for sec in ["Quiz:", "Trick:", "การนำไปใช้ในคลินิก:", "ระวัง:", "กลไกและเหตุผล:", "Concept หลัก:", "Intro:", "เฉลย:", "ตัวอย่าง:", "ข้ามได้เพราะ:"]):
            in_high_yield = False
        
        if in_high_yield:
            if re.match(r'^(\s*[-*]\s|\s*\d+\.\s)', line) or line.strip().startswith("- key"):
                current_color = colors[color_idx % len(colors)]
                color_idx += 1
            else:
                idx_to_use = (color_idx - 1) if color_idx > 0 else 0
                current_color = colors[idx_to_use % len(colors)]
        else:
            current_color = "#DC2626" 
        
        line = re.sub(r'\*\*(.*?)\*\*', f"<strong style='color: {current_color}; font-weight: bold;'>\\1</strong>", line)
        new_lines.append(line)
        
    text = '\n'.join(new_lines)
    html = markdown.markdown(text, extensions=['tables'])
    
    replacements = [
        ("Intro:", "<div class='box-intro'><b style='color: #475569; font-size: 0.95em;'>🔗 เชื่อมโยงเนื้อหา (Intro)</b></div>"),
        ("<strong>Intro:</strong>", "<div class='box-intro'><b style='color: #475569; font-size: 0.95em;'>🔗 เชื่อมโยงเนื้อหา (Intro)</b></div>"),
        ("Concept หลัก:", "<div class='box-concept'><b style='color: #4338CA; font-size: 0.95em;'>🎯 Concept หลัก</b></div>"),
        ("<strong>Concept หลัก:</strong>", "<div class='box-concept'><b style='color: #4338CA; font-size: 0.95em;'>🎯 Concept หลัก</b></div>"),
        ("กลไกและเหตุผล:", "<div class='box-mech'><b style='color: #334155; font-size: 0.95em;'>⚙️ กลไกและเหตุผล</b></div>"),
        ("<strong>กลไกและเหตุผล:</strong>", "<div class='box-mech'><b style='color: #334155; font-size: 0.95em;'>⚙️ กลไกและเหตุผล</b></div>"),
        ("ตัวอย่าง:", "<div class='box-clinic'><b style='color: #0F766E; font-size: 0.95em;'>💡 ตัวอย่าง</b></div>"),
        ("<strong>ตัวอย่าง:</strong>", "<div class='box-clinic'><b style='color: #0F766E; font-size: 0.95em;'>💡 ตัวอย่าง</b></div>"),
        ("การนำไปใช้ในคลินิก:", "<div class='box-clinic'><b style='color: #0F766E; font-size: 0.95em;'>🩺 การนำไปใช้ในคลินิก</b></div>"),
        ("<strong>การนำไปใช้ในคลินิก:</strong>", "<div class='box-clinic'><b style='color: #0F766E; font-size: 0.95em;'>🩺 การนำไปใช้ในคลินิก</b></div>"),
        ("ระวัง:", "<div class='box-warn'><b style='color: #C2410C; font-size: 0.95em;'>⚠️ ระวัง / จุดล้าสมัย</b></div>"),
        ("<strong>ระวัง:</strong>", "<div class='box-warn'><b style='color: #C2410C; font-size: 0.95em;'>⚠️ ระวัง / จุดล้าสมัย</b></div>"),
        ("ข้ามได้เพราะ:", "<div class='box-warn'><b style='color: #C2410C; font-size: 0.95em;'>⏩ ข้ามได้เพราะ</b></div>"),
        ("<strong>ข้ามได้เพราะ:</strong>", "<div class='box-warn'><b style='color: #C2410C; font-size: 0.95em;'>⏩ ข้ามได้เพราะ</b></div>"),
        ("Trick:", "<div class='box-trick'><b style='color: #A16207; font-size: 0.95em;'>💡 Trick & Cross-ref</b></div>"),
        ("<strong>Trick:</strong>", "<div class='box-trick'><b style='color: #A16207; font-size: 0.95em;'>💡 Trick & Cross-ref</b></div>"),
        ("High-Yield:", "<div class='box-hy'><b style='color: #BE123C; font-size: 0.95em;'>🚨 High-Yield</b></div>"),
        ("<strong>High-Yield:</strong>", "<div class='box-hy'><b style='color: #BE123C; font-size: 0.95em;'>🚨 High-Yield</b></div>"),
        ("Quiz:", "<div class='box-quiz'><b style='color: #0369A1; font-size: 0.95em;'>📝 Quiz</b></div>"),
        ("<strong>Quiz:</strong>", "<div class='box-quiz'><b style='color: #0369A1; font-size: 0.95em;'>📝 Quiz</b></div>"),
        ("เฉลย:", "<div class='box-ans'><b style='color: #15803D; font-size: 0.95em;'>🎯 เฉลย</b></div>"),
        ("<strong>เฉลย:</strong>", "<div class='box-ans'><b style='color: #15803D; font-size: 0.95em;'>🎯 เฉลย</b></div>"),
    ]
    for old, new in replacements:
        html = html.replace(old, new).replace(f"<p>{new}</p>", new) 
    return html

# --- 4. Sidebar: Note Settings ---
with st.sidebar:
    st.markdown("<h2 style='color: #2D3748;'>🩺 Note Settings</h2>", unsafe_allow_html=True)
    is_locked = st.session_state.is_running
    
    api_input = st.text_input("🔑 ใส่ Gemini API Key:", type="password", value=st.session_state.user_api_key, disabled=is_locked)
    if api_input != st.session_state.user_api_key:
        st.session_state.user_api_key = api_input
        save_workspace()
        st.rerun()
        
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
                selected_display = st.selectbox("AI Model (สลับอัตโนมัติ):", display_options, index=0)
                st.session_state.current_active_model = model_map[selected_display]
        except: 
            st.error("API Key ไม่ถูกต้อง")

    st.markdown("### 💳 Token Tracker (จำลอง)")
    token_used = st.session_state.estimated_tokens_used
    st.progress(min(token_used / 1000000, 1.0)) 
    st.caption(f"ใช้ไปแล้ว: **{token_used:,} Tokens**")

    st.divider()
    med_year = st.selectbox("ระดับ นสพ.", [2, 3, 4, 5, 6], index=2, disabled=is_locked)
    max_tokens = st.number_input("กำหนด Max Output Tokens", min_value=100, max_value=8192, value=6000, step=500, disabled=is_locked)
    
    st.markdown("### 📐 จัดสรรพื้นที่กระดาษ (Layout)")
    margin_right_pct = st.slider("เพิ่มพื้นที่ด้านขวา (%)", 0, 100, 40, disabled=is_locked)
    margin_bottom_pct = st.slider("เพิ่มพื้นที่ด้านล่าง (%)", 0, 100, 50, disabled=is_locked)
    
    pos_options = ["ด้านขวา", "ด้านล่าง", "ด้านซ้าย", "ด้านบน"]
    st.markdown("### 📍 ตำแหน่งของแต่ละหัวข้อ")
    pos_intro = st.selectbox("วาง [Intro & Concept] ไว้ที่:", pos_options, index=0, disabled=is_locked)
    pos_mech = st.selectbox("วาง [กลไก, ตัวอย่าง, คลินิก] ไว้ที่:", pos_options, index=0, disabled=is_locked)
    pos_warn = st.selectbox("วาง [ระวัง / ข้ามได้เพราะ] ไว้ที่:", pos_options, index=0, disabled=is_locked)
    pos_hy = st.selectbox("วาง [High-Yield & Trick] ไว้ที่:", pos_options, index=1, disabled=is_locked) 
    pos_quiz = st.selectbox("วาง [Quiz & เฉลย] ไว้ที่:", pos_options, index=0, disabled=is_locked)
    
    st.markdown("### 📋 ข้อมูลที่ต้องการ (เปิด/ปิด ตามใจชอบ)")
    with st.expander("⚙️ ปรับแต่งหัวข้อในส่วน [เนื้อหาหลัก]", expanded=True):
        want_intro = st.checkbox("🔗 Intro (เชื่อมโยง + วัตถุประสงค์)", value=True, disabled=is_locked)
        want_concept = st.checkbox("🎯 Concept หลัก (ภาพรวม)", value=True, disabled=is_locked)
        want_mech = st.checkbox("⚙️ กลไกและเหตุผล (ห้ามจำแบบนกแก้ว)", value=True, disabled=is_locked)
        want_example = st.checkbox("💡 ยกตัวอย่างให้เห็นภาพ", value=True, disabled=is_locked)
        want_clinic = st.checkbox("🩺 การนำไปใช้ในคลินิก", value=True, disabled=is_locked)
        want_warn = st.checkbox("⚠️ ระวัง / ข้อมูลล้าสมัย", value=True, disabled=is_locked)

    want_summary = st.checkbox("🚨 สรุป High-Yield", value=True, disabled=is_locked)
    want_trick = st.checkbox("💡 ทริคจำ & การโยงข้อมูล (Cross-ref)", value=True, disabled=is_locked)
    want_quiz = st.checkbox("📝 Quiz", value=True, disabled=is_locked)
    
    quiz_count = 3
    want_answer = False
    if want_quiz:
        quiz_count = st.slider("จำนวนข้อ Quiz:", 1, 5, 3, disabled=is_locked)
        want_answer = st.checkbox("รวมเฉลย", value=True, disabled=is_locked)

    # 🌟 ระบบ Customize Prompt เนื้อหา
    st.markdown("### 🛠️ ปรับแต่ง Prompt เนื้อหาหลัก")
    use_custom_prompt = st.checkbox("เปิดใช้งานแก้ไข Prompt หลัก", value=st.session_state.use_custom_prompt, disabled=is_locked)
    
    base_prompt_template = f"""คุณคือรุ่นพี่แพทย์ที่กำลังติว นสพ. ปี {med_year} ตอบเป็นภาษาไทย
เป้าหมายของคุณคือ: อธิบายให้ **เข้าใจง่าย กระชับ** เหมือนรุ่นพี่อธิบายให้รุ่นน้องฟัง เพื่อให้เข้าใจจนจำได้นาน ไม่ใช่แค่การท่องจำ Pattern recognition เพราะสมองมนุษย์จำกัด ต้องเน้นการคิดเป็นเหตุเป็นผล

**บริบทเนื้อหาความเชื่อมโยงของสไลด์ (+/- 10 หน้า):**
{{global_context}}

**ข้อความ Text ดิบจากหน้าปัจจุบัน (เพื่อกันข้อมูลปริมาณ/ยา/ตารางตกหล่น):**
---
{{raw_text}}
---

**คำเตือนและข้อบังคับสำคัญ (ต้องทำตามอย่างเคร่งครัด):**
1. **ห้ามใช้คำทักทายเด็ดขาด** ให้เริ่มอธิบายเนื้อหาทันที เขียนชิดขอบซ้าย
2. **ต้องเน้นตัวหนาที่คำสำคัญ** เพื่อลดภาระสายตา
3. การอธิบายกลไก/อาการ/เหตุการณ์ **ต้องมีการให้เหตุผลโดยใช้คำว่า '...เพราะ...' เสมอ** ให้ผู้เรียนวาดภาพในหัวตามได้
4. หากพบข้อมูลในสไลด์ที่ล้าสมัย (Outdated) หรือผิดพลาดเมื่อเทียบกับ Guideline ปัจจุบัน ให้ทักท้วงในหัวข้อ 'ระวัง:' เสมอ
5. ⚠️ **กฎพิเศษสำหรับข้อสอบ:** ถ้าเนื้อหาในหน้านั้นเป็น "ข้อสอบ/คำถาม/โจทย์" ให้เปลี่ยนรูปแบบเป็น: [โจทย์ถามอะไร? -> ตอบข้อไหน? -> ทำไมข้อนี้ถูก? -> ทำไมข้ออื่นถึงผิด?] แล้วข้ามแพทเทิร์นปกติไปเลย
6. 🖼️ **รูปภาพและตาราง:** หากพบรูปภาพ กราฟ หรือตารางที่สำคัญในต้นฉบับ ให้พิมพ์คำว่า `[IMAGE_PLACEHOLDER]` แทรกไว้ตรงจุดนั้นเสมอ (ระบบจะนำภาพจริงมาแทรกให้)
7. หากเป็นหน้าว่างจริงๆ ให้ตอบแค่ 'NON_CONTENT'

{{strict_pattern}}"""

    if use_custom_prompt:
        custom_prompt_text = st.text_area("แก้ไข Prompt", value=st.session_state.custom_prompt_text if st.session_state.custom_prompt_text else base_prompt_template, height=300, disabled=is_locked)
        st.session_state.custom_prompt_text = custom_prompt_text
    else:
        st.session_state.custom_prompt_text = base_prompt_template
        
    st.session_state.use_custom_prompt = use_custom_prompt

    # 🌟 ระบบ Customize Prompt สำหรับ One-Sheet Summary
    st.markdown("### 📝 ปรับแต่ง Prompt สำหรับ One-Sheet")
    use_custom_summary_prompt = st.checkbox("เปิดใช้งานแก้ไข Prompt สำหรับ Summary", value=st.session_state.use_custom_summary_prompt, disabled=is_locked)
    default_summary_prompt_1 = f"สรุป High-yield สำหรับ นสพ.ปี {med_year} จัดรูปแบบมินิมอล **มีข้อมูลเปรียบเทียบให้ทำเป็น Markdown Table ทันที**:\nข้อมูลอ้างอิง:\n{{full_summaries}} เรียงเนื้อหาตามเอกสาร จัดเรียงหัวข้อหลัก ย่อย ให้ชัดเจน พร้อมใส่รายละเอียดในแต่ละหัวข้อด้วย"
    default_summary_prompt_2 = "สร้าง Clinical One-Sheet Summary แผ่นที่ 2 (เน้นการเจาะลึกโรคและการวินิจฉัย)\nจากข้อมูลอ้างอิง สกัดข้อมูลโรคสำคัญออกมา นำเสนอเป็นตาราง Markdown:\n1. โรค\n2. อาการเด่น\n3. เกณฑ์วินิจฉัย/Mnemonic\n4. Differential diagnosis\n5. Management/ยา\nข้อมูลอ้างอิง:\n{full_summaries}"

    if use_custom_summary_prompt:
        st.session_state.custom_summary_prompt_1 = st.text_area("Prompt แผ่นที่ 1", value=st.session_state.custom_summary_prompt_1 or default_summary_prompt_1, height=150, disabled=is_locked)
        st.session_state.custom_summary_prompt_2 = st.text_area("Prompt แผ่นที่ 2", value=st.session_state.custom_summary_prompt_2 or default_summary_prompt_2, height=150, disabled=is_locked)
    else:
        st.session_state.custom_summary_prompt_1 = default_summary_prompt_1
        st.session_state.custom_summary_prompt_2 = default_summary_prompt_2
    st.session_state.use_custom_summary_prompt = use_custom_summary_prompt

    if st.button("💾 บันทึกการตั้งค่า Prompt", use_container_width=True): save_workspace(); st.toast("บันทึกการตั้งค่าแล้ว!")

    current_settings = { "y": med_year, "mt": max_tokens, "mr": margin_right_pct, "mb": margin_bottom_pct, "wi": want_intro, "wc": want_concept, "wm": want_mech, "we": want_example, "wcl": want_clinic, "ww": want_warn, "ws": want_summary, "wt": want_trick, "wq": want_quiz, "qc": quiz_count, "wa": want_answer, "pi": pos_intro, "pm": pos_mech, "pw": pos_warn, "ph": pos_hy, "pq": pos_quiz }
    if not is_locked and st.session_state.last_settings and current_settings != st.session_state.last_settings:
        st.session_state.settings_changed_alert = True
    st.session_state.last_settings = current_settings

# --- 5. หน้าหลัก: การจัดการไฟล์ ---
st.markdown("<div class='main-header'>📚 PDF Note Space: Smart Clinical Reader</div>", unsafe_allow_html=True)

if not st.session_state.pdf_bytes:
    if os.path.exists("autosave_workspace.pkl"):
        st.info("💾 **พบงานที่ทำค้างไว้!**")
        if st.button("🔄 กู้คืนงานที่ทำค้างไว้", type="primary"):
            with st.spinner("กำลังโหลดข้อมูล..."):
                if load_workspace(): st.success("กู้คืนสำเร็จ!"); time.sleep(1); st.rerun()
                else: st.error("ไฟล์กู้คืนมีปัญหา")
    
    uploaded_file = st.file_uploader("อัปโหลดสไลด์อาจารย์ (PDF)", type="pdf")
    if uploaded_file:
        with st.status(f"กำลังนำเข้าไฟล์: {uploaded_file.name}...", expanded=True) as status:
            st.session_state.pdf_bytes = uploaded_file.getvalue()
            st.session_state.pdf_name = uploaded_file.name
            doc_tmp = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
            st.session_state.selected_pages = list(range(len(doc_tmp)))
            save_workspace()
            status.update(label=f"✅ อัปโหลดสำเร็จ", state="complete")
        st.rerun()
else:
    st.info(f"📄 ไฟล์ปัจจุบัน: **{st.session_state.pdf_name}**")
    if st.button("🗑️ เปลี่ยนเอกสาร (Reset)"): st.session_state.show_reset_confirm = True

    if st.session_state.show_reset_confirm:
        st.warning("ยืนยันการล้างข้อมูลทั้งหมด?")
        c1, c2 = st.columns(2)
        if c1.button("✅ ยืนยัน", type="primary"):
            clear_workspace() 
            for k in keys_to_init: del st.session_state[k]
            st.rerun()
        if c2.button("❌ ยกเลิก"): st.session_state.show_reset_confirm = False; st.rerun()

# --- 6. ระบบเลือกหน้า ---
if st.session_state.pdf_bytes and not is_locked:
    doc_in = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
    total_pages = len(doc_in)
    
    if "expander_open" not in st.session_state: st.session_state.expander_open = True
    if st.session_state.expander_open:
        with st.expander("🖼️ เลือกว่าจะให้ AI ประมวลผลหน้าไหนบ้าง", expanded=True):
            c_btn1, c_btn2, c_btn3 = st.columns([1,1,2])
            if c_btn1.button("✅ เลือกทั้งหมด"): st.session_state.selected_pages = list(range(total_pages)); st.rerun()
            if c_btn2.button("❌ ไม่เลือกเลย"): st.session_state.selected_pages = []; st.rerun()
            if c_btn3.button("💾 ยืนยันการเลือกหน้า", type="primary"): st.session_state.expander_open = False; save_workspace(); st.rerun()
            
            st.write("---")
            for row_idx in range(0, total_pages, 5):
                cols = st.columns(5)
                for col_idx in range(5):
                    page_num = row_idx + col_idx
                    if page_num < total_pages:
                        with cols[col_idx]:
                            page = doc_in[page_num]
                            st.image(page.get_pixmap(dpi=40).tobytes("png"), use_container_width=True) 
                            is_checked = st.checkbox(f"หน้า {page_num+1}", value=(page_num in st.session_state.selected_pages), key=f"sel_{page_num}")
                            if is_checked and page_num not in st.session_state.selected_pages: st.session_state.selected_pages.append(page_num)
                            elif not is_checked and page_num in st.session_state.selected_pages: st.session_state.selected_pages.remove(page_num)
    else:
        if st.button("⚙️ เปิดหน้าต่างเลือกหน้าอีกครั้ง"): st.session_state.expander_open = True; st.rerun()

# --- 7. แถบสถานะการประมวลผล ---
if st.session_state.pdf_bytes:
    doc_in = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
    total_pages = len(doc_in)
    
    if st.session_state.settings_changed_alert and not st.session_state.is_running:
        st.warning("🔔 ตรวจพบการเปลี่ยนการตั้งค่า: หน้าถัดไปจะใช้รูปแบบใหม่ทันที")
        if st.button("รับทราบ"): st.session_state.settings_changed_alert = False

    if st.session_state.show_start_popup:
        with st.container():
            st.markdown("### 📊 สรุปข้อมูลก่อนเริ่มสร้างเอกสาร")
            pages_to_do = len([i for i in st.session_state.selected_pages if i not in st.session_state.processed_data])
            st.info(f"- หน้าที่ต้องประมวลผลเพิ่ม: **{pages_to_do} หน้า**\n- คาดการณ์ Token: **~{pages_to_do * max_tokens:,} Tokens**")
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
    st.subheader(f"📖 Clinical E-Book: หน้า {st.session_state.page_idx + 1}")
    
    c_nav1, c_nav2, c_nav3 = st.columns([1, 2, 1])
    with c_nav1:
        if st.button("⬅️ หน้าก่อนหน้า") and st.session_state.page_idx > 0: st.session_state.page_idx -= 1; st.rerun()
    with c_nav2:
        new_page = st.slider("กระโดดไปหน้า:", 1, total_pages, st.session_state.page_idx + 1, label_visibility="collapsed")
        if new_page - 1 != st.session_state.page_idx: st.session_state.page_idx = new_page - 1; st.rerun()
    with c_nav3:
        if st.button("หน้าถัดไป ➡️") and st.session_state.page_idx < total_pages - 1: st.session_state.page_idx += 1; st.rerun()

    curr = st.session_state.page_idx
    if curr in st.session_state.processed_data:
        data = st.session_state.processed_data[curr]
        col_v1, col_v2 = st.columns([1.2, 1])
        with col_v1: 
            st.image(data["img"], use_container_width=True)
            # โชว์รูปภาพที่สกัดไว้ด้วยเผื่อผู้ใช้เทียบเคียง
            ext_imgs = data.get("extracted_images", [])
            if ext_imgs:
                with st.expander(f"🖼️ ดูรูปที่สกัดมาได้จากหน้านี้ ({len(ext_imgs)} รูป)"):
                    for img_bytes in ext_imgs: st.image(img_bytes, use_container_width=True)
        with col_v2:
            st.markdown("### 📝 บันทึกการเรียน")
            if f"editing_{curr}" not in st.session_state: st.session_state[f"editing_{curr}"] = False
            display_text = data["user_text"] if data["user_text"] else data["ai_text"]
            
            if st.session_state[f"editing_{curr}"]:
                edited = st.text_area("แก้ไขเนื้อหา:", value=display_text, height=400)
                ce1, ce2 = st.columns(2)
                if ce1.button("💾 ยืนยันการแก้ไข", type="primary"):
                    st.session_state.processed_data[curr]["user_text"] = edited; st.session_state[f"editing_{curr}"] = False; save_workspace(); st.rerun()
                if ce2.button("🔄 คืนค่าต้นฉบับ AI"):
                    st.session_state.processed_data[curr]["user_text"] = ""; st.session_state[f"editing_{curr}"] = False; save_workspace(); st.rerun()
            else:
                st.markdown(f"<div class='edit-box'>{apply_custom_tags(display_text)}</div>", unsafe_allow_html=True)
                if st.button("✏️ พิมพ์แก้ไขเนื้อหานี้"):
                    st.session_state[f"editing_{curr}"] = True
                    if st.session_state.is_running: st.session_state.is_running = False; st.warning("⚠️ หยุดรันชั่วคราวให้แก้ไข กด Continue เพื่อรันต่อ")
                    st.rerun()
    else:
        st.info(f"⏳ หน้าที่ {curr+1} ยังไม่ได้ประมวลผล...")

    # --- 9. Export PDF & Master Review ---
    st.write("---")
    if len(st.session_state.processed_data) > 0:
        if st.button("📦 รวบรวมและเตรียมดาวน์โหลด PDF (มี Master Review ให้อ่านทวนตอนท้าย)"):
            with st.spinner("กำลังประกอบร่างไฟล์ PDF ฉบับสมบูรณ์ (อาจใช้เวลาสักครู่เนื่องจากดึงรูปและต่อข้อมูล)..."):
                doc_out = fitz.open()
                arch_path = "."
                layout_prefs = { "Intro": pos_intro, "Mech": pos_mech, "Warn": pos_warn, "HY": pos_hy, "Quiz": pos_quiz }
                all_temp_files = [] # เก็บรายชื่อไฟล์รูปชั่วคราวเพื่อลบตอนจบ
                
                # --- ส่วนที่ 1: สไลด์ต้นฉบับ + Margin Notes ---
                for i in range(total_pages):
                    p_in = doc_in[i]; w, h = p_in.rect.width, p_in.rect.height
                    new_w, new_h = w * (1 + margin_right_pct/100), max(h, h * (1 + margin_bottom_pct/100))
                    p_out = doc_out.new_page(width=new_w, height=new_h)
                    p_out.show_pdf_page(fitz.Rect(0, 0, w, h), doc_in, i)
                    
                    bg_color = (0.97, 0.98, 0.99)
                    if margin_right_pct > 0: p_out.draw_rect(fitz.Rect(w, 0, new_w, new_h), color=bg_color, fill=bg_color, width=0)
                    if margin_bottom_pct > 0: p_out.draw_rect(fitz.Rect(0, h, w, new_h), color=bg_color, fill=bg_color, width=0)
                    
                    # 🔥 วาดกล่อง Layout ใหม่ (รูปตัว L-Shape มุมขวาล่างไม่แหว่ง)
                    rects = {
                        "ด้านขวา": fitz.Rect(w + 10, 10, new_w - 10, new_h - 10), # ลากยาวสุดขอบกระดาษใหม่!
                        "ด้านล่าง": fitz.Rect(10, h + 10, w - 10, new_h - 10), # กล่องล่างไม่ให้กวนกับกล่องขวา
                        "ด้านซ้าย": fitz.Rect(10, 10, (w * margin_right_pct/100) - 10, h - 10), 
                        "ด้านบน": fitz.Rect(10, 10, w - 10, (h * margin_bottom_pct/100) - 10) 
                    }
                    
                    if i in st.session_state.processed_data:
                        data = st.session_state.processed_data[i]
                        raw_txt = data["user_text"] or data["ai_text"]
                        images = data.get("extracted_images", [])
                        
                        if raw_txt and "⚠️" not in raw_txt:
                            raw_txt = re.sub(r'^[•\-\*]\s*$', '', raw_txt, flags=re.MULTILINE)
                            
                            # เตรียม Placeholder สำหรับฝั่ง Margin (รูปเล็ก)
                            html_parts = raw_txt.split("[IMAGE_PLACEHOLDER]")
                            processed_ai_text = ""
                            for idx, part in enumerate(html_parts):
                                processed_ai_text += part
                                if idx < len(html_parts) - 1 and idx < len(images):
                                    tmp_filename = f"tmp_export_margin_img_p{i}_{idx}.png"
                                    try:
                                        with open(tmp_filename, "wb") as f: f.write(images[idx])
                                        all_temp_files.append(tmp_filename)
                                        processed_ai_text += f"\n\n<div style='text-align:center;'><img src='{tmp_filename}' style='max-width: 90%; border: 1px solid #ccc; margin: 5px 0;'></div>\n\n"
                                    except: pass

                            box_contents = distribute_content(processed_ai_text, layout_prefs)
                            
                            for pos, text_chunk in box_contents.items():
                                if not text_chunk.strip(): continue
                                box = rects[pos]
                                html = apply_custom_tags(text_chunk)
                                f_size = calc_dynamic_fontsize(html, box.width, box.height)
                                css = f"@font-face {{ font-family: 'T'; src: url('THSarabunNew.ttf'); }} @font-face {{ font-family: 'T'; font-weight: bold; src: url('THSarabunNew Bold.ttf'); }} body {{ font-family: 'T'; font-size: {f_size}px; line-height: 1.5; color: #0F172A; margin: 0; padding: 0; }} b, strong {{ font-weight: bold; }} .box-intro, .box-concept, .box-mech, .box-clinic, .box-warn, .box-trick, .box-hy, .box-quiz, .box-ans {{ padding: 2px 8px; margin: 6px 0 4px 0; }} .box-intro{{background:#F8FAFC;border-left:3px solid #94A3B8;}} .box-concept{{background:#EEF2FF;border-left:3px solid #6366F1;}} .box-mech{{background:#F1F5F9;border-left:3px solid #475569;}} .box-clinic{{background:#F0FDFA;border-left:3px solid #14B8A6;}} .box-warn{{background:#FFF7ED;border-left:3px solid #F97316;}} .box-trick{{background:#FEF9C3;border-left:3px solid #EAB308;}} .box-hy{{background:#FFF1F2;border-left:3px solid #F43F5E;}} .box-quiz{{background:#F0F9FF;border-left:3px solid #0EA5E9;}} .box-ans{{background:#F0FDF4;border-left:3px solid #22C55E;}} table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }} th {{ background: #F8FAFC; border: 1px solid #CBD5E1; padding: 6px; text-align: left; }} td {{ border: 1px solid #E2E8F0; padding: 6px; }} ul, ol {{ margin: 8px 0; padding-left: 20px; }} li {{ margin-bottom: 8px; }}"
                                try: p_out.insert_htmlbox(box, f"<style>{css}</style><body>{html}</body>", archive=fitz.Archive(arch_path))
                                except: p_out.insert_textbox(box, text_chunk, fontsize=f_size)
                
                # --- ส่วนที่ 2: Master Review (หน้าสรุปรวบยอดท้ายเล่ม) ---
                p_divider = doc_out.new_page(width=595, height=842) # A4 Size
                p_divider.insert_text(fitz.Point(120, 400), "📘 MASTER REVIEW SECTION", fontsize=28, color=(0.06,0.09,0.17))
                
                for i in range(total_pages):
                    if i in st.session_state.processed_data and i in st.session_state.selected_pages:
                        data = st.session_state.processed_data[i]
                        ai_text = data["user_text"] or data["ai_text"]
                        images = data.get("extracted_images", [])
                        
                        if ai_text and "⚠️" not in ai_text:
                            html_parts = ai_text.split("[IMAGE_PLACEHOLDER]")
                            review_html = ""
                            
                            for idx, part in enumerate(html_parts):
                                review_html += part
                                if idx < len(html_parts) - 1 and idx < len(images):
                                    tmp_filename = f"tmp_export_review_img_p{i}_{idx}.png"
                                    try:
                                        with open(tmp_filename, "wb") as f: f.write(images[idx])
                                        all_temp_files.append(tmp_filename)
                                        # รูปในหน้ารีวิวจะใหญ่ขึ้น มองเห็นชัดเจน
                                        review_html += f"\n\n<div style='text-align:center;'><img src='{tmp_filename}' style='max-width: 80%; max-height: 250px; border-radius: 8px; border: 2px solid #CBD5E1; margin: 15px 0; box-shadow: 0 4px 6px rgba(0,0,0,0.1);'></div>\n\n"
                                    except: pass
                            
                            review_html = apply_custom_tags(review_html)
                            
                            p_rev = doc_out.new_page(width=595, height=842)
                            f_size_rev = calc_dynamic_fontsize(review_html, 515, 762)
                            css_rev = f"@font-face {{ font-family: 'T'; src: url('THSarabunNew.ttf'); }} @font-face {{ font-family: 'T'; font-weight: bold; src: url('THSarabunNew Bold.ttf'); }} body {{ font-family: 'T'; font-size: {f_size_rev}px; line-height: 1.5; color: #1E293B; }} h2 {{ text-align: center; border-bottom: 2px solid #3B82F6; color: #0F172A; padding-bottom: 5px;}} b, strong {{ font-weight: bold; background-color: #FEF9C3; padding: 0 4px; border-radius: 4px; }} .box-intro, .box-concept, .box-mech, .box-clinic, .box-warn, .box-trick, .box-hy, .box-quiz, .box-ans {{ padding: 2px 8px; margin: 8px 0; }} .box-intro{{background:#F8FAFC;border-left:4px solid #94A3B8;}} .box-concept{{background:#EEF2FF;border-left:4px solid #6366F1;}} .box-mech{{background:#F1F5F9;border-left:4px solid #475569;}} .box-clinic{{background:#F0FDFA;border-left:4px solid #14B8A6;}} .box-warn{{background:#FFF7ED;border-left:4px solid #F97316;}} .box-trick{{background:#FEF9C3;border-left:4px solid #EAB308;}} .box-hy{{background:#FFF1F2;border-left:4px solid #F43F5E;}} .box-quiz{{background:#F0F9FF;border-left:4px solid #0EA5E9;}} table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }} th {{ background: #F1F5F9; border: 1px solid #CBD5E1; padding: 8px; }} td {{ border: 1px solid #E2E8F0; padding: 8px; }}"
                            p_rev.insert_htmlbox(fitz.Rect(40,40,555,802), f"<style>{css_rev}</style><body><h2>📖 สรุปเนื้อหาหน้า {i+1}</h2>{review_html}</body>", archive=fitz.Archive(arch_path))
                            
                # --- ส่วนที่ 3: One-Sheet Summary (จบปิ๊ง) ---
                if st.session_state.full_summaries:
                    model_os = genai.GenerativeModel(get_best_available_model(st.session_state.flash_models_list) or "gemini-3.1-flash-lite")
                    safety = { HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE }
                    data_chunk = st.session_state.full_summaries[:30000]
                    
                    try: os_res_1 = model_os.generate_content(st.session_state.custom_summary_prompt_1.replace("{full_summaries}", data_chunk), safety_settings=safety); os_html_1 = markdown.markdown(os_res_1.text, extensions=['tables'])
                    except: os_html_1 = "Summary 1 ไม่พร้อม"
                    p_os_1 = doc_out.new_page(width=595, height=842)
                    css_os = f"@font-face {{ font-family: 'T'; src: url('THSarabunNew.ttf'); }} @font-face {{ font-family: 'T'; font-weight: bold; src: url('THSarabunNew Bold.ttf'); }} body {{ font-family: 'T'; font-size: {calc_dynamic_fontsize(os_html_1, 515, 762)}px; color: #334155; }} h2 {{ text-align: center; border-bottom: 2px solid #0EA5E9; color: #0F172A; padding-bottom: 5px;}} table {{ width: 100%; border-collapse: collapse; margin: 10px 0;}} th, td {{ border: 1px solid #E2E8F0; padding: 6px; }} th {{ background-color: #F8FAFC; color: #0F172A; font-weight: bold; text-align: center; }}"
                    p_os_1.insert_htmlbox(fitz.Rect(40,40,555,802), f"<style>{css_os}</style><body><h2>⭐ CLINICAL ONE-SHEET (OVERVIEW) ⭐</h2>{os_html_1}</body>", archive=fitz.Archive(arch_path))

                    try: os_res_2 = model_os.generate_content(st.session_state.custom_summary_prompt_2.replace("{full_summaries}", data_chunk), safety_settings=safety); os_html_2 = markdown.markdown(os_res_2.text, extensions=['tables'])
                    except: os_html_2 = "Summary 2 ไม่พร้อม"
                    p_os_2 = doc_out.new_page(width=595, height=842)
                    css_os_2 = f"@font-face {{ font-family: 'T'; src: url('THSarabunNew.ttf'); }} @font-face {{ font-family: 'T'; font-weight: bold; src: url('THSarabunNew Bold.ttf'); }} body {{ font-family: 'T'; font-size: {calc_dynamic_fontsize(os_html_2, 515, 762)}px; color: #334155; }} h2 {{ text-align: center; border-bottom: 2px solid #14B8A6; color: #0F172A; padding-bottom: 5px;}} table {{ width: 100%; border-collapse: collapse; margin: 10px 0;}} th, td {{ border: 1px solid #E2E8F0; padding: 6px; }} th {{ background-color: #F0FDFA; color: #0F766E; font-weight: bold; text-align: center; }}"
                    p_os_2.insert_htmlbox(fitz.Rect(40,40,555,802), f"<style>{css_os_2}</style><body><h2>⭐ CLINICAL ONE-SHEET (DISEASE FOCUS) ⭐</h2>{os_html_2}</body>", archive=fitz.Archive(arch_path))

                # ล้างไฟล์รูปขยะทิ้ง
                for tmp_file in all_temp_files:
                    try: os.remove(tmp_file)
                    except: pass
                    
                st.session_state.base_pdf_doc_bytes = doc_out.tobytes()
                st.session_state.show_download_modal = True

        if st.session_state.get('show_download_modal') and st.session_state.get('base_pdf_doc_bytes'):
            st.markdown("""<div style="border: 2px solid #3182CE; border-radius: 12px; padding: 25px; background-color: #F8FAFC; margin-top: 15px;">
                <h3 style="color: #2B6CB0; margin-top: 0;">🗜️ ตั้งค่าการบีบอัดไฟล์ PDF</h3>""", unsafe_allow_html=True)
            
            raw_bytes = st.session_state.base_pdf_doc_bytes
            temp_doc = fitz.open(stream=raw_bytes, filetype="pdf")
            orig_size_mb = len(raw_bytes) / (1024 * 1024)
            st.markdown(f"📁 ขนาดต้นฉบับก่อนบีบอัด: **{orig_size_mb:.2f} MB**")
            
            comp_choice = st.radio("เลือกระดับการบีบอัด:", ["2. บีบอัดที่แนะนำ (สมดุลที่สุด)", "1. บีบอัดขั้นสุด (เล็กที่สุด)", "3. บีบอัดนิดหน่อย (คุณภาพภาพเดิม)"])
            with st.spinner("กำลังคำนวณ..."):
                if "ขั้นสุด" in comp_choice: final_bytes = temp_doc.tobytes(garbage=4, deflate=True, clean=True)
                elif "แนะนำ" in comp_choice: final_bytes = temp_doc.tobytes(garbage=3, deflate=True)
                else: final_bytes = temp_doc.tobytes(garbage=1, deflate=True)
                final_size_mb = len(final_bytes) / (1024 * 1024)

            st.markdown(f"📉 หลังบีบอัด: <strong style='color: #E53E3E; font-size: 1.4em;'>{final_size_mb:.2f} MB</strong> (ประหยัด **{orig_size_mb - final_size_mb:.2f} MB**)", unsafe_allow_html=True)
            st.download_button("💾 คลิกดาวน์โหลดไฟล์ PDF", data=final_bytes, file_name=f"MasterNote_{st.session_state.pdf_name}", mime="application/pdf", type="primary")
            if st.button("❌ ปิดหน้าต่างนี้"): st.session_state.show_download_modal = False; st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    # --- 10. ระบบประมวลผล (2-Phase) ---
    if st.session_state.is_running and not st.session_state.stop_clicked:
        active_m = st.session_state.current_active_model
        model = genai.GenerativeModel(active_m)
        config = GenerationConfig(max_output_tokens=max_tokens)
        safety = { HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE }

        # --- PHASE 1: GLOBAL SCAN (Triage Priority) ---
        if st.session_state.phase == 'global_scan':
            target_global = next((i for i in st.session_state.selected_pages if i not in st.session_state.global_data), None)
            
            if target_global is None:
                st.session_state.phase = 'detail_scan'; save_workspace(); st.rerun()
            else:
                action_placeholder.markdown(f"<div class='status-purple'><b>🔍 [Phase 1/2] ประเมิน Triage ความสำคัญ (หน้า {target_global+1}/{total_pages})</b></div>", unsafe_allow_html=True)
                img = Image.open(io.BytesIO(doc_in[target_global].get_pixmap(dpi=50).tobytes("png")))
                
                prompt_global = """วิเคราะห์สไลด์หน้านี้อย่างรวดเร็ว ตอบกลับตามรูปแบบนี้เท่านั้น (ห้ามมีคำอื่น):
                TOPIC: (ชื่อหัวข้อเรื่องของหน้านี้ สั้นๆ 1-3 คำ)
                SUMMARY: (สรุปใจความสำคัญของหน้านี้สั้นๆ 1 ประโยค)
                PRIORITY: (ประเมินเป็น HIGH, MEDIUM หรือ LOW)
                - HIGH = กลไกโรค(Patho), วินิจฉัย, รักษา, ข้อบ่งชี้
                - MEDIUM = ระบาดวิทยา, อาการทั่วไป
                - LOW = ประวัติศาสตร์, วัตถุประสงค์ (Objective), หน้าว่างคั่นบท, รูปภาพประกอบที่ไม่มีเนื้อหาสำคัญ"""
                
                try:
                    resp = model.generate_content([prompt_global, img], safety_settings=safety, generation_config=GenerationConfig(max_output_tokens=150))
                    text = resp.text.strip()
                    st.session_state.estimated_tokens_used += len(text)
                    
                    topic = text.split("TOPIC:")[1].split("SUMMARY:")[0].strip() if "TOPIC:" in text else f"หัวข้อหน้า {target_global+1}"
                    summary_raw = text.split("SUMMARY:")[1] if "SUMMARY:" in text else "ข้อมูลสไลด์"
                    if "PRIORITY:" in summary_raw:
                        summary = summary_raw.split("PRIORITY:")[0].strip()
                        priority = summary_raw.split("PRIORITY:")[1].strip().upper()
                    else:
                        summary, priority = summary_raw.strip(), "MEDIUM"
                        
                    st.session_state.global_data[target_global] = {'topic': topic, 'summary': summary, 'priority': priority}
                    save_workspace() 
                except:
                    st.session_state.global_data[target_global] = {'topic': f"หน้า {target_global+1}", 'summary': "", 'priority': 'MEDIUM'}
                time.sleep(0.1); st.rerun()

        # --- PHASE 2: DETAIL SCAN ---
        elif st.session_state.phase == 'detail_scan':
            target = next((i for i in range(total_pages) if i in st.session_state.processed_data and "⚠️" in st.session_state.processed_data[i].get("ai_text", "")), None)
            is_recheck = target is not None
            if target is None: target = next((i for i in range(total_pages) if i not in st.session_state.processed_data), None)

            if target is not None:
                if target not in st.session_state.selected_pages:
                    st.session_state.processed_data[target] = {"ai_text": "", "user_text": "", "img": doc_in[target].get_pixmap(dpi=50).tobytes("png")}; st.rerun()

                st.session_state.status_mode = 'yellow' if is_recheck else 'blue'
                msg = f"🔄 ซ่อมหน้าที่ Error (หน้า {target+1})" if is_recheck else f"⚡ ลงรายละเอียดหน้าที่ {target+1} / {total_pages}"
                action_placeholder.markdown(f"<div class='status-{st.session_state.status_mode}'><b>{msg}</b><br>🤖 วิเคราะห์ด้วย Context Window และอ่านภาพ | <code>{active_m}</code></div>", unsafe_allow_html=True)
                
                # 1. ดึงภาพดิบ และดึงภาพย่อย
                p_img = doc_in[target].get_pixmap(dpi=75)
                img = Image.open(io.BytesIO(p_img.tobytes("png")))
                extracted_images = extract_images_from_page(doc_in, target)
                raw_text = doc_in[target].get_text() # สกัด text ดิบกันข้อมูลตกหล่น

                # 2. สร้าง Context Window (+/- 10 หน้า)
                start_idx, end_idx = max(0, target - 10), min(total_pages, target + 11)
                local_context_lines = []
                for idx in range(start_idx, end_idx):
                    if idx in st.session_state.global_data:
                        g_info = st.session_state.global_data[idx]
                        prefix = "👉 [หน้านี้กำลังแปล]" if idx == target else "-"
                        local_context_lines.append(f"{prefix} หน้า {idx+1} ({g_info['topic']}): {g_info['summary']} [Priority: {g_info.get('priority','MEDIUM')}]")
                local_context_text = "\n".join(local_context_lines)

                # 3. Triage & Pattern Building สำหรับ Margin Note
                page_priority = st.session_state.global_data.get(target, {}).get('priority', 'MEDIUM')
                pattern_parts = []
                
                if "LOW" in page_priority:
                    strict_pattern = (
                        "🚨 **หน้าเกริ่นนำ / น้ำเยอะ (Low Priority)**\n\n"
                        "Concept หลัก: (สรุปสั้นๆ 1-2 ประโยคว่าสไลด์นี้ต้องการสื่ออะไร)\n\n"
                        "ข้ามได้เพราะ: (บอกเหตุผลตรงๆ ว่าทำไมถึงไม่ต้องอ่านละเอียด **ต้องใช้คำว่า '...เพราะ...' เสมอ**)\n"
                    )
                else:
                    content_instruction = "เนื้อหาหลัก:\n"
                    if want_intro: content_instruction += "Intro: (วิเคราะห์บริบท +/- 10 หน้า อธิบายสั้นๆ ว่าผู้เขียนสไลด์มีวัตถุประสงค์อะไร และเนื้อหาเชื่อมโยงกับหน้าก่อนอย่างไร)\n\n"
                    if want_concept: content_instruction += "Concept หลัก: (สรุปเป้าหมายของหน้านี้ภาษาที่เข้าใจง่ายสุดๆ)\n\n"
                    if want_mech: content_instruction += "กลไกและเหตุผล: (อธิบายเหตุผล ที่มาที่ไป **ต้องใช้คำว่า '...เพราะ...' เสมอ** ให้คิดเป็นเหตุเป็นผลเป็นภาพ)\n\n"
                    if want_example: content_instruction += "ตัวอย่าง: (ยกตัวอย่างสถานการณ์จริง หรือเปรียบเทียบให้เห็นภาพชัดเจน)\n\n"
                    if want_clinic: content_instruction += "การนำไปใช้ในคลินิก: (จุดเชื่อมโยงนำไปใช้จริงบนวอร์ด)\n\n"
                    if want_warn: content_instruction += "ระวัง: (จุดสับสน หรือ **หากสไลด์ผิด/ล้าสมัย ให้แจ้งเตือนพร้อมบอกข้อมูลที่อัปเดตกว่าทันที**)\n\n"
                    
                    if any([want_intro, want_concept, want_mech, want_example, want_clinic, want_warn]): pattern_parts.append(content_instruction)
                    if want_summary: pattern_parts.append("High-Yield:\n- KEY1: **(คีย์เวิร์ด)** (ประโยคกระชับ เข้าใจทันที)\n- KEY2: **(คีย์เวิร์ด)** (ประโยคกระชับ)")
                    if want_trick: pattern_parts.append("Trick: (ทริคการจำ, การสร้าง Cross-reference เชื่อมโยงกับเรื่องอื่นเพื่อใช้ดึงความจำตอนลืม **ระบุชัดเจนว่าจุดไหนคือจุดที่ต้องจำให้ครบ**)")
                    if want_quiz: 
                        q_sec = f"Quiz:\nQ1: (คำถามทบทวนความจำ)" + (f"\n\nQ2: (คำถาม)" if quiz_count >= 2 else "")
                        if want_answer: q_sec += f"\n\nเฉลย:\nA1: (เฉลยสั้นๆ)" + (f"\n\nA2: (เฉลยสั้นๆ)" if quiz_count >= 2 else "")
                        pattern_parts.append(q_sec)
                    
                    strict_pattern = "\n\n".join(pattern_parts)

                prompt = st.session_state.custom_prompt_text.replace("{global_context}", local_context_text).replace("{strict_pattern}", strict_pattern).replace("{current_page}", str(target+1)).replace("{total_pages}", str(total_pages)).replace("{raw_text}", raw_text)
                
                is_success, retry_count = False, 0
                while retry_count < 2 and not is_success:
                    try:
                        resp = model.generate_content([prompt, img], safety_settings=safety, generation_config=config)
                        final_text = resp.text.strip()
                        st.session_state.estimated_tokens_used += len(final_text) 
                        
                        if "NON_CONTENT" in final_text: 
                            main_text = ""
                        else:
                            main_text = final_text
                            
                            # เก็บสะสมข้อมูลทำ One-Sheet หน้าสุดท้าย
                            if want_summary and "High-Yield:" in main_text and "LOW" not in page_priority:
                                st.session_state.full_summaries += f"\n[Page {target+1}] " + main_text.split("High-Yield:")[-1].split("Quiz:")[0]
                        
                        is_success = True
                        st.session_state.processed_data[target] = {
                            "ai_text": main_text, 
                            "user_text": "", 
                            "img": p_img.tobytes("png"), 
                            "extracted_images": extracted_images, 
                            "raw_text": raw_text
                        }
                        save_workspace() 
                    except Exception as e:
                        if "429" in str(e) or "Quota" in str(e):
                            st.session_state.exhausted_models[active_m] = time.time() + 60
                            action_placeholder.markdown(f"<div class='status-yellow'><b>⚠️ คิวเต็ม! กำลังหาโมเดลสำรอง...</b></div>", unsafe_allow_html=True); time.sleep(2)
                            new_model = get_best_available_model(st.session_state.flash_models_list)
                            if new_model: active_m = st.session_state.current_active_model = new_model; model = genai.GenerativeModel(new_model); retry_count += 1
                            else: 
                                st.session_state.processed_data[target] = {"ai_text": "⚠️ โควต้าเต็มทุกโมเดล กด Pause รอ 1 นาที", "user_text": "", "img": p_img.tobytes("png")}; is_success = True
                        elif "400" in str(e):
                            st.session_state.exhausted_models[active_m] = time.time() + 86400 
                            st.session_state.processed_data[target] = {"ai_text": f"⚠️ โมเดลถูกแบนชั่วคราว รอระบบสลับโมเดล", "user_text": "", "img": p_img.tobytes("png")}; is_success = True
                        else:
                            st.session_state.processed_data[target] = {"ai_text": f"⚠️ Error: {str(e)}", "user_text": "", "img": p_img.tobytes("png")}; is_success = True
                time.sleep(0.1); st.rerun()
            else:
                st.session_state.is_running, st.session_state.phase = False, 'idle'
                action_placeholder.markdown(f"<div class='status-blue' style='border-left-color: #38A169; color: #2F855A; background: #F0FFF4;'><b>✅ ประมวลผลเสร็จสิ้น!</b></div>", unsafe_allow_html=True)
