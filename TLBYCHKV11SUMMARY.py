import streamlit as st
import fitz  # PyMuPDF
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold, GenerationConfig
from PIL import Image
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
    
    # --- ตัวแปรสำหรับระบบ Global Context ---
    'phase': 'idle', # idle, global_scan, detail_scan
    'global_data': {}, # เก็บ {'topic': '', 'summary': ''} ของแต่ละหน้า
    'global_context_text': "", # ข้อความภาพรวมทั้งหมดที่รวมร่างแล้ว
    
    # --- ตัวแปรสำหรับ Custom Prompt เนื้อหา ---
    'use_custom_prompt': False,
    'custom_prompt_text': "",
    
    # --- ตัวแปรสำหรับ Custom Prompt Summary (4 แผ่นเรียงสไลด์ + 1 แผ่น Master Table) ---
    'use_custom_summary_prompt': False,
    'custom_summary_prompt_1': "",
    'custom_summary_prompt_2': "",
    'custom_summary_prompt_3': "",
    'custom_summary_prompt_4': "",
    'custom_summary_prompt_5': "", # Master Clinical Table
    
    # --- ตัวแปรสำหรับระบบบีบอัดไฟล์ PDF ---
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
    /* 🌟 นำเข้าฟอนต์ Sarabun จาก Google Fonts */
    @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');
    
    html, body, [class*="st-"] {
        font-family: 'Sarabun', sans-serif !important;
    }

    .stApp { background-color: #F8FAFC; }
    .main-header { font-size: 2.2rem; font-weight: 800; color: #0F172A; margin-bottom: 1rem; letter-spacing: -0.5px; }
    .stButton>button { border-radius: 8px; transition: all 0.3s; font-weight: 600; font-family: 'Sarabun', sans-serif !important; }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
    
    /* 🌟 Minimalist Edit Box */
    .edit-box { 
        border: 1px solid #F1F5F9; 
        border-radius: 16px; 
        padding: 24px; 
        background: #FFFFFF; 
        font-size: 17px; 
        line-height: 1.8;
        color: #334155;
        box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.04);
    }
    
    .edit-box strong, .edit-box b { color: #0F172A; font-weight: 700; }
    
    .box-intro { background-color: #F8FAFC; border-left: 4px solid #94A3B8; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.02); }
    .box-concept { background-color: #EEF2FF; border-left: 4px solid #6366F1; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.02); }
    .box-mech { background-color: #F1F5F9; border-left: 4px solid #475569; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.02); }
    .box-clinic { background-color: #F0FDFA; border-left: 4px solid #14B8A6; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.02); }
    .box-warn { background-color: #FFF7ED; border-left: 4px solid #F97316; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.02); }
    .box-trick { background-color: #FEF9C3; border-left: 4px solid #EAB308; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.02); }
    .box-hy { background-color: #FFF1F2; border-left: 4px solid #F43F5E; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.02); }
    .box-quiz { background-color: #F0F9FF; border-left: 4px solid #0EA5E9; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.02); }
    .box-ans { background-color: #F0FDF4; border-left: 4px solid #22C55E; padding: 4px 12px; margin: 10px 0 4px 0; border-radius: 0 4px 4px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.02); }
    
    .box-hy strong, .box-hy b { font-weight: 700; }
    
    .edit-box ul, .edit-box ol { margin-top: 0.5rem; margin-bottom: 1rem; padding-left: 1.5rem; }
    .edit-box li { margin-bottom: 12px; }
    .edit-box p { margin-bottom: 12px; }
    
    .edit-box table { width: 100%; border-collapse: collapse; margin: 20px 0; border-radius: 8px; overflow: hidden; font-size: 16px; }
    .edit-box th { background-color: #F8FAFC; padding: 12px; border-bottom: 2px solid #E2E8F0; color: #475569; text-align: left; }
    .edit-box td { padding: 12px; border-bottom: 1px solid #F1F5F9; }
    
    @keyframes pulse-blue { 0% { box-shadow: 0 0 0 0 rgba(49, 130, 206, 0.4); } 70% { box-shadow: 0 0 0 10px rgba(49, 130, 206, 0); } 100% { box-shadow: 0 0 0 0 rgba(49, 130, 206, 0); } }
    @keyframes pulse-yellow { 0% { box-shadow: 0 0 0 0 rgba(214, 158, 46, 0.4); } 70% { box-shadow: 0 0 0 10px rgba(214, 158, 46, 0); } 100% { box-shadow: 0 0 0 0 rgba(214, 158, 46, 0); } }
    @keyframes pulse-red { 0% { box-shadow: 0 0 0 0 rgba(229, 62, 62, 0.4); } 70% { box-shadow: 0 0 0 10px rgba(229, 62, 62, 0); } 100% { box-shadow: 0 0 0 0 rgba(229, 62, 62, 0); } }
    @keyframes pulse-purple { 0% { box-shadow: 0 0 0 0 rgba(128, 90, 213, 0.4); } 70% { box-shadow: 0 0 0 10px rgba(128, 90, 213, 0); } 100% { box-shadow: 0 0 0 0 rgba(128, 90, 213, 0); } }
    
    .status-blue { background: #EBF8FF; border-left: 5px solid #3182CE; color: #2B6CB0; animation: pulse-blue 2s infinite; padding: 15px; border-radius: 10px; margin-bottom: 15px;}
    .status-yellow { background: #FFFFF0; border-left: 5px solid #D69E2E; color: #B7791F; animation: pulse-yellow 2s infinite; padding: 15px; border-radius: 10px; margin-bottom: 15px;}
    .status-red { background: #FFF5F5; border-left: 5px solid #E53E3E; color: #C53030; animation: pulse-red 2s infinite; padding: 15px; border-radius: 10px; margin-bottom: 15px;}
    .status-purple { background: #FAF5FF; border-left: 5px solid #805AD5; color: #553C9A; animation: pulse-purple 2s infinite; padding: 15px; border-radius: 10px; margin-bottom: 15px;}
</style>
""", unsafe_allow_html=True)

# --- 3. ฟังก์ชันอัจฉริยะ (Helper Functions) ---

def save_workspace():
    data_to_save = {
        'pdf_bytes': st.session_state.pdf_bytes,
        'pdf_name': st.session_state.pdf_name,
        'processed_data': st.session_state.processed_data,
        'global_data': st.session_state.global_data,
        'global_context_text': st.session_state.global_context_text,
        'selected_pages': st.session_state.selected_pages,
        'full_summaries': st.session_state.full_summaries,
        'user_api_key': st.session_state.user_api_key,
        'custom_prompt_text': st.session_state.custom_prompt_text,
        'use_custom_prompt': st.session_state.use_custom_prompt,
        'custom_summary_prompt_1': st.session_state.custom_summary_prompt_1,
        'custom_summary_prompt_2': st.session_state.custom_summary_prompt_2,
        'custom_summary_prompt_3': st.session_state.custom_summary_prompt_3,
        'custom_summary_prompt_4': st.session_state.custom_summary_prompt_4,
        'custom_summary_prompt_5': st.session_state.custom_summary_prompt_5,
        'use_custom_summary_prompt': st.session_state.use_custom_summary_prompt
    }
    try:
        with open("autosave_workspace.pkl", "wb") as f:
            pickle.dump(data_to_save, f)
    except Exception:
        pass

def load_workspace():
    if os.path.exists("autosave_workspace.pkl"):
        try:
            with open("autosave_workspace.pkl", "rb") as f:
                data = pickle.load(f)
                for k, v in data.items():
                    st.session_state[k] = v
            return True
        except Exception:
            return False
    return False

def clear_workspace():
    if os.path.exists("autosave_workspace.pkl"):
        try:
            os.remove("autosave_workspace.pkl")
        except Exception:
            pass

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
    char_count = len(text)
    if char_count == 0: return 18
    estimated_size = (area / (char_count * 0.35)) ** 0.5
    return max(13, min(42, int(estimated_size))) 

def split_content_hq(text):
    c_txt, hy_txt, q_txt = "", "", ""
    temp = text
    if "High-Yield:" in temp:
        parts = temp.split("High-Yield:")
        c_txt = parts[0].strip()
        temp = parts[1]
        if "Quiz:" in temp:
            hq_parts = temp.split("Quiz:")
            hy_txt = "High-Yield:\n" + hq_parts[0].strip()
            q_txt = "Quiz:\n" + hq_parts[1].strip()
        else:
            hy_txt = "High-Yield:\n" + temp.strip()
    elif "Quiz:" in temp:
        parts = temp.split("Quiz:")
        c_txt = parts[0].strip()
        q_txt = "Quiz:\n" + parts[1].strip()
    else:
        c_txt = temp.strip()
    return c_txt, hy_txt, q_txt

def get_layout_preview(c_pos, hy_pos, q_pos):
    layout_map = {"ด้านขวา": [], "ด้านล่าง": [], "ด้านซ้าย": [], "ด้านบน": []}
    layout_map[c_pos].append("<span style='color: #334155;'><b>เนื้อหา</b></span>")
    layout_map[hy_pos].append("<span style='color: #BE123C;'><b>High-Yield</b></span>")
    layout_map[q_pos].append("<span style='color: #0369A1;'><b>Quiz</b></span>")
    
    right_box = f"<div style='flex: 0.35; background: #F8FAFC; padding: 5px; font-size: 8px; border-left: 1px solid #E2E8F0;'>{'<br><br>'.join(layout_map['ด้านขวา'])}</div>" if layout_map['ด้านขวา'] else ""
    left_box = f"<div style='flex: 0.35; background: #F8FAFC; padding: 5px; font-size: 8px; border-right: 1px solid #E2E8F0;'>{'<br><br>'.join(layout_map['ด้านซ้าย'])}</div>" if layout_map['ด้านซ้าย'] else ""
    bottom_box = f"<div style='height: 40px; background: #F8FAFC; padding: 5px; font-size: 8px; border-top: 1px solid #E2E8F0; text-align: center;'>{' | '.join(layout_map['ด้านล่าง'])}</div>" if layout_map['ด้านล่าง'] else ""
    top_box = f"<div style='height: 40px; background: #F8FAFC; padding: 5px; font-size: 8px; border-bottom: 1px solid #E2E8F0; text-align: center;'>{' | '.join(layout_map['ด้านบน'])}</div>" if layout_map['ด้านบน'] else ""
    
    html_str = f"""<div style="width: 100%; height: 180px; border-radius: 10px; background: white; border: 2px solid #E2E8F0; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.02);">{top_box}<div style="flex: 1; display: flex; flex-direction: row;">{left_box}<div style="flex: 1; background: #F1F5F9; border: 2px dashed #CBD5E1; margin: 8px; display: flex; align-items: center; justify-content: center; font-size: 12px; color: #64748B; font-weight: bold; border-radius: 6px;">Slide</div>{right_box}</div>{bottom_box}</div>"""
    st.markdown(html_str, unsafe_allow_html=True)

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
        elif any(sec in line for sec in ["Quiz:", "Trick:", "การนำไปใช้ในคลินิก:", "ระวัง:", "กลไก/รายละเอียดและอาการ:", "Concept หลัก:", "Intro:", "เฉลย:"]):
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
        
        ("กลไก/รายละเอียดและอาการ:", "<div class='box-mech'><b style='color: #334155; font-size: 0.95em;'>⚙️ กลไกและอาการ</b></div>"),
        ("<strong>กลไก/รายละเอียดและอาการ:</strong>", "<div class='box-mech'><b style='color: #334155; font-size: 0.95em;'>⚙️ กลไกและอาการ</b></div>"),
        
        ("การนำไปใช้ในคลินิก:", "<div class='box-clinic'><b style='color: #0F766E; font-size: 0.95em;'>🩺 การนำไปใช้ในคลินิก</b></div>"),
        ("<strong>การนำไปใช้ในคลินิก:</strong>", "<div class='box-clinic'><b style='color: #0F766E; font-size: 0.95em;'>🩺 การนำไปใช้ในคลินิก</b></div>"),
        
        ("ระวัง:", "<div class='box-warn'><b style='color: #C2410C; font-size: 0.95em;'>⚠️ ระวัง</b></div>"),
        ("<strong>ระวัง:</strong>", "<div class='box-warn'><b style='color: #C2410C; font-size: 0.95em;'>⚠️ ระวัง</b></div>"),
        
        ("Trick:", "<div class='box-trick'><b style='color: #A16207; font-size: 0.95em;'>💡 Trick จำ</b></div>"),
        ("<strong>Trick:</strong>", "<div class='box-trick'><b style='color: #A16207; font-size: 0.95em;'>💡 Trick จำ</b></div>"),
        
        ("High-Yield:", "<div class='box-hy'><b style='color: #BE123C; font-size: 0.95em;'>🚨 High-Yield</b></div>"),
        ("<strong>High-Yield:</strong>", "<div class='box-hy'><b style='color: #BE123C; font-size: 0.95em;'>🚨 High-Yield</b></div>"),
        
        ("Quiz:", "<div class='box-quiz'><b style='color: #0369A1; font-size: 0.95em;'>📝 Quiz</b></div>"),
        ("<strong>Quiz:</strong>", "<div class='box-quiz'><b style='color: #0369A1; font-size: 0.95em;'>📝 Quiz</b></div>"),
        
        ("เฉลย:", "<div class='box-ans'><b style='color: #15803D; font-size: 0.95em;'>🎯 เฉลย</b></div>"),
        ("<strong>เฉลย:</strong>", "<div class='box-ans'><b style='color: #15803D; font-size: 0.95em;'>🎯 เฉลย</b></div>"),
    ]
    
    for old, new in replacements:
        html = html.replace(old, new)
        html = html.replace(f"<p>{new}</p>", new) 
        
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
            if not flash_models:
                flash_models = ["gemini-3.1-flash-lite"]
                
            flash_models = sorted(flash_models, key=lambda x: 0 if "3.1-flash-lite" in x else (1 if "2.5-flash-lite" in x else 2))
            st.session_state.flash_models_list = flash_models
            
            if is_locked:
                st.info("🔒 ระบบล็อกการตั้งค่าขณะรัน")
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
    content_pos = st.selectbox("วาง [เนื้อหา] ไว้ที่:", pos_options, index=0, disabled=is_locked)
    hy_pos = st.selectbox("วาง [High-Yield] ไว้ที่:", pos_options, index=1, disabled=is_locked) 
    quiz_pos = st.selectbox("วาง [Quiz] ไว้ที่:", pos_options, index=0, disabled=is_locked)
    
    st.markdown("### 📋 ข้อมูลที่ต้องการ")
    want_content = st.checkbox("คำอธิบายเนื้อหา", value=True, disabled=is_locked)
    want_summary = st.checkbox("สรุป High-Yield", value=True, disabled=is_locked)
    want_trick = st.checkbox("💡 ทริคจำ (Trick)", value=True, disabled=is_locked)
    want_quiz = st.checkbox("Quiz", value=True, disabled=is_locked)
    
    quiz_count = 3
    want_answer = False
    if want_quiz:
        quiz_count = st.slider("จำนวนข้อ Quiz:", 1, 5, 3, disabled=is_locked)
        want_answer = st.checkbox("รวมเฉลย", value=True, disabled=is_locked)

    get_layout_preview(content_pos, hy_pos, quiz_pos)

    # 🌟 ระบบ Customize Prompt เนื้อหาหลัก
    st.markdown("### 🛠️ ปรับแต่ง Prompt เนื้อหาหลัก")
    use_custom_prompt = st.checkbox("เปิดใช้งานแก้ไข Prompt หลัก", value=st.session_state.use_custom_prompt, disabled=is_locked)
    
    base_prompt_template = f"""คุณคือรุ่นพี่แพทย์ที่กำลังติว นสพ. ปี {med_year} ตอบเป็นภาษาไทย
ให้อธิบายเนื้อหาให้ **เข้าใจง่าย กระชับ** ไม่เป็นวิชาการจนเกินไป เหมือนรุ่นพี่อธิบายให้รุ่นน้องฟัง

**ข้อมูลอ้างอิงภาพรวม (Global Context):**
{{global_context}}

**คำเตือนและข้อบังคับสำคัญ (ต้องทำตามอย่างเคร่งครัด):**
1. **ห้ามใช้คำทักทายเด็ดขาด** (เช่น สวัสดีครับน้อง... วันนี้เรามา...) ให้เริ่มอธิบายเนื้อหาทันที
2. **ห้ามข้ามการอธิบายเนื้อหาเด็ดขาด!** ให้เขียนชิดขอบซ้าย ไม่ต้องเว้นวรรคเข้าข้างใน
3. **คำย่อและคำศัพท์:** หากมีคำย่อครั้งแรกในหน้า ให้ใส่วงเล็บคำเต็มภาษาอังกฤษต่อท้ายเสมอ คำศัพท์แพทย์/โรค/อาการ ให้ใส่วงเล็บภาษาอังกฤษต่อท้ายด้วย (เช่น ไอ (cough))
4. **ต้องเน้นตัวหนาที่คำสำคัญ** เพื่อให้สะดุดตา
5. การอธิบายเหตุการณ์สำคัญ/อาการ/กลไก **ต้องมีการให้เหตุผลโดยใช้คำว่า '...เพราะ...' เสมอ** เพื่อให้ผู้อ่านเข้าใจและจดจำได้นาน
6. ⚠️ **กฎพิเศษสำหรับข้อสอบ:** ถ้าเนื้อหาในหน้านั้นเป็น "ข้อสอบ", "คำถาม", หรือ "โจทย์" ให้เปลี่ยนการอธิบายเป็นเฉลยข้อสอบดังนี้:
   - โจทย์ถามอะไร?
   - ตอบข้อไหน?
   - ทำไมข้อนี้ถูก?
   - ทำไมข้ออื่นถึงผิด?
   (แล้วข้ามแพทเทิร์นเนื้อหาหลักไปได้เลย)
7. หากเป็นหน้าว่างจริงๆ (ไม่มีเนื้อหาการแพทย์) ให้ตอบแค่ 'NON_CONTENT'
ในส่วนของ high yield ให้เกริ่นเนื้อหา concept คร่าวๆของหน้านั้น ก่อนขึ้น KEY1  แล้วถ้าหน้าไหนมีหลายประเด็นสำคัญ ก็เพิ่ม
KEY3, KEY4  ได้เลย ตามความเหมาะสม ไม่บังคับว่าต้องมีกี่ Key

{{strict_pattern}}"""

    if use_custom_prompt:
        custom_prompt_text = st.text_area(
            "แก้ไข Prompt (ห้ามลบตัวแปรที่มีวงเล็บปีกกา {})", 
            value=st.session_state.custom_prompt_text if st.session_state.custom_prompt_text else base_prompt_template, 
            height=300,
            disabled=is_locked
        )
        st.session_state.custom_prompt_text = custom_prompt_text
    else:
        st.session_state.custom_prompt_text = base_prompt_template
        
    st.session_state.use_custom_prompt = use_custom_prompt

    # 🌟 ระบบ Customize Prompt สำหรับ One-Sheet Summary (เรียงตามสไลด์ 4 แผ่น + Master Table พร้อม Search Engine แผ่นที่ 5)
    st.markdown("### 📝 ปรับแต่ง Prompt สำหรับ One-Sheet Summary (5 แผ่น)")
    use_custom_summary_prompt = st.checkbox("เปิดใช้งานแก้ไข Prompt สำหรับ Summary", value=st.session_state.use_custom_summary_prompt, disabled=is_locked)

    default_summary_prompt_1 = f"""สร้าง Clinical Summary แผ่นที่ 1 จาก 5 แผ่น สำหรับ นสพ.ปี {med_year}
- สรุปเนื้อหา **เรียงตามลำดับหน้าสไลด์ต้นฉบับ [Page 1] ถึงช่วง 25% แรก**
- คงหัวข้อหลัก หัวข้อย่อย Keyword และเหตุผล ('...เพราะ...') ระบุ [Page X] กำกับทุกหัวข้อ
- จัดรูปแบบ Markdown Table หรือ Bullet points อ่านง่าย ไม่ข้ามสไลด์

ข้อมูลอ้างอิง:
{{full_summaries}}"""

    default_summary_prompt_2 = f"""สร้าง Clinical Summary แผ่นที่ 2 จาก 5 แผ่น สำหรับ นสพ.ปี {med_year}
- สรุปเนื้อหา **เรียงต่อตามลำดับหน้าสไลด์ต้นฉบับ (ช่วง 25% ถึง 50%)**
- สรุปเรียงตามลำดับหน้าอย่างต่อเนื่องจากแผ่นแรก ระบุ [Page X] กำกับทุกหัวข้อ
- คงหัวข้อหลัก หัวข้อย่อย พยาธิสรีรวิทยา และกลไกเหตุผล '...เพราะ...' ตามสไลด์จริง

ข้อมูลอ้างอิง:
{{full_summaries}}"""

    default_summary_prompt_3 = f"""สร้าง Clinical Summary แผ่นที่ 3 จาก 5 แผ่น สำหรับ นสพ.ปี {med_year}
- สรุปเนื้อหา **เรียงต่อตามลำดับหน้าสไลด์ต้นฉบับ (ช่วง 50% ถึง 75%)**
- สรุปเรียงตามลำดับหน้าอย่างต่อเนื่องจากแผ่นสอง ระบุ [Page X] กำกับทุกหัวข้อ
- คงหัวข้อหลัก หัวข้อย่อย การวินิจฉัย ผลแล็บ การแยกโรค DDx ตามสไลด์จริง

ข้อมูลอ้างอิง:
{{full_summaries}}"""

    default_summary_prompt_4 = f"""สร้าง Clinical Summary แผ่นที่ 4 จาก 5 แผ่น สำหรับ นสพ.ปี {med_year}
- สรุปเนื้อหา **เรียงต่อตามลำดับหน้าสไลด์ต้นฉบับ (ช่วง 75% จนถึงหน้าสุดท้าย)**
- สรุปเรียงตามลำดับหน้าอย่างต่อเนื่องจากแผ่นสามจนจบสไลด์ ระบุ [Page X] กำกับทุกหัวข้อ
- คงหัวข้อหลัก หัวข้อย่อย ยา แนวทางการรักษา และข้อควรระวัง ตามสไลด์จริง

ข้อมูลอ้างอิง:
{{full_summaries}}"""

    # 🌟 Prompt สำหรับแผ่นที่ 5: Master Clinical Table พร้อมระบบ Search & Pathognomonic Sign
    default_summary_prompt_5 = f"""คุณคืออาจารย์แพทย์ติวสอบ NL ให้ นสพ.ปี {med_year}
กรุณาสร้าง Master Clinical Table แผ่นที่ 5 (ตารางสรุปโรคฉบับเป็นทางการ ครบถ้วน อ่านสบายตา)
ดึง "ทุกโรคสำคัญ" ที่ปรากฏในเอกสารทั้งหมด มาจัดลงในตาราง Markdown เดียวกัน

ให้เปิดใช้ Search Engine เพื่อสืบค้น "Official Diagnostic Criteria" สากลทางคลินิกเพิ่มเติมให้ถูกต้องแม่นยำ

กำหนดหัวคอลัมน์ตารางให้กระชับดังนี้:
| Disease & Trick | Pathophysiology | Clinical Features | Diagnostic Criteria | Investigations | Management | Complications & Pearls |

รายละเอียดข้อมูลในแต่ละคอลัมน์:
1. **Disease & Trick:**
   - **ชื่อโรค**
   - **(Hook word)** หรือ Mnemonic จำสากล
   - **Pathognomonic sign / Keyword สำคัญประจำโรค** (⚠️ สรุปเฉพาะที่มีจริงจากเอกสารหรือเกณฑ์สากล **หากโรคนั้นไม่มี ให้ละไว้ ห้ามมั่วใส่มาเด็ดขาด**)
2. **Pathophysiology:** กลไกการเกิดโรคพยาธิสภาพหลัก
3. **Clinical Features:** อาการเด่นและอาการแสดง (หากมีเหตุผลเชื่อมโยงจากกลไก ให้บอกกระชับด้วยคำว่า '...เพราะ...')
4. **Diagnostic Criteria:** เกณฑ์การวินิจฉัยอย่างเป็นทางการ (Official / International Guidelines สากล)
5. **Investigations:** การส่งตรวจเพิ่มเติมเพื่อยืนยันการวินิจฉัย (Confirmatory tests / Labs / Imaging)
6. **Management:** แนวทางการรักษา (First-line drugs + ขนาดยา หรือ หัตถการรักษาหลัก)
7. **Complications & Pearls:** ภาวะแทรกซ้อนจากการรักษาที่ต้องระวัง + ข้อควรระวัง High-Yield

เงื่อนไขบังคับเคร่งครัด:
- **ทำตัวหนา (Bold)** ในคำสำคัญ ประเด็นเจอบ่อย และข้อควรระวังอย่างชัดเจน
- หากข้อมูลส่วนใดไม่มีในเอกสาร ให้ใส่เครื่องหมาย (-) **ห้ามคิดค้นข้อมูลมั่วขึ้นมาเองเด็ดขาด**
- นำเสนอในรูปแบบ Markdown Table ที่สะอาด สวยงาม เป็นทางการ

ข้อมูลอ้างอิง:
{{full_summaries}}"""

    if use_custom_summary_prompt:
        custom_summary_prompt_1 = st.text_area("Prompt แผ่นที่ 1 (สไลด์ส่วนที่ 1/4)", value=st.session_state.custom_summary_prompt_1 if st.session_state.custom_summary_prompt_1 else default_summary_prompt_1, height=140, disabled=is_locked)
        custom_summary_prompt_2 = st.text_area("Prompt แผ่นที่ 2 (สไลด์ส่วนที่ 2/4)", value=st.session_state.custom_summary_prompt_2 if st.session_state.custom_summary_prompt_2 else default_summary_prompt_2, height=140, disabled=is_locked)
        custom_summary_prompt_3 = st.text_area("Prompt แผ่นที่ 3 (สไลด์ส่วนที่ 3/4)", value=st.session_state.custom_summary_prompt_3 if st.session_state.custom_summary_prompt_3 else default_summary_prompt_3, height=140, disabled=is_locked)
        custom_summary_prompt_4 = st.text_area("Prompt แผ่นที่ 4 (สไลด์ส่วนที่ 4/4)", value=st.session_state.custom_summary_prompt_4 if st.session_state.custom_summary_prompt_4 else default_summary_prompt_4, height=140, disabled=is_locked)
        custom_summary_prompt_5 = st.text_area("Prompt แผ่นที่ 5 (Master Table + Search)", value=st.session_state.custom_summary_prompt_5 if st.session_state.custom_summary_prompt_5 else default_summary_prompt_5, height=220, disabled=is_locked)
        
        st.session_state.custom_summary_prompt_1 = custom_summary_prompt_1
        st.session_state.custom_summary_prompt_2 = custom_summary_prompt_2
        st.session_state.custom_summary_prompt_3 = custom_summary_prompt_3
        st.session_state.custom_summary_prompt_4 = custom_summary_prompt_4
        st.session_state.custom_summary_prompt_5 = custom_summary_prompt_5
    else:
        st.session_state.custom_summary_prompt_1 = default_summary_prompt_1
        st.session_state.custom_summary_prompt_2 = default_summary_prompt_2
        st.session_state.custom_summary_prompt_3 = default_summary_prompt_3
        st.session_state.custom_summary_prompt_4 = default_summary_prompt_4
        st.session_state.custom_summary_prompt_5 = default_summary_prompt_5
        
    st.session_state.use_custom_summary_prompt = use_custom_summary_prompt

    if st.button("💾 บันทึกการตั้งค่า Prompt", use_container_width=True):
        save_workspace()
        st.toast("บันทึกการตั้งค่า Prompt เรียบร้อยแล้ว!")

    current_settings = {
        "year": med_year, "max_tok": max_tokens, 
        "m_right": margin_right_pct, "m_bottom": margin_bottom_pct,
        "c_pos": content_pos, "hy_pos": hy_pos, "q_pos": quiz_pos,
        "content": want_content, "summary": want_summary, "quiz": want_quiz, "count": quiz_count, "ans": want_answer,
        "trick": want_trick, "use_prompt": use_custom_prompt, "use_summary_prompt": use_custom_summary_prompt
    }
    if not is_locked and st.session_state.last_settings and current_settings != st.session_state.last_settings:
        st.session_state.settings_changed_alert = True
    st.session_state.last_settings = current_settings

# --- 5. หน้าหลัก: การจัดการไฟล์ ---
st.markdown("<div class='main-header'>📚 PDF Note Space: Smart Reader</div>", unsafe_allow_html=True)

if not st.session_state.pdf_bytes:
    if os.path.exists("autosave_workspace.pkl"):
        st.info("💾 **พบงานที่ทำค้างไว้!** (ระบบ Auto-save ป้องกันเน็ตหลุด/หน้าจอดับ)")
        if st.button("🔄 กู้คืนงานที่ทำค้างไว้", type="primary"):
            with st.spinner("กำลังโหลดข้อมูล..."):
                if load_workspace():
                    st.success("กู้คืนสำเร็จ!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("ไฟล์กู้คืนมีปัญหา หรือหมดอายุแล้ว")
    
    uploaded_file = st.file_uploader("อัปโหลดสไลด์อาจารย์ (PDF) - รองรับสูงสุด 400 หน้า", type="pdf")
    if uploaded_file:
        with st.status(f"กำลังนำเข้าไฟล์: {uploaded_file.name}...", expanded=True) as status:
            st.session_state.pdf_bytes = uploaded_file.getvalue()
            st.session_state.pdf_name = uploaded_file.name
            doc_tmp = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
            st.session_state.selected_pages = list(range(len(doc_tmp)))
            for i in range(len(doc_tmp)):
                st.session_state[f"sel_{i}"] = True
            save_workspace()
            status.update(label=f"✅ อัปโหลดสำเร็จ: {uploaded_file.name}", state="complete")
        st.rerun()
else:
    st.info(f"📄 ไฟล์ปัจจุบัน: **{st.session_state.pdf_name}**")
    if st.button("🗑️ เปลี่ยนเอกสาร (Reset)"):
        st.session_state.show_reset_confirm = True

    if st.session_state.show_reset_confirm:
        st.warning("ยืนยันการล้างข้อมูลทั้งหมด?")
        c1, c2 = st.columns(2)
        if c1.button("✅ ยืนยัน", type="primary"):
            clear_workspace() 
            for k in keys_to_init: del st.session_state[k]
            st.rerun()
        if c2.button("❌ ยกเลิก"):
            st.session_state.show_reset_confirm = False
            st.rerun()

# --- 6. ระบบเลือกหน้า (Page Customizer) ---
if st.session_state.pdf_bytes and not is_locked:
    doc_in = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
    total_pages = len(doc_in)
    
    if "expander_open" not in st.session_state: st.session_state.expander_open = True
    if st.session_state.expander_open:
        with st.expander("🖼️ เลือกว่าจะให้ AI ประมวลผลหน้าไหนบ้าง (Customize Pages)", expanded=True):
            st.info("💡 ทุกหน้าถูกเลือกไว้เป็นค่าเริ่มต้น")
            c_btn1, c_btn2, c_btn3 = st.columns([1,1,2])
            
            if c_btn1.button("✅ เลือกทั้งหมด"):
                st.session_state.selected_pages = list(range(total_pages))
                st.rerun()
            if c_btn2.button("❌ ไม่เลือกเลย"):
                st.session_state.selected_pages = []
                st.rerun()
            if c_btn3.button("💾 ยืนยันการเลือกหน้า", type="primary"):
                st.session_state.expander_open = False
                save_workspace() 
                st.rerun()
            
            st.write("---")
            cols_per_row = 5
            for row_idx in range(0, total_pages, cols_per_row):
                cols = st.columns(cols_per_row)
                for col_idx in range(cols_per_row):
                    page_num = row_idx + col_idx
                    if page_num < total_pages:
                        with cols[col_idx]:
                            page = doc_in[page_num]
                            pix = page.get_pixmap(dpi=40)
                            st.image(pix.tobytes("png"), use_container_width=True) 
                            
                            is_checked = st.checkbox(f"หน้า {page_num+1}", value=(page_num in st.session_state.selected_pages), key=f"sel_{page_num}")
                            if is_checked and page_num not in st.session_state.selected_pages:
                                st.session_state.selected_pages.append(page_num)
                            elif not is_checked and page_num in st.session_state.selected_pages:
                                st.session_state.selected_pages.remove(page_num)
    else:
        if st.button("⚙️ เปิดหน้าต่างเลือกหน้าอีกครั้ง"):
            st.session_state.expander_open = True
            st.rerun()

# --- 7. แถบสถานะส่วนบน (Animated Status) ---
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
            est_tokens = pages_to_do * max_tokens
            st.info(f"""
            - หน้าที่ต้องประมวลผลเพิ่ม: **{pages_to_do} หน้า**
            - คาดการณ์ Token ที่ต้องใช้ (Output): **~{est_tokens:,} Tokens**
            """)
            c_start1, c_start2 = st.columns(2)
            if c_start1.button("✅ ยืนยันรันงาน", type="primary"):
                if not st.session_state.current_active_model or st.session_state.current_active_model in st.session_state.exhausted_models:
                    st.session_state.current_active_model = get_best_available_model(st.session_state.flash_models_list)
                
                if st.session_state.phase == 'idle':
                    st.session_state.phase = 'global_scan'
                
                st.session_state.is_running = True
                st.session_state.stop_clicked = False
                st.session_state.show_start_popup = False
                st.rerun()
            if c_start2.button("❌ ยกเลิก"):
                st.session_state.show_start_popup = False
                st.rerun()
    
    action_placeholder = st.empty() 

    col_run1, col_ctrl2, col_ctrl3 = st.columns([1,1,1])
    if col_run1.button("🚀 Start / Continue", type="primary", disabled=is_locked):
        st.session_state.show_start_popup = True
        st.rerun()
    if col_ctrl2.button("🛑 Stop / Pause", disabled=not st.session_state.is_running):
        st.session_state.is_running = False
        st.session_state.stop_clicked = True
        st.rerun()

    # --- 8. E-BOOK READER & EDITING ---
    st.write("---")
    st.subheader(f"📖 Clinical E-Book: หน้า {st.session_state.page_idx + 1}")
    
    c_nav1, c_nav2, c_nav3 = st.columns([1, 2, 1])
    with c_nav1:
        if st.button("⬅️ หน้าก่อนหน้า") and st.session_state.page_idx > 0:
            st.session_state.page_idx -= 1
            st.rerun()
    with c_nav2:
        new_page = st.slider("กระโดดไปหน้า:", 1, total_pages, st.session_state.page_idx + 1, label_visibility="collapsed")
        if new_page - 1 != st.session_state.page_idx:
            st.session_state.page_idx = new_page - 1
            st.rerun()
    with c_nav3:
        if st.button("หน้าถัดไป ➡️") and st.session_state.page_idx < total_pages - 1:
            st.session_state.page_idx += 1
            st.rerun()

    curr = st.session_state.page_idx
    if curr in st.session_state.processed_data:
        data = st.session_state.processed_data[curr]
        col_v1, col_v2 = st.columns([1.2, 1])
        with col_v1:
            st.image(data["img"], use_container_width=True, caption="E-book preview")
        with col_v2:
            st.markdown("### 📝 บันทึกการเรียน")
            if f"editing_{curr}" not in st.session_state: st.session_state[f"editing_{curr}"] = False
            display_text = data["user_text"] if data["user_text"] else data["ai_text"]
            
            if st.session_state[f"editing_{curr}"]:
                edited = st.text_area("แก้ไขเนื้อหา:", value=display_text, height=400)
                ce1, ce2 = st.columns(2)
                if ce1.button("💾 ยืนยันการแก้ไข", type="primary"):
                    st.session_state.processed_data[curr]["user_text"] = edited
                    st.session_state[f"editing_{curr}"] = False
                    save_workspace() 
                    st.rerun()
                if ce2.button("🔄 คืนค่าต้นฉบับ AI"):
                    st.session_state.processed_data[curr]["user_text"] = ""
                    st.session_state[f"editing_{curr}"] = False
                    save_workspace() 
                    st.rerun()
            else:
                raw_text = display_text
                html_content = apply_custom_tags(raw_text)
                
                st.markdown(f"<div class='edit-box'>{html_content}</div>", unsafe_allow_html=True)
                if st.button("✏️ พิมพ์แก้ไขเนื้อหานี้"):
                    st.session_state[f"editing_{curr}"] = True
                    if st.session_state.is_running:
                        st.session_state.is_running = False 
                        st.warning("⚠️ ระบบหยุดรันชั่วคราวเพื่อให้แก้ไขได้สะดวก กด Continue เพื่อรันต่อ")
                    st.rerun()
    else:
        st.info(f"⏳ หน้าที่ {curr+1} ยังไม่ได้ประมวลผล (อยู่ในคิว)...")

    # --- 9. ปุ่มดาวน์โหลด PDF และระบบสร้างสรุป 5 แผ่น ---
    st.write("---")
    if len(st.session_state.processed_data) > 0:
        
        if st.button("📦 รวบรวมและเตรียมดาวน์โหลด PDF (พร้อมสรุป 5 แผ่นรวม Master Clinical Table)"):
            with st.spinner("กำลังค้นหาเกณฑ์วินิจฉัยสากลผ่าน Search Engine และประกอบร่าง PDF ฉบับสมบูรณ์ (รอสักครู่นะครับ)..."):
                doc_out = fitz.open()
                arch = fitz.Archive(".")
                
                for i in range(total_pages):
                    p_in = doc_in[i]; w, h = p_in.rect.width, p_in.rect.height
                    new_w = w * (1 + margin_right_pct/100)
                    new_h = h * (1 + margin_bottom_pct/100)
                    p_out = doc_out.new_page(width=new_w, height=new_h)
                    p_out.show_pdf_page(fitz.Rect(0, 0, w, h), doc_in, i)
                    
                    bg_color = (0.97, 0.98, 0.99)
                    if margin_right_pct > 0: p_out.draw_rect(fitz.Rect(w, 0, new_w, new_h), color=bg_color, fill=bg_color, width=0)
                    if margin_bottom_pct > 0: p_out.draw_rect(fitz.Rect(0, h, w, new_h), color=bg_color, fill=bg_color, width=0)
                    
                    rects = {
                        "ด้านขวา": fitz.Rect(w + 10, 10, new_w - 10, h - 10),
                        "ด้านล่าง": fitz.Rect(10, h + 10, w - 10, new_h - 10),
                        "ด้านซ้าย": fitz.Rect(10, 10, (w * margin_right_pct/100) - 10, h - 10), 
                        "ด้านบน": fitz.Rect(10, 10, w - 10, (h * margin_bottom_pct/100) - 10) 
                    }
                    
                    if i in st.session_state.processed_data:
                        raw_txt = st.session_state.processed_data[i]["user_text"] or st.session_state.processed_data[i]["ai_text"]
                        
                        if raw_txt and "⚠️" not in raw_txt:
                            raw_txt = re.sub(r'^[•\-\*]\s*$', '', raw_txt, flags=re.MULTILINE)
                            c_txt, hq_txt, q_txt = split_content_hq(raw_txt)
                            
                            box_contents = {"ด้านขวา": "", "ด้านล่าง": "", "ด้านซ้าย": "", "ด้านบน": ""}
                            if c_txt: box_contents[content_pos] += c_txt + "\n\n"
                            if hq_txt: box_contents[hy_pos] += hq_txt + "\n\n"
                            if q_txt: box_contents[quiz_pos] += q_txt + "\n\n"
                            
                            for pos, text_chunk in box_contents.items():
                                if not text_chunk.strip(): continue
                                box = rects[pos]
                                html = apply_custom_tags(text_chunk)
                                f_size = calc_dynamic_fontsize(html, box.width, box.height)
                                
                                css = f"""
                                @font-face {{ font-family: 'T'; src: url('THSarabunNew.ttf'); }}
                                @font-face {{ font-family: 'T'; font-weight: bold; src: url('THSarabunNew Bold.ttf'); }}
                                body {{ font-family: 'T'; font-size: {f_size}px; line-height: 1.5; color: #0F172A; margin: 0; padding: 0; }} 
                                b, strong {{ font-weight: bold; }}
                                
                                .box-intro {{ background-color: #F8FAFC; border-left: 3px solid #94A3B8; padding: 2px 8px; margin: 6px 0 4px 0; }}
                                .box-concept {{ background-color: #EEF2FF; border-left: 3px solid #6366F1; padding: 2px 8px; margin: 6px 0 4px 0; }}
                                .box-mech {{ background-color: #F1F5F9; border-left: 3px solid #475569; padding: 2px 8px; margin: 6px 0 4px 0; }}
                                .box-clinic {{ background-color: #F0FDFA; border-left: 3px solid #14B8A6; padding: 2px 8px; margin: 6px 0 4px 0; }}
                                .box-warn {{ background-color: #FFF7ED; border-left: 3px solid #F97316; padding: 2px 8px; margin: 6px 0 4px 0; }}
                                .box-trick {{ background-color: #FEF9C3; border-left: 3px solid #EAB308; padding: 2px 8px; margin: 6px 0 4px 0; }}
                                .box-hy {{ background-color: #FFF1F2; border-left: 3px solid #F43F5E; padding: 2px 8px; margin: 6px 0 4px 0; }}
                                .box-quiz {{ background-color: #F0F9FF; border-left: 3px solid #0EA5E9; padding: 2px 8px; margin: 6px 0 4px 0; }}
                                .box-ans {{ background-color: #F0FDF4; border-left: 3px solid #22C55E; padding: 2px 8px; margin: 6px 0 4px 0; }}
                                
                                table {{ border-collapse: collapse; width: 100%; margin-top: 10px; margin-bottom: 10px; }} 
                                th {{ background-color: #F8FAFC; border: 1px solid #CBD5E1; padding: 6px; color: #334155; text-align: left; }}
                                td {{ border: 1px solid #E2E8F0; padding: 6px; color: #475569; }}
                                ul, ol {{ margin-top: 8px; margin-bottom: 8px; padding-left: 20px; }}
                                li {{ margin-bottom: 8px; }}
                                """
                                try: p_out.insert_htmlbox(box, f"<style>{css}</style><body>{html}</body>", archive=arch)
                                except: p_out.insert_textbox(box, text_chunk, fontsize=f_size)
                            
                # --- 🌟 ระบบสร้าง One-Sheet Summary 5 แผ่น (เปิดใช้ Google Search Grounding ที่แก้ไขแล้ว) ---
                if st.session_state.full_summaries:
                    model_os = genai.GenerativeModel(
                        get_best_available_model(st.session_state.flash_models_list) or "gemini-3.1-flash-lite",
                        tools=["google_search_retrieval"] # เปิด Search Engine ค้นหา Official Criteria อย่างถูกต้อง
                    )
                    safety = { HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE }
                    
                    data_chunk = st.session_state.full_summaries[:35000]
                    
                    sheet_configs = [
                        {"title": "📌 SLIDE SUMMARY (PART 1: SLIDE 1 ONWARDS) 📌", "border_color": "#0EA5E9", "th_bg": "#F8FAFC", "th_color": "#0F172A", "prompt_key": "custom_summary_prompt_1", "is_landscape": False},
                        {"title": "📌 SLIDE SUMMARY (PART 2: CONTINUATION) 📌", "border_color": "#14B8A6", "th_bg": "#F0FDFA", "th_color": "#0F766E", "prompt_key": "custom_summary_prompt_2", "is_landscape": False},
                        {"title": "📌 SLIDE SUMMARY (PART 3: CONTINUATION) 📌", "border_color": "#6366F1", "th_bg": "#EEF2FF", "th_color": "#4338CA", "prompt_key": "custom_summary_prompt_3", "is_landscape": False},
                        {"title": "📌 SLIDE SUMMARY (PART 4: UNTIL FINAL SLIDE) 📌", "border_color": "#F97316", "th_bg": "#FFF7ED", "th_color": "#C2410C", "prompt_key": "custom_summary_prompt_4", "is_landscape": False},
                        {"title": "🩺 MASTER CLINICAL MATRIX (COMPREHENSIVE DISEASE TABLE) 🩺", "border_color": "#2563EB", "th_bg": "#EFF6FF", "th_color": "#1E40AF", "prompt_key": "custom_summary_prompt_5", "is_landscape": True}
                    ]
                    
                    for idx, cfg in enumerate(sheet_configs, start=1):
                        prompt_template = getattr(st.session_state, cfg["prompt_key"])
                        prompt_sheet = prompt_template.replace("{full_summaries}", data_chunk)
                        try:
                            os_res = model_os.generate_content(prompt_sheet, safety_settings=safety)
                            os_html = markdown.markdown(os_res.text, extensions=['tables'])
                        except:
                            os_html = f"One-sheet Summary (Sheet {idx}) ไม่สามารถสร้างได้ในขณะนี้"
                        
                        if cfg["is_landscape"]:
                            p_os = doc_out.new_page(width=842, height=595)
                            rect_target = fitz.Rect(30, 30, 812, 565)
                            f_size_os = calc_dynamic_fontsize(os_html, 782, 535)
                        else:
                            p_os = doc_out.new_page(width=595, height=842)
                            rect_target = fitz.Rect(40, 40, 555, 802)
                            f_size_os = calc_dynamic_fontsize(os_html, 515, 762)

                        css_os = f"""
                        @font-face {{ font-family: 'T'; src: url('THSarabunNew.ttf'); }} 
                        @font-face {{ font-family: 'T'; font-weight: bold; src: url('THSarabunNew Bold.ttf'); }} 
                        body {{ font-family: 'T'; font-size: {f_size_os}px; color: #334155; line-height: 1.35; }} 
                        h2 {{ text-align: center; border-bottom: 2px solid {cfg['border_color']}; color: #0F172A; padding-bottom: 4px; font-size: 1.1em; margin-bottom: 8px; }} 
                        table {{ width: 100%; border-collapse: collapse; margin: 6px 0; table-layout: fixed; }} 
                        th, td {{ border: 1px solid #CBD5E1; padding: 4px 6px; word-wrap: break-word; vertical-align: top; }} 
                        th {{ background-color: {cfg['th_bg']}; color: {cfg['th_color']}; font-weight: bold; text-align: center; font-size: 0.95em; }}
                        b, strong {{ color: #0F172A; font-weight: bold; }}
                        ul, ol {{ margin-top: 2px; margin-bottom: 2px; padding-left: 14px; }}
                        li {{ margin-bottom: 2px; }}
                        """
                        p_os.insert_htmlbox(rect_target, f"<style>{css_os}</style><body><h2>{cfg['title']}</h2>{os_html}</body>", archive=arch)

                st.session_state.base_pdf_doc_bytes = doc_out.tobytes()
                st.session_state.show_download_modal = True

        if st.session_state.get('show_download_modal') and st.session_state.get('base_pdf_doc_bytes'):
            st.markdown("""
            <div style="border: 2px solid #3182CE; border-radius: 12px; padding: 25px; background-color: #F8FAFC; margin-top: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.05);">
                <h3 style="color: #2B6CB0; margin-top: 0; font-weight: 800;">🗜️ ตั้งค่าการบีบอัดไฟล์ PDF</h3>
                <p style="color: #475569; font-size: 16px;">สรุปครบถ้วน 5 แผ่น (4 แผ่นเรียงสไลด์ + 1 แผ่น Master Clinical Matrix) พร้อมใช้งานแล้วครับ สามารถเลือกปรับระดับการบีบอัดไฟล์ได้เลยครับ</p>
            """, unsafe_allow_html=True)
            
            raw_bytes = st.session_state.base_pdf_doc_bytes
            temp_doc = fitz.open(stream=raw_bytes, filetype="pdf")
            orig_size_mb = len(raw_bytes) / (1024 * 1024)
            
            st.markdown(f"📁 ขนาดต้นฉบับก่อนบีบอัด: **{orig_size_mb:.2f} MB**")
            
            comp_choice = st.radio(
                "เลือกระดับการบีบอัด:",
                options=[
                    "2. บีบอัดที่แนะนำ (สมดุลที่สุด - แนะนำอันนี้ครับ)", 
                    "1. บีบอัดขั้นสุด (เล็กที่สุด แต่อาจใช้เวลาโหลดเพิ่มนิดหน่อย)", 
                    "3. บีบอัดนิดหน่อย (ไฟล์ใหญ่อยู่ แต่รักษาคุณภาพภาพเดิมไว้เยอะสุด)"
                ],
                index=0
            )
            
            with st.spinner("กำลังคำนวณขนาดไฟล์หลังบีบอัด..."):
                if "ขั้นสุด" in comp_choice:
                    final_bytes = temp_doc.tobytes(garbage=4, deflate=True, clean=True)
                elif "แนะนำ" in comp_choice:
                    final_bytes = temp_doc.tobytes(garbage=3, deflate=True)
                else:
                    final_bytes = temp_doc.tobytes(garbage=1, deflate=True)
                    
                final_size_mb = len(final_bytes) / (1024 * 1024)
                saved_mb = orig_size_mb - final_size_mb

            st.markdown(f"📉 หลังบีบอัดไฟล์จะเหลือขนาด: <strong style='color: #E53E3E; font-size: 1.4em;'>{final_size_mb:.2f} MB</strong> (ประหยัดพื้นที่ไปได้ **{saved_mb:.2f} MB**)", unsafe_allow_html=True)
            
            st.download_button(
                label=f"💾 คลิกดาวน์โหลดไฟล์ PDF ลงเครื่อง ({final_size_mb:.2f} MB)",
                data=final_bytes,
                file_name=f"Note_{st.session_state.pdf_name}",
                mime="application/pdf",
                type="primary"
            )
            
            if st.button("❌ ปิดหน้าต่างนี้"):
                st.session_state.show_download_modal = False
                st.rerun()
                
            st.markdown("</div>", unsafe_allow_html=True)

    # --- 10. ระบบประมวลผลหลังบ้าน (2-Phase Background Processor) ---
    if st.session_state.is_running and not st.session_state.stop_clicked:
        active_m = st.session_state.current_active_model
        model = genai.GenerativeModel(active_m)
        config = GenerationConfig(max_output_tokens=max_tokens)
        safety = { HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE }

        # ==========================================
        # PHASE 1: GLOBAL SCAN (สแกนภาพรวมและสารบัญ)
        # ==========================================
        if st.session_state.phase == 'global_scan':
            target_global = next((i for i in st.session_state.selected_pages if i not in st.session_state.global_data), None)
            
            if target_global is None:
                st.session_state.phase = 'detail_scan'
                
                context_lines = []
                for idx in st.session_state.selected_pages:
                    g_info = st.session_state.global_data.get(idx, {})
                    topic = g_info.get('topic', f"หน้า {idx+1}")
                    summary = g_info.get('summary', "")
                    context_lines.append(f"- หน้า {idx+1} ({topic}): {summary}")
                
                st.session_state.global_context_text = "\n".join(context_lines)
                save_workspace() 
                st.rerun()

            else:
                st.session_state.status_mode = 'purple'
                action_html = f"<div class='status-purple'><b>🔍 [Phase 1/2] กำลังสแกนภาพรวม (หน้า {target_global+1} / {total_pages})</b><br>🤖 เพื่อสร้างระบบความจำ Context</div>"
                action_placeholder.markdown(action_html, unsafe_allow_html=True)
                
                p_img = doc_in[target_global].get_pixmap(dpi=50) 
                img = Image.open(io.BytesIO(p_img.tobytes("png")))
                
                prompt_global = """
                วิเคราะห์สไลด์หน้านี้อย่างรวดเร็ว ตอบกลับตามรูปแบบนี้เท่านั้น (ห้ามมีคำอื่น):
                TOPIC: (ชื่อหัวข้อเรื่องของหน้านี้ สั้นๆ 1-3 คำ)
                SUMMARY: (สรุปใจความสำคัญของหน้านี้สั้นๆ 1 ประโยค เพื่อให้ AI ตัวอื่นรู้ว่าหน้านี้สอนเรื่องอะไร)
                """
                
                try:
                    fast_config = GenerationConfig(max_output_tokens=100)
                    resp = model.generate_content([prompt_global, img], safety_settings=safety, generation_config=fast_config)
                    text = resp.text.strip()
                    st.session_state.estimated_tokens_used += len(text)
                    
                    topic = text.split("TOPIC:")[1].split("SUMMARY:")[0].strip() if "TOPIC:" in text and "SUMMARY:" in text else f"หัวข้อหน้า {target_global+1}"
                    summary = text.split("SUMMARY:")[1].strip() if "SUMMARY:" in text else "ข้อมูลสไลด์"
                    
                    st.session_state.global_data[target_global] = {'topic': topic, 'summary': summary}
                    save_workspace() 
                except Exception as e:
                    st.session_state.global_data[target_global] = {'topic': f"หน้า {target_global+1}", 'summary': ""}
                
                time.sleep(0.1) 
                st.rerun()

        # ==========================================
        # PHASE 2: DETAIL SCAN (ลงรายละเอียดทีละหน้า)
        # ==========================================
        elif st.session_state.phase == 'detail_scan':
            target = None
            is_recheck = False
            
            for i in range(total_pages):
                if i in st.session_state.processed_data and "⚠️" in st.session_state.processed_data[i].get("ai_text", ""):
                    target = i
                    is_recheck = True
                    break
                    
            if target is None:
                target = next((i for i in range(total_pages) if i not in st.session_state.processed_data), None)

            if target is not None:
                is_selected = target in st.session_state.selected_pages
                if not is_selected:
                    st.session_state.processed_data[target] = {"ai_text": "", "user_text": "", "img": doc_in[target].get_pixmap(dpi=50).tobytes("png")}
                    st.rerun()

                if is_recheck:
                    st.session_state.status_mode = 'yellow'
                    icon, msg = "🔄", f"[Phase 2/2] กำลังย้อนกลับไปซ่อมหน้าที่ Error (หน้า {target+1})"
                else:
                    st.session_state.status_mode = 'blue'
                    icon, msg = "⚡", f"[Phase 2/2] กำลังลงรายละเอียดหน้าที่ {target+1} / {total_pages}"
                    
                action_html = f"<div class='status-{st.session_state.status_mode}'><b>{icon} {msg}</b><br>🤖 อิงบริบทจากภาพรวม | สั่งงาน: <code>{active_m}</code></div>"
                action_placeholder.markdown(action_html, unsafe_allow_html=True)
                
                p_img = doc_in[target].get_pixmap(dpi=75)
                img = Image.open(io.BytesIO(p_img.tobytes("png")))

                pattern_parts = []
                if want_content: 
                    content_instruction = (
                        "เนื้อหาหลัก (แบ่งเป็นหัวข้อย่อยดังนี้ เขียนติดขอบซ้ายไม่ต้องเว้นวรรคเข้าข้างใน):\n"
                        "Intro: (เกริ่นนำ 1-2 ประโยคสั้นๆ เพื่อเชื่อมโยงเนื้อหาสไลด์หน้านี้ ให้ลื่นไหลต่อจากหน้าก่อนหน้า อิงจาก Global Context ห้ามใช้คำทักทายเด็ดขาด ให้เหมือนกำลังเล่าเรื่องต่อเนื่อง)\n\n"
                        "Concept หลัก: (สรุปภาษาที่เข้าใจง่ายสุดๆ ไม่วิชาการจ๋าว่าหน้านี้สอนเรื่องอะไร)\n\n"
                        "กลไก/รายละเอียดและอาการ: (อธิบายกลไกการเกิดโรค/อาการ **ต้องมีเหตุผลโดยใช้คำว่า '...เพราะ...' เสมอ**)\n\n"
                        "การนำไปใช้ในคลินิก: (จุดเชื่อมโยงนำไปใช้จริง **และถ้ามีจุดที่มักสับสน ให้แทรกคำว่า 'ระวัง: ...' เพื่อเปรียบเทียบจุดแตกต่าง**)\n"
                    )
                    if want_trick:
                        content_instruction += "\nTrick: (ทริคการจำ, Mnemonic หรือจุดสังเกตที่ข้อมูลต่างจากเพื่อน จัดกลุ่มเชื่อมโยงกัน)\n"
                        
                    pattern_parts.append(content_instruction)
                    
                if want_summary: pattern_parts.append("High-Yield:\n- KEY1: **(คีย์เวิร์ด/จุดตายที่ 1)** (อธิบายด้วยประโยคที่กระชับ อ่านแล้วเข้าใจทันที จำได้นาน)\n- KEY2: **(คีย์เวิร์ด/จุดตายที่ 2)** (อธิบายด้วยประโยคที่กระชับ อ่านแล้วเข้าใจทันที จำได้นาน)")
                if want_quiz: 
                    q_sec = f"Quiz:\nQ1: (คำถามสั้นๆเน้นทบทวนความจำ ไม่ต้องมีตัวเลือก กขคง.)\n\nQ2: (คำถาม)" if quiz_count >= 2 else f"Quiz:\nQ1: (คำถามสั้นๆเน้นทบทวนความจำ ไม่ต้องมีตัวเลือก กขคง.)"
                    if want_answer: q_sec += f"\n\nเฉลย:\nA1: (เฉลยสั้นๆ กระชับ)\n\nA2: (เฉลยสั้นๆ กระชับ)" if quiz_count >= 2 else f"\n\nเฉลย:\nA1: (เฉลยสั้นๆ กระชับ)"
                    pattern_parts.append(q_sec)
                    
                strict_pattern = "\n\n".join(pattern_parts)

                prompt_template = st.session_state.custom_prompt_text
                prompt = prompt_template.replace("{global_context}", st.session_state.global_context_text).replace("{strict_pattern}", strict_pattern).replace("{current_page}", str(target+1)).replace("{total_pages}", str(total_pages))
                
                is_success = False
                retry_count = 0

                while retry_count < 2 and not is_success:
                    try:
                        resp = model.generate_content([prompt, img], safety_settings=safety, generation_config=config)
                        final_text = resp.text.strip()
                        
                        st.session_state.estimated_tokens_used += len(final_text) 
                        
                        if "NON_CONTENT" in final_text:
                            final_text = ""
                        else:
                            if want_summary and "High-Yield:" in final_text:
                                st.session_state.full_summaries += f"\n[Page {target+1}] " + final_text.split("High-Yield:")[-1].split("Quiz:")[0]
                        
                        is_success = True
                        st.session_state.processed_data[target] = {"ai_text": final_text, "user_text": "", "img": p_img.tobytes("png")}
                        
                        save_workspace() 
                        
                    except Exception as e:
                        error_msg = str(e)
                        if "429" in error_msg or "Quota" in error_msg:
                            st.session_state.exhausted_models[active_m] = time.time() + 60
                            st.session_state.status_mode = 'yellow'
                            action_placeholder.markdown(f"<div class='status-yellow'><b>⚠️ `{active_m}` คิวเต็ม!</b><br>🔍 กำลังหาโมเดลสำรอง...</div>", unsafe_allow_html=True)
                            time.sleep(2)
                            
                            new_model = get_best_available_model(st.session_state.flash_models_list)
                            if new_model:
                                active_m = new_model
                                st.session_state.current_active_model = new_model
                                model = genai.GenerativeModel(new_model)
                                retry_count += 1
                            else:
                                st.session_state.status_mode = 'red'
                                action_placeholder.markdown(f"<div class='status-red'><b>🚨 โควต้าเต็มทุกโมเดล (ไม่มีตัวว่าง)</b><br>กด Pause รอ 1 นาทีแล้วกด Continue ครับ</div>", unsafe_allow_html=True)
                                st.session_state.processed_data[target] = {"ai_text": "⚠️ โควต้าเต็มทุกโมเดล (ไม่มีตัวว่าง) กด Pause รอ 1 นาทีแล้วกด Continue ครับ", "user_text": "", "img": p_img.tobytes("png")}
                                is_success = True
                        elif "400" in error_msg:
                            st.session_state.exhausted_models[active_m] = time.time() + 86400 
                            st.session_state.processed_data[target] = {"ai_text": f"⚠️ โมเดล {active_m} ถูกแบนชั่วคราวเนื่องจากไม่อ่านรูป โปรดรอระบบสลับโมเดล", "user_text": "", "img": p_img.tobytes("png")}
                            is_success = True
                        else:
                            st.session_state.processed_data[target] = {"ai_text": f"⚠️ Error: {error_msg}", "user_text": "", "img": p_img.tobytes("png")}
                            is_success = True

                time.sleep(0.1) 
                st.rerun()
            else:
                st.session_state.is_running = False
                st.session_state.phase = 'idle'
                action_placeholder.markdown(f"<div class='status-blue' style='border-left-color: #38A169; color: #2F855A; background: #F0FFF4;'><b>✅ ประมวลผลครบทุกหน้าแล้ว!</b><br>สามารถพิมพ์แก้ไขเนื้อหา หรือกดดาวน์โหลดไฟล์สมบูรณ์ได้เลยครับ</div>", unsafe_allow_html=True)
