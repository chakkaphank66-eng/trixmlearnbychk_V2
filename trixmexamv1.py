import streamlit as st
import fitz  # PyMuPDF
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold, GenerationConfig
from PIL import Image
import io
import time
import markdown
import re
import os
import pickle
import gc
import math

# --- 1. การตั้งค่าเริ่มต้น และ Session State ---
keys_to_init = {
    'processed_data': {},  # เก็บเฉพาะ {'ai_text': '', 'user_text': ''} เพื่อประหยัด RAM
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
    'phase': 'idle',  # idle, global_scan, detail_scan
    'global_data': {},
    'global_context_text': "",
    'fast_index_mode': True,

    # --- ตัวแปรสำหรับหน้าจอเลือกหน้าและโหมดการอ่าน ---
    'customizer_page': 0,
    'quick_review_mode': False,

    # --- ตัวแปรสำหรับ Custom Prompt เนื้อหาติวและข้อสอบ ---
    'use_custom_prompt': False,
    'custom_prompt_text': "",

    # --- ตัวแปรสำหรับ Custom Prompt Summary โค้งสุดท้าย (4 แผ่น) ---
    'use_custom_summary_prompt': False,
    'custom_summary_prompt_1': "",
    'custom_summary_prompt_2': "",
    'custom_summary_prompt_3': "",
    'custom_summary_prompt_4': "",
    'generated_summary_sheets': {},

    # --- ตัวแปรสำหรับระบบดาวน์โหลด PDF ---
    'compiled_pdf_bytes': None,
    'compiled_pdf_size_mb': 0.0
}

for k, v in keys_to_init.items():
    if k not in st.session_state:
        st.session_state[k] = v

st.set_page_config(page_title="MedTutor Exam Master 🎯", layout="wide")

# --- 2. Custom CSS: ออกแบบสีตามลำดับความคิดในการทำข้อสอบ (Exam Cognitive UI) ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');
    
    html, body, [class*="st-"] {
        font-family: 'Sarabun', sans-serif !important;
    }

    .stApp { background-color: #F8FAFC; }
    .main-header { font-size: 2.1rem; font-weight: 800; color: #0F172A; margin-bottom: 0.6rem; letter-spacing: -0.5px; }
    .sub-badge { display: inline-block; background: #DBEAFE; color: #1E40AF; padding: 4px 12px; border-radius: 99px; font-weight: 700; font-size: 0.9rem; margin-bottom: 1rem; }
    .stButton>button { border-radius: 8px; transition: all 0.2s; font-weight: 600; font-family: 'Sarabun', sans-serif !important; }
    .stButton>button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
    
    .edit-box { 
        border: 1px solid #E2E8F0; 
        border-radius: 16px; 
        padding: 20px 24px; 
        background: #FFFFFF; 
        font-size: 16.5px; 
        line-height: 1.75;
        color: #1E293B;
        box-shadow: 0 4px 16px -2px rgba(0, 0, 0, 0.04);
    }
    
    .edit-box strong, .edit-box b { color: #0F172A; font-weight: 700; }
    
    /* กล่องสำหรับโหมดติวเนื้อหาและแกะภาพ (Concept & Visual Tutor) */
    .box-visual { background-color: #EFF6FF; border-left: 5px solid #2563EB; padding: 6px 12px; margin: 8px 0 6px 0; border-radius: 0 6px 6px 0; }
    .box-concept { background-color: #EEF2FF; border-left: 5px solid #4F46E5; padding: 6px 12px; margin: 10px 0 4px 0; border-radius: 0 6px 6px 0; }
    .box-mech { background-color: #F1F5F9; border-left: 5px solid #334155; padding: 6px 12px; margin: 10px 0 4px 0; border-radius: 0 6px 6px 0; }
    .box-trap { background-color: #FFF7ED; border-left: 5px solid #EA580C; padding: 6px 12px; margin: 10px 0 4px 0; border-radius: 0 6px 6px 0; }
    .box-trick { background-color: #FEF9C3; border-left: 5px solid #CA8A04; padding: 6px 12px; margin: 10px 0 4px 0; border-radius: 0 6px 6px 0; }

    /* กล่องสำหรับโหมดผ่าตัดข้อสอบเก่า (Exam Dissection Mode) */
    .box-clue { background-color: #F5F3FF; border-left: 5px solid #7C3AED; padding: 6px 12px; margin: 8px 0 6px 0; border-radius: 0 6px 6px 0; }
    .box-correct { background-color: #ECFDF5; border-left: 5px solid #059669; padding: 6px 12px; margin: 10px 0 6px 0; border-radius: 0 6px 6px 0; }
    .box-wrong { background-color: #FEF2F2; border-left: 5px solid #DC2626; padding: 6px 12px; margin: 10px 0 6px 0; border-radius: 0 6px 6px 0; }

    /* กล่อง High-Yield และ Mini-Quiz */
    .box-hy { background-color: #FFF1F2; border-left: 6px solid #E11D48; padding: 8px 14px; margin: 12px 0 6px 0; border-radius: 0 8px 8px 0; }
    .box-quiz { background-color: #F0F9FF; border-left: 5px solid #0284C7; padding: 6px 12px; margin: 10px 0 4px 0; border-radius: 0 6px 6px 0; }
    .box-ans { background-color: #F0FDF4; border-left: 5px solid #16A34A; padding: 6px 12px; margin: 6px 0 4px 0; border-radius: 0 6px 6px 0; }
    
    details.ans-toggle {
        background: #F0FDF4;
        border: 1px solid #BBF7D0;
        border-radius: 8px;
        padding: 8px 14px;
        margin-top: 8px;
        cursor: pointer;
    }
    details.ans-toggle summary {
        font-weight: 700;
        color: #15803D;
        outline: none;
    }
    
    .edit-box ul, .edit-box ol { margin-top: 0.4rem; margin-bottom: 0.8rem; padding-left: 1.4rem; }
    .edit-box li { margin-bottom: 8px; }
    .edit-box p { margin-bottom: 8px; }
    
    .edit-box table { width: 100%; border-collapse: collapse; margin: 14px 0; border-radius: 8px; overflow: hidden; font-size: 15.5px; }
    .edit-box th { background-color: #F1F5F9; padding: 10px; border-bottom: 2px solid #CBD5E1; color: #334155; text-align: left; }
    .edit-box td { padding: 10px; border-bottom: 1px solid #E2E8F0; }
    
    .status-blue { background: #EBF8FF; border-left: 5px solid #3182CE; color: #2B6CB0; padding: 14px; border-radius: 10px; margin-bottom: 15px;}
    .status-yellow { background: #FFFFF0; border-left: 5px solid #D69E2E; color: #B7791F; padding: 14px; border-radius: 10px; margin-bottom: 15px;}
    .status-red { background: #FFF5F5; border-left: 5px solid #E53E3E; color: #C53030; padding: 14px; border-radius: 10px; margin-bottom: 15px;}
    .status-purple { background: #FAF5FF; border-left: 5px solid #805AD5; color: #553C9A; padding: 14px; border-radius: 10px; margin-bottom: 15px;}
</style>
""", unsafe_allow_html=True)

# --- 3. ฟังก์ชันจัดการหน่วยความจำและคำนวณขนาดฟอนต์อัจฉริยะ ---

WORKSPACE_META_FILE = "autosave_tutor_meta.pkl"
WORKSPACE_PDF_FILE = "autosave_tutor_source.pdf"

def save_workspace(save_pdf_binary=False):
    if save_pdf_binary and st.session_state.pdf_bytes:
        try:
            with open(WORKSPACE_PDF_FILE, "wb") as f_pdf:
                f_pdf.write(st.session_state.pdf_bytes)
        except Exception:
            pass

    clean_processed = {}
    for k, v in st.session_state.processed_data.items():
        clean_processed[k] = {
            "ai_text": v.get("ai_text", ""),
            "user_text": v.get("user_text", "")
        }

    data_to_save = {
        'pdf_name': st.session_state.pdf_name,
        'processed_data': clean_processed,
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
        'use_custom_summary_prompt': st.session_state.use_custom_summary_prompt,
        'generated_summary_sheets': st.session_state.generated_summary_sheets
    }
    try:
        with open(WORKSPACE_META_FILE, "wb") as f:
            pickle.dump(data_to_save, f)
    except Exception:
        pass

def load_workspace():
    if os.path.exists(WORKSPACE_META_FILE) and os.path.exists(WORKSPACE_PDF_FILE):
        try:
            with open(WORKSPACE_PDF_FILE, "rb") as f_pdf:
                st.session_state.pdf_bytes = f_pdf.read()
            with open(WORKSPACE_META_FILE, "rb") as f:
                data = pickle.load(f)
                for k, v in data.items():
                    st.session_state[k] = v
            return True
        except Exception:
            return False
    return False

def clear_workspace():
    for path in [WORKSPACE_META_FILE, WORKSPACE_PDF_FILE]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

@st.cache_data(max_entries=30, show_spinner=False)
def render_page_png(pdf_bytes, page_number, dpi=115):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[page_number]
        pix = page.get_pixmap(dpi=dpi)
        img_bytes = pix.tobytes("png")
    finally:
        doc.close()
    return img_bytes

def build_local_sliding_context(target_idx, window=2):
    lines = []
    sorted_pages = sorted(st.session_state.selected_pages)
    if target_idx in sorted_pages:
        pos = sorted_pages.index(target_idx)
        start_p = max(0, pos - window)
        end_p = min(len(sorted_pages), pos + window + 1)
        near_pages = sorted_pages[start_p:end_p]
    else:
        near_pages = [p for p in sorted_pages if abs(p - target_idx) <= window]

    for idx in near_pages:
        g_info = st.session_state.global_data.get(idx, {})
        topic = g_info.get('topic', f"หน้า {idx+1}")
        summary = g_info.get('summary', "")
        marker = "👉 [หน้าปัจจุบัน]" if idx == target_idx else f"หน้า {idx+1}"
        lines.append(f"- {marker} ({topic}): {summary}")
    return "\n".join(lines) if lines else "ไม่มีข้อมูลบริบทข้างเคียง"

def rebuild_full_summaries():
    chunks = []
    for i in sorted(st.session_state.processed_data.keys()):
        txt = st.session_state.processed_data[i].get("user_text") or st.session_state.processed_data[i].get("ai_text", "")
        if txt and "⚠️" not in txt:
            if "High-Yield:" in txt:
                hy_part = txt.split("High-Yield:")[-1].split("Quiz:")[0].strip()
                chunks.append(f"[หน้า {i+1}] {hy_part}")
            else:
                chunks.append(f"[หน้า {i+1}] {txt[:300]}")
    st.session_state.full_summaries = "\n".join(chunks)

def get_best_available_model(models_list):
    current_time = time.time()
    st.session_state.exhausted_models = {k: v for k, v in st.session_state.exhausted_models.items() if v > current_time}
    preferred = ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash"]
    if not models_list:
        return "gemini-2.5-flash"
    sorted_models = sorted(models_list, key=lambda x: next((i for i, p in enumerate(preferred) if p in x), 99))
    for m in sorted_models:
        if m not in st.session_state.exhausted_models:
            return m
    return sorted_models[0]

def calc_optimal_fontsize(html_text, rect_width, rect_height, is_hy_only=False):
    """
    คำนวณขนาดฟอนต์อัจฉริยะด้วยการจำลองการตัดบรรทัดภาษาไทยจริง (Thai Line-Wrapping Simulator)
    ขยายฟอนต์ High-Yield กรอบล่างให้ใหญ่เต็มพื้นที่กรอบพอดี (สูงสุด 58px)
    """
    if not html_text or rect_width <= 0 or rect_height <= 0:
        return 20

    block_split = re.sub(r'</?(li|p|div|tr|h\d|br)[^>]*>', '\n', html_text)
    raw_lines = [re.sub(r'<[^>]+>', '', ln).strip() for ln in block_split.split('\n')]
    raw_lines = [ln for ln in raw_lines if ln]

    if not raw_lines:
        return 20

    thai_combining = r'[\u0E31\u0E34-\u0E3A\u0E47-\u0E4E]'
    eff_lengths = [max(1, len(re.sub(thai_combining, '', ln))) for ln in raw_lines]
    num_blocks = len(eff_lengths)

    max_f = 58 if is_hy_only else 40
    min_f = 20 if is_hy_only else 13
    char_width_factor = 0.37 if is_hy_only else 0.41
    line_height_factor = 1.35 if is_hy_only else 1.42
    target_fill_ratio = 0.94 if is_hy_only else 0.88

    for f_size in range(max_f, min_f - 1, -1):
        usable_w = max(40.0, rect_width - 20.0)
        chars_per_line = max(8.0, usable_w / (f_size * char_width_factor))

        total_lines = 0.0
        for length in eff_lengths:
            total_lines += math.ceil(length / chars_per_line)

        block_spacing_lines = num_blocks * (0.22 if is_hy_only else 0.28)
        est_height = (total_lines + block_spacing_lines) * (f_size * line_height_factor)

        if est_height <= rect_height * target_fill_ratio:
            return f_size

    return min_f

def split_content_hq(text):
    c_txt, hy_txt, q_txt = "", "", ""
    temp = text
    if "High-Yield:" in temp:
        parts = temp.split("High-Yield:", 1)
        c_txt = parts[0].strip()
        temp = parts[1]
        if "Quiz:" in temp:
            hq_parts = temp.split("Quiz:", 1)
            hy_txt = "High-Yield:\n" + hq_parts[0].strip()
            q_txt = "Quiz:\n" + hq_parts[1].strip()
        else:
            hy_txt = "High-Yield:\n" + temp.strip()
    elif "Quiz:" in temp:
        parts = temp.split("Quiz:", 1)
        c_txt = parts[0].strip()
        q_txt = "Quiz:\n" + parts[1].strip()
    else:
        c_txt = temp.strip()
    return c_txt, hy_txt, q_txt

def get_layout_preview(c_pos, hy_pos, q_pos):
    layout_map = {"ด้านขวา": [], "ด้านล่าง": [], "ด้านซ้าย": [], "ด้านบน": []}
    layout_map[c_pos].append("<span style='color: #1E40AF;'><b>ติวเนื้อหา/ผ่าข้อสอบ</b></span>")
    layout_map[hy_pos].append("<span style='color: #BE123C;'><b>High-Yield (ฟอนต์ใหญ่)</b></span>")
    layout_map[q_pos].append("<span style='color: #0369A1;'><b>Mini-Quiz</b></span>")

    right_box = f"<div style='flex: 0.38; background: #F8FAFC; padding: 5px; font-size: 8px; border-left: 1px solid #E2E8F0;'>{'<br><br>'.join(layout_map['ด้านขวา'])}</div>" if layout_map['ด้านขวา'] else ""
    left_box = f"<div style='flex: 0.38; background: #F8FAFC; padding: 5px; font-size: 8px; border-right: 1px solid #E2E8F0;'>{'<br><br>'.join(layout_map['ด้านซ้าย'])}</div>" if layout_map['ด้านซ้าย'] else ""
    bottom_box = f"<div style='height: 42px; background: #FFF1F2; padding: 5px; font-size: 8px; border-top: 1px solid #FECDD3; text-align: center;'>{' | '.join(layout_map['ด้านล่าง'])}</div>" if layout_map['ด้านล่าง'] else ""
    top_box = f"<div style='height: 40px; background: #F8FAFC; padding: 5px; font-size: 8px; border-bottom: 1px solid #E2E8F0; text-align: center;'>{' | '.join(layout_map['ด้านบน'])}</div>" if layout_map['ด้านบน'] else ""

    html_str = f"""<div style="width: 100%; height: 170px; border-radius: 10px; background: white; border: 2px solid #E2E8F0; display: flex; flex-direction: column; overflow: hidden;">{top_box}<div style="flex: 1; display: flex; flex-direction: row;">{left_box}<div style="flex: 1; background: #F1F5F9; border: 2px dashed #CBD5E1; margin: 6px; display: flex; align-items: center; justify-content: center; font-size: 11px; color: #64748B; font-weight: bold; border-radius: 6px;">สไลด์ติว / โจทย์เก่า</div>{right_box}</div>{bottom_box}</div>"""
    st.markdown(html_str, unsafe_allow_html=True)

def apply_custom_tags(text, for_pdf=False):
    lines = text.split('\n')
    colors = ["#DC2626", "#2563EB", "#059669", "#7C3AED", "#EA580C", "#0891B2", "#DB2777"]
    color_idx = 0
    in_high_yield = False
    new_lines = []

    section_headers = [
        "Quiz:", "Trick:", "จุดที่ข้อสอบชอบหลอก:", "กลไกเชื่อมโยง:",
        "แก่นเนื้อหาที่ใช้สอบ:", "แกะภาพและตาราง:", "สแกนโจทย์หาคำใบ้:",
        "ฟันธงคำตอบ:", "ผ่าตัดช้อยส์หลอก:", "เฉลย:"
    ]

    for line in lines:
        if "High-Yield:" in line or "🚨 High-Yield" in line:
            in_high_yield = True
            color_idx = 0
        elif any(sec in line for sec in section_headers):
            in_high_yield = False

        if in_high_yield:
            if re.match(r'^(\s*[-*]\s|\s*\d+\.\s)', line) or line.strip().upper().startswith("- KEY"):
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

    # ซ่อนเฉลย Mini-Quiz บนหน้าเว็บเพื่อฝึก Active Recall แต่กางออกอัตโนมัติใน PDF
    if not for_pdf and "เฉลย:" in text:
        parts = text.split("เฉลย:", 1)
        before_ans = markdown.markdown(parts[0], extensions=['tables'])
        ans_html = markdown.markdown(parts[1].strip(), extensions=['tables'])
        html = f"{before_ans}<details class='ans-toggle'><summary>🎯 คลิกเพื่อดูเฉลย Mini-Quiz (ฝึกคิดเองก่อนเปิด)</summary><div style='margin-top:8px;'>{ans_html}</div></details>"
    else:
        html = markdown.markdown(text, extensions=['tables'])

    replacements = [
        # --- แท็กสำหรับโหมดติวเนื้อหาและสอนดูภาพ ---
        ("แกะภาพและตาราง:", "<div class='box-visual'><b style='color: #1D4ED8; font-size: 0.96em;'>🖼️ พี่ติวเตอร์พาแกะภาพ & ตาราง (Visual Walkthrough)</b></div>"),
        ("<strong>แกะภาพและตาราง:</strong>", "<div class='box-visual'><b style='color: #1D4ED8; font-size: 0.96em;'>🖼️ พี่ติวเตอร์พาแกะภาพ & ตาราง (Visual Walkthrough)</b></div>"),

        ("แก่นเนื้อหาที่ใช้สอบ:", "<div class='box-concept'><b style='color: #4338CA; font-size: 0.96em;'>🎯 แก่นเนื้อหาที่ใช้สอบ (Core Exam Concept)</b></div>"),
        ("<strong>แก่นเนื้อหาที่ใช้สอบ:</strong>", "<div class='box-concept'><b style='color: #4338CA; font-size: 0.96em;'>🎯 แก่นเนื้อหาที่ใช้สอบ (Core Exam Concept)</b></div>"),

        ("กลไกเชื่อมโยง:", "<div class='box-mech'><b style='color: #334155; font-size: 0.96em;'>⚡ กลไกและเหตุผลเชื่อมโยง (Why & How)</b></div>"),
        ("<strong>กลไกเชื่อมโยง:</strong>", "<div class='box-mech'><b style='color: #334155; font-size: 0.96em;'>⚡ กลไกและเหตุผลเชื่อมโยง (Why & How)</b></div>"),

        ("จุดที่ข้อสอบชอบหลอก:", "<div class='box-trap'><b style='color: #C2410C; font-size: 0.96em;'>💣 จุดที่ข้อสอบชอบหลอก & แยกโรค (Exam Traps & DDx)</b></div>"),
        ("<strong>จุดที่ข้อสอบชอบหลอก:</strong>", "<div class='box-trap'><b style='color: #C2410C; font-size: 0.96em;'>💣 จุดที่ข้อสอบชอบหลอก & แยกโรค (Exam Traps & DDx)</b></div>"),

        ("Trick:", "<div class='box-trick'><b style='color: #A16207; font-size: 0.96em;'>💡 Trick จำเข้าห้องสอบ</b></div>"),
        ("<strong>Trick:</strong>", "<div class='box-trick'><b style='color: #A16207; font-size: 0.96em;'>💡 Trick จำเข้าห้องสอบ</b></div>"),

        # --- แท็กสำหรับโหมดผ่าตัดข้อสอบเก่า (Exam Dissection Mode) ---
        ("สแกนโจทย์หาคำใบ้:", "<div class='box-clue'><b style='color: #6D28D9; font-size: 0.96em;'>🔍 สแกนโจทย์หาคำใบ้ & แปลผลภาพในโจทย์ (Clue Hunter)</b></div>"),
        ("<strong>สแกนโจทย์หาคำใบ้:</strong>", "<div class='box-clue'><b style='color: #6D28D9; font-size: 0.96em;'>🔍 สแกนโจทย์หาคำใบ้ & แปลผลภาพในโจทย์ (Clue Hunter)</b></div>"),

        ("ฟันธงคำตอบ:", "<div class='box-correct'><b style='color: #047857; font-size: 0.96em;'>✅ ฟันธงคำตอบ & เหตุผลเชิงลึก (Why Correct)</b></div>"),
        ("<strong>ฟันธงคำตอบ:</strong>", "<div class='box-correct'><b style='color: #047857; font-size: 0.96em;'>✅ ฟันธงคำตอบ & เหตุผลเชิงลึก (Why Correct)</b></div>"),

        ("ผ่าตัดช้อยส์หลอก:", "<div class='box-wrong'><b style='color: #B91C1C; font-size: 0.96em;'>❌ ผ่าตัดช้อยส์หลอก & ถ้าจะตอบช้อยส์นั้นโจทย์ต้องถามอะไร</b></div>"),
        ("<strong>ผ่าตัดช้อยส์หลอก:</strong>", "<div class='box-wrong'><b style='color: #B91C1C; font-size: 0.96em;'>❌ ผ่าตัดช้อยส์หลอก & ถ้าจะตอบช้อยส์นั้นโจทย์ต้องถามอะไร</b></div>"),

        # --- แท็ก High-Yield และ Mini-Quiz ---
        ("High-Yield:", "<div class='box-hy'><b style='color: #BE123C; font-size: 1.02em;'>🚨 High-Yield กฎเหล็กทำข้อสอบ (จำไปใช้ทันที)</b></div>"),
        ("<strong>High-Yield:</strong>", "<div class='box-hy'><b style='color: #BE123C; font-size: 1.02em;'>🚨 High-Yield กฎเหล็กทำข้อสอบ (จำไปใช้ทันที)</b></div>"),

        ("Quiz:", "<div class='box-quiz'><b style='color: #0369A1; font-size: 0.95em;'>📝 เก็งข้อสอบเพิ่มจากหน้านี้ (Active Recall)</b></div>"),
        ("<strong>Quiz:</strong>", "<div class='box-quiz'><b style='color: #0369A1; font-size: 0.95em;'>📝 เก็งข้อสอบเพิ่มจากหน้านี้ (Active Recall)</b></div>"),

        ("เฉลย:", "<div class='box-ans'><b style='color: #15803D; font-size: 0.95em;'>🎯 เฉลย</b></div>"),
        ("<strong>เฉลย:</strong>", "<div class='box-ans'><b style='color: #15803D; font-size: 0.95em;'>🎯 เฉลย</b></div>"),
    ]

    for old, new in replacements:
        html = html.replace(old, new)
        html = html.replace(f"<p>{new}</p>", new)

    return html

def generate_all_4_summary_sheets(status_callback=None):
    """สร้างสรุปโค้งสุดท้าย 4 แผ่นอัตโนมัติสำหรับแนบท้าย PDF"""
    rebuild_full_summaries()
    if not st.session_state.full_summaries.strip():
        return False

    model_os = genai.GenerativeModel(get_best_available_model(st.session_state.flash_models_list))
    safety = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE
    }
    data_chunk = st.session_state.full_summaries[:120000]
    prompt_keys = [
        ("custom_summary_prompt_1", "แผ่นที่ 1: ตารางคำใบ้โจทย์ (Exam Buzzwords ➡️ โรค)"),
        ("custom_summary_prompt_2", "แผ่นที่ 2: คู่มือแปลผลภาพและ Lab ที่ออกสอบ"),
        ("custom_summary_prompt_3", "แผ่นที่ 3: ตารางผ่าช้อยส์หลอก & แยกโรคคู่แฝด (DDx)"),
        ("custom_summary_prompt_4", "แผ่นที่ 4: สรุป First-line, Gold Standard & Management")
    ]
    for idx, (pk, label) in enumerate(prompt_keys, start=1):
        if status_callback:
            status_callback(idx, f"กำลังสกัดสรุปโค้งสุดท้าย {label} ({idx}/4)...")
        p_tmpl = getattr(st.session_state, pk)
        p_sheet = p_tmpl.replace("{full_summaries}", data_chunk)
        try:
            os_res = model_os.generate_content(p_sheet, safety_settings=safety)
            st.session_state.generated_summary_sheets[idx] = os_res.text.strip()
        except Exception as e:
            st.session_state.generated_summary_sheets[idx] = f"ไม่สามารถสร้าง {label} ได้ในขณะนี้ ({e})"
        time.sleep(0.4)
    save_workspace()
    return True

# --- 4. Sidebar: Exam Tutor Settings ---
with st.sidebar:
    st.markdown("<h2 style='color: #1E293B;'>🎯 Exam Tutor Settings</h2>", unsafe_allow_html=True)
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
            if not st.session_state.flash_models_list:
                all_models = [m.name.replace("models/", "") for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                flash_models = [m for m in all_models if "flash-lite" in m.lower() or "3.1" in m.lower() or "flash" in m.lower()]
                if not flash_models:
                    flash_models = ["gemini-2.5-flash"]
                flash_models = sorted(flash_models, key=lambda x: 0 if "3.1-flash-lite" in x else (1 if "2.5-flash-lite" in x else 2))
                st.session_state.flash_models_list = flash_models

            if is_locked:
                st.info("🔒 ระบบล็อกการตั้งค่าขณะรัน")
            else:
                display_options = []
                model_map = {}
                for m in st.session_state.flash_models_list:
                    status = "⏳ [รอ]" if m in st.session_state.exhausted_models else "✅ [พร้อม]"
                    opt = f"{status} {m}"
                    display_options.append(opt)
                    model_map[opt] = m
                selected_display = st.selectbox("AI Model (สลับอัตโนมัติ):", display_options, index=0)
                st.session_state.current_active_model = model_map[selected_display]
        except Exception:
            st.error("API Key ไม่ถูกต้อง หรือไม่สามารถดึงรายชื่อโมเดลได้")

    st.markdown("### 💳 Token Tracker")
    token_used = st.session_state.estimated_tokens_used
    st.progress(min(token_used / 1000000, 1.0))
    st.caption(f"ใช้ไปแล้ว: **{token_used:,} Tokens**")

    st.divider()
    med_year = st.selectbox("ระดับชั้น / เป้าหมายการสอบ", ["นสพ. ปี 4 (NL1 / Ward)", "นสพ. ปี 5 (Clinical)", "นสพ. ปี 6 (NL2 / Comprehensive)", "นสพ. พรีคลินิก (ปี 2-3)"], index=0, disabled=is_locked)
    max_tokens = st.number_input("กำหนด Max Output Tokens", min_value=100, max_value=8192, value=4500, step=500, disabled=is_locked)

    st.session_state.fast_index_mode = st.checkbox(
        "⚡ สแกนโครงสร้างสไลด์ความเร็วสูง (0.1 วินาที)",
        value=st.session_state.fast_index_mode,
        disabled=is_locked
    )

    st.markdown("### 📐 จัดสรรพื้นที่กระดาษ (Layout)")
    margin_side_pct = st.slider("ขยายพื้นที่ด้านข้าง (%)", 0, 100, 48, disabled=is_locked)
    margin_vert_pct = st.slider("ขยายพื้นที่ด้านบน/ล่าง (%)", 0, 100, 45, disabled=is_locked)

    pos_options = ["ด้านขวา", "ด้านล่าง", "ด้านซ้าย", "ด้านบน"]
    content_pos = st.selectbox("วาง [คำอธิบายติว/ผ่าข้อสอบ] ไว้ที่:", pos_options, index=0, disabled=is_locked)
    hy_pos = st.selectbox("วาง [High-Yield ฟอนต์ใหญ่] ไว้ที่:", pos_options, index=1, disabled=is_locked)
    quiz_pos = st.selectbox("วาง [Mini-Quiz เก็งข้อสอบ] ไว้ที่:", pos_options, index=0, disabled=is_locked)

    st.markdown("### 📋 ข้อมูลที่ต้องการให้พี่ติวเตอร์สรุป")
    want_content = st.checkbox("คำอธิบายติวเนื้อหา + แกะภาพ + ผ่าโจทย์ข้อสอบ", value=True, disabled=is_locked)
    want_summary = st.checkbox("สรุป High-Yield กฎเหล็กทำข้อสอบ (ฟอนต์ใหญ่)", value=True, disabled=is_locked)
    want_trick = st.checkbox("💡 ทริคจำเข้าห้องสอบ (Trick)", value=True, disabled=is_locked)
    want_quiz = st.checkbox("Mini-Quiz เก็งข้อสอบเพิ่ม", value=True, disabled=is_locked)

    quiz_count = 2
    want_answer = True
    if want_quiz:
        quiz_count = st.slider("จำนวนข้อ Mini-Quiz:", 1, 4, 2, disabled=is_locked)
        want_answer = st.checkbox("รวมเฉลยและเหตุผล", value=True, disabled=is_locked)

    get_layout_preview(content_pos, hy_pos, quiz_pos)

    # 🌟 ระบบ Prompt อัจฉริยะ Dual-Mode (แยกหน้าเนื้อหาติว vs หน้าโจทย์ข้อสอบเก่าอัตโนมัติ)
    st.markdown("### 🛠️ ปรับแต่ง Prompt ติวเตอร์อัจฉริยะ")
    use_custom_prompt = st.checkbox("เปิดใช้งานแก้ไข Prompt หลัก", value=st.session_state.use_custom_prompt, disabled=is_locked)

    base_prompt_template = f"""คุณคืออาจารย์แพทย์และรุ่นพี่ติวเตอร์มือหนึ่ง กำลังติวข้อสอบและเนื้อหาเข้มข้นให้ {med_year}
เป้าหมายสูงสุด: **เปลี่ยนเรื่องยากให้เข้าใจง่าย อธิบายภาพแทนคนสอน ดึงแก่นที่ใช้สอบจริง และผ่าตัดโจทย์ข้อสอบเก่าให้ทะลุปรุโปร่ง**

**บริบทหน้าใกล้เคียง:**
{{global_context}}

**กฎเหล็ก 6 ข้อ (ต้องทำตามอย่างเคร่งครัด):**
1. **ห้ามทักทาย ห้ามเกริ่นนำ** เขียนชิดขอบซ้ายทันที
2. **เน้นตัวหนาที่คำสำคัญ (Keywords / Buzzwords) เสมอ** เพื่อให้กวาดสายตาจับจุดออกสอบได้ทันที
3. **ทุกกลไกและทุกการเฉลยข้อสอบ ต้องให้เหตุผลด้วยคำว่า '...เพราะ...' เสมอ** เพื่อให้เข้าใจถึงแก่นและจำได้นานโดยไม่ต้องท่องจำดิบๆ
4. **ช่วยอธิบายภาพและตารางอย่างละเอียดแต่กระชับ:** เพราะผู้อ่านอ่านคนเดียวไม่มีคนสอน หากสไลด์มีรูปภาพ (X-ray, CT, ECG, Patho, ผื่น, ไดอะแกรม) หรือตาราง ต้องชี้เป้าว่าให้มองตรงไหน เห็นลักษณะอะไร และแปลผลอย่างไร
5. **ใช้ลูกศรเชื่อมลำดับความคิด:** เขียนในรูปแบบ `คำใบ้/สาเหตุ ➡️ กลไก ➡️ คำตอบ/การรักษา (**เพราะ...**)`
6. **แยกโหมดอัตโนมัติตามเนื้อหาในสไลด์ (Dual-Mode Detection):**
   - ถ้านี่คือ **"หน้าสรุปเนื้อหา / รูปภาพ / ตาราง"** ให้ใช้ **โหมดที่ 1 (ติวเนื้อหาเข้มข้น)**
   - ถ้านี่คือ **"หน้าโจทย์ข้อสอบเก่า / คำถามคลินิก (Clinical Vignette) / ช้อยส์ A-E"** ให้สลับไปใช้ **โหมดที่ 2 (ผ่าตัดข้อสอบเก่า)** ทันที!
   - ถ้าเป็นหน้าปกหรือหน้าว่างไม่มีเนื้อหาวิชาการ ให้ตอบแค่ 'NON_CONTENT'

{{strict_pattern}}"""

    if use_custom_prompt:
        custom_prompt_text = st.text_area(
            "แก้ไข Prompt (ห้ามลบตัวแปรที่มีวงเล็บปีกกา {})",
            value=st.session_state.custom_prompt_text if st.session_state.custom_prompt_text else base_prompt_template,
            height=280,
            disabled=is_locked
        )
        st.session_state.custom_prompt_text = custom_prompt_text
    else:
        st.session_state.custom_prompt_text = base_prompt_template

    st.session_state.use_custom_prompt = use_custom_prompt

    # 🌟 ระบบ Prompt สำหรับ 4 แผ่นสรุปโค้งสุดท้ายหน้าห้องสอบ (Exam Cram Sheets)
    st.markdown("### 📝 ปรับแต่ง Prompt สรุปโค้งสุดท้าย 4 แผ่นท้ายเล่ม")
    use_custom_summary_prompt = st.checkbox("เปิดใช้งานแก้ไข Prompt สรุป 4 แผ่น", value=st.session_state.use_custom_summary_prompt, disabled=is_locked)

    default_summary_prompt_1 = f"""สร้างแผ่นสรุปโค้งสุดท้าย แผ่นที่ 1 (Exam Buzzwords & Classic Clues: โจทย์ให้คำใบ้นี้ ตอบโรคอะไร) สำหรับ {med_year}:
- จัดทำเป็น **Markdown Table** จับคู่ระหว่าง: **คำใบ้สำคัญในโจทย์ (Classic Buzzwords / อาการเด่น)** | **โรค/ภาวะที่ต้องนึกถึงทันที** | **เหตุผลและกลไกสำคัญ (...เพราะ...)**
- เน้น **ตัวหนาที่คำสำคัญ** ทุกจุด
ข้อมูลอ้างอิง:
{{full_summaries}}"""

    default_summary_prompt_2 = f"""สร้างแผ่นสรุปโค้งสุดท้าย แผ่นที่ 2 (Visual, Imaging & Lab Interpretation Guide: คู่มือดูภาพและแปลผลตรวจที่ใช้สอบ) สำหรับ {med_year}:
- รวบรวมจุดสังเกตภาพตรวจพิเศษ (X-ray, CT, ECG, Patho, ผื่น, กราฟ) และผล Lab สำคัญทั้งหมดในเอกสารชุดนี้
- อธิบายว่า **เห็นลักษณะอะไรบนภาพ/Lab ➡️ แปลผลว่าอะไร (**เพราะ...**) ➡️ ต้องระวังสับสนกับอะไร**
ข้อมูลอ้างอิง:
{{full_summaries}}"""

    default_summary_prompt_3 = f"""สร้างแผ่นสรุปโค้งสุดท้าย แผ่นที่ 3 (Kill-Switch DDx & Exam Traps: ตารางผ่าช้อยส์หลอกและแยกโรคคู่แฝด) สำหรับ {med_year}:
1. **ตารางเปรียบเทียบโรคคู่แฝด (Markdown Table):** เปรียบเทียบโรคที่ข้อสอบชอบนำมาออกเป็นช้อยส์หลอกคู่กัน โดยชี้ **จุดตัด (Kill-switch clue)** ที่ใช้ฟันธงแยกโรค
2. **รวมหลุมพรางข้อสอบ (Common Exam Pitfalls):** จุดที่คนทำข้อสอบมักโดนหลอกบ่อยที่สุดพร้อมวิธีแก้ทาง
ข้อมูลอ้างอิง:
{{full_summaries}}"""

    default_summary_prompt_4 = f"""สร้างแผ่นสรุปโค้งสุดท้าย แผ่นที่ 4 (Next Best Step Algorithm: สรุปการส่งตรวจยืนยันและการรักษา) สำหรับ {med_year}:
- สรุปเป็นตารางหรือลำดับลูกศรชัดเจน: **โรค/ภาวะ** ➡️ **Initial Test (ส่งทำไม)** ➡️ **Gold Standard Test** ➡️ **First-line Management / Drug of Choice (พร้อมผลข้างเคียงสำคัญ และเหตุผล ...เพราะ...)**
ข้อมูลอ้างอิง:
{{full_summaries}}"""

    if use_custom_summary_prompt:
        st.session_state.custom_summary_prompt_1 = st.text_area("Prompt แผ่นที่ 1 (Buzzwords)", value=st.session_state.custom_summary_prompt_1 or default_summary_prompt_1, height=130, disabled=is_locked)
        st.session_state.custom_summary_prompt_2 = st.text_area("Prompt แผ่นที่ 2 (Visual/Lab)", value=st.session_state.custom_summary_prompt_2 or default_summary_prompt_2, height=130, disabled=is_locked)
        st.session_state.custom_summary_prompt_3 = st.text_area("Prompt แผ่นที่ 3 (DDx/Traps)", value=st.session_state.custom_summary_prompt_3 or default_summary_prompt_3, height=130, disabled=is_locked)
        st.session_state.custom_summary_prompt_4 = st.text_area("Prompt แผ่นที่ 4 (Management)", value=st.session_state.custom_summary_prompt_4 or default_summary_prompt_4, height=130, disabled=is_locked)
    else:
        st.session_state.custom_summary_prompt_1 = default_summary_prompt_1
        st.session_state.custom_summary_prompt_2 = default_summary_prompt_2
        st.session_state.custom_summary_prompt_3 = default_summary_prompt_3
        st.session_state.custom_summary_prompt_4 = default_summary_prompt_4

    st.session_state.use_custom_summary_prompt = use_custom_summary_prompt

    if st.button("💾 บันทึกการตั้งค่า Prompt", use_container_width=True):
        save_workspace()
        st.toast("บันทึกการตั้งค่า Prompt เรียบร้อยแล้ว!")

    current_settings = {
        "year": med_year, "max_tok": max_tokens,
        "m_side": margin_side_pct, "m_vert": margin_vert_pct,
        "c_pos": content_pos, "hy_pos": hy_pos, "q_pos": quiz_pos,
        "content": want_content, "summary": want_summary, "quiz": want_quiz, "count": quiz_count, "ans": want_answer,
        "trick": want_trick
    }
    if not is_locked and st.session_state.last_settings and current_settings != st.session_state.last_settings:
        st.session_state.settings_changed_alert = True
    st.session_state.last_settings = current_settings

# --- 5. หน้าหลัก: การจัดการไฟล์ ---
st.markdown("<div class='main-header'>🎯 MedTutor Exam Master: แอปติวเนื้อหา & ผ่าตัดข้อสอบเก่า</div>", unsafe_allow_html=True)
st.markdown("<div class='sub-badge'>✨ แยกโหมดอัตโนมัติ: สอนแกะภาพและสรุปแก่นเนื้อหา + ผ่าตัดช้อยส์ข้อสอบเก่าทีละข้อ</div>", unsafe_allow_html=True)

if not st.session_state.pdf_bytes:
    if os.path.exists(WORKSPACE_META_FILE) and os.path.exists(WORKSPACE_PDF_FILE):
        st.info("💾 **พบไฟล์ติวที่ทำค้างไว้!** (ระบบ Auto-save ความเร็วสูง รองรับมากกว่า 100 หน้า)")
        if st.button("🔄 กู้คืนงานติวที่ทำค้างไว้", type="primary"):
            with st.spinner("กำลังโหลดข้อมูล..."):
                if load_workspace():
                    st.success("กู้คืนสำเร็จ!")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("ไฟล์กู้คืนมีปัญหา")

    uploaded_file = st.file_uploader("อัปโหลดไฟล์ชีทติว หรือรวมข้อสอบเก่า (PDF) - รองรับ 100–400+ หน้าโดยไม่ค้าง", type="pdf")
    if uploaded_file:
        with st.status(f"กำลังนำเข้าชีทติว: {uploaded_file.name}...", expanded=True) as status:
            st.session_state.pdf_bytes = uploaded_file.getvalue()
            st.session_state.pdf_name = uploaded_file.name
            doc_tmp = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
            total_p = len(doc_tmp)
            doc_tmp.close()
            st.session_state.selected_pages = list(range(total_p))
            save_workspace(save_pdf_binary=True)
            status.update(label=f"✅ อัปโหลดสำเร็จ: {uploaded_file.name} ({total_p} หน้า)", state="complete")
        st.rerun()
else:
    doc_meta = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
    total_pages = len(doc_meta)
    doc_meta.close()

    col_info1, col_info2 = st.columns([3, 1])
    with col_info1:
        st.info(f"📄 ไฟล์ติวปัจจุบัน: **{st.session_state.pdf_name}** (ทั้งหมด **{total_pages} หน้า** | ติวเสร็จแล้ว **{len(st.session_state.processed_data)} หน้า**)")
    with col_info2:
        if st.button("🗑️ เปลี่ยนเอกสาร (Reset)", use_container_width=True):
            st.session_state.show_reset_confirm = True

    if st.session_state.show_reset_confirm:
        st.warning("ยืนยันการล้างข้อมูลทั้งหมด?")
        c1, c2 = st.columns(2)
        if c1.button("✅ ยืนยันล้างข้อมูล", type="primary"):
            clear_workspace()
            st.cache_data.clear()
            for k in list(keys_to_init.keys()):
                if k in st.session_state:
                    del st.session_state[k]
            st.rerun()
        if c2.button("❌ ยกเลิก"):
            st.session_state.show_reset_confirm = False
            st.rerun()

# --- 6. ระบบเลือกหน้าแบบแบ่งเพจ (Paginated Page Customizer) ---
if st.session_state.pdf_bytes and not is_locked:
    if "expander_open" not in st.session_state:
        st.session_state.expander_open = False

    if st.session_state.expander_open:
        with st.expander(f"🖼️ เลือกหน้าที่ต้องการให้พี่ติวเตอร์อธิบาย (เลือกไว้ {len(st.session_state.selected_pages)}/{total_pages} หน้า)", expanded=True):
            c_btn1, c_btn2, c_btn3, c_btn4 = st.columns([1, 1, 2, 1.5])
            if c_btn1.button("✅ เลือกทั้งหมด", use_container_width=True):
                st.session_state.selected_pages = list(range(total_pages))
                st.rerun()
            if c_btn2.button("❌ ล้างที่เลือก", use_container_width=True):
                st.session_state.selected_pages = []
                st.rerun()
            with c_btn3:
                range_input = st.text_input("ระบุช่วงหน้า (เช่น 1-50, 55, 60-120):", label_visibility="collapsed", placeholder="ระบุช่วงหน้า เช่น 1-50, 60-100")
            if c_btn4.button("🎯 เลือกตามช่วงที่ระบุ", use_container_width=True) and range_input:
                new_sel = set()
                for part in range_input.split(","):
                    part = part.strip()
                    if "-" in part:
                        try:
                            s, e = map(int, part.split("-"))
                            new_sel.update(range(max(0, s - 1), min(total_pages, e)))
                        except Exception:
                            pass
                    elif part.isdigit():
                        idx_p = int(part) - 1
                        if 0 <= idx_p < total_pages:
                            new_sel.add(idx_p)
                if new_sel:
                    st.session_state.selected_pages = sorted(list(new_sel))
                    st.rerun()

            ITEMS_PER_PAGE = 20
            max_cust_pages = max(1, math.ceil(total_pages / ITEMS_PER_PAGE))
            c_p1, c_p2, c_p3 = st.columns([1, 2, 1])
            with c_p2:
                cust_page = st.number_input(f"ดูตัวอย่างสไลด์ชุดที่ (1 - {max_cust_pages}):", min_value=1, max_value=max_cust_pages, value=st.session_state.customizer_page + 1) - 1
                st.session_state.customizer_page = cust_page

            start_idx = cust_page * ITEMS_PER_PAGE
            end_idx = min(total_pages, start_idx + ITEMS_PER_PAGE)

            doc_thumb = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
            cols_per_row = 5
            for row_idx in range(start_idx, end_idx, cols_per_row):
                cols = st.columns(cols_per_row)
                for col_idx in range(cols_per_row):
                    page_num = row_idx + col_idx
                    if page_num < end_idx:
                        with cols[col_idx]:
                            pix = doc_thumb[page_num].get_pixmap(dpi=36)
                            st.image(pix.tobytes("png"), use_container_width=True)
                            is_checked = st.checkbox(f"หน้า {page_num+1}", value=(page_num in st.session_state.selected_pages), key=f"sel_chk_{page_num}")
                            if is_checked and page_num not in st.session_state.selected_pages:
                                st.session_state.selected_pages.append(page_num)
                            elif not is_checked and page_num in st.session_state.selected_pages:
                                st.session_state.selected_pages.remove(page_num)
            doc_thumb.close()

            if st.button("💾 ยืนยันการเลือกหน้าและพับเก็บ", type="primary", use_container_width=True):
                st.session_state.expander_open = False
                save_workspace()
                st.rerun()
    else:
        if st.button(f"⚙️ ตั้งค่าเลือกหน้าสไลด์ติว (ปัจจุบันเลือกไว้ {len(st.session_state.selected_pages)}/{total_pages} หน้า)"):
            st.session_state.expander_open = True
            st.rerun()

# --- 7. แถบสถานะและปุ่มควบคุมการทำงาน ---
if st.session_state.pdf_bytes:
    if st.session_state.settings_changed_alert and not st.session_state.is_running:
        st.warning("🔔 ตรวจพบการเปลี่ยนการตั้งค่า: หน้าถัดไปจะใช้รูปแบบใหม่ทันที")
        if st.button("รับทราบ"):
            st.session_state.settings_changed_alert = False
            st.rerun()

    if st.session_state.show_start_popup:
        with st.container():
            st.markdown("### 📊 สรุปข้อมูลก่อนเริ่มติวและผ่าข้อสอบ")
            pages_to_do = len([i for i in st.session_state.selected_pages if i not in st.session_state.processed_data])
            est_tokens = pages_to_do * 1300
            st.info(f"""
            - หน้าที่ต้องประมวลผลเพิ่ม: **{pages_to_do} หน้า**
            - โหมดตรวจจับอัตโนมัติ: **สลับระหว่าง [ติวเนื้อหา+แกะภาพ] และ [ผ่าตัดโจทย์ข้อสอบเก่า] อัตโนมัติ**
            - คาดการณ์ Token ที่ต้องใช้: **~{est_tokens:,} Tokens**
            """)
            c_start1, c_start2 = st.columns(2)
            if c_start1.button("✅ ยืนยันเริ่มติว", type="primary"):
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

    col_run1, col_ctrl2, col_ctrl3 = st.columns([1, 1, 1.5])
    if col_run1.button("🚀 Start / Continue ติวต่อ", type="primary", disabled=is_locked, use_container_width=True):
        st.session_state.show_start_popup = True
        st.rerun()
    if col_ctrl2.button("🛑 Stop / Pause", disabled=not st.session_state.is_running, use_container_width=True):
        st.session_state.is_running = False
        st.session_state.stop_clicked = True
        save_workspace()
        st.rerun()
    with col_ctrl3:
        st.session_state.quick_review_mode = st.toggle(
            "⚡ โหมดทวนด่วนหน้าห้องสอบ (แสดงเฉพาะ สไลด์ + High-Yield + Quiz)",
            value=st.session_state.quick_review_mode
        )

    # --- 8. INTERACTIVE TUTOR READER & EDITING ---
    st.write("---")
    st.subheader(f"📖 ห้องติวเข้มข้น: หน้า {st.session_state.page_idx + 1} / {total_pages}")

    c_nav1, c_nav2, c_nav3 = st.columns([1, 2.5, 1])
    with c_nav1:
        if st.button("⬅️ หน้าก่อนหน้า", use_container_width=True) and st.session_state.page_idx > 0:
            st.session_state.page_idx -= 1
            st.rerun()
    with c_nav2:
        new_page = st.slider("กระโดดไปหน้า:", 1, total_pages, st.session_state.page_idx + 1, label_visibility="collapsed")
        if new_page - 1 != st.session_state.page_idx:
            st.session_state.page_idx = new_page - 1
            st.rerun()
    with c_nav3:
        if st.button("หน้าถัดไป ➡️", use_container_width=True) and st.session_state.page_idx < total_pages - 1:
            st.session_state.page_idx += 1
            st.rerun()

    curr = st.session_state.page_idx
    col_v1, col_v2 = st.columns([1.15, 1])

    with col_v1:
        curr_img_bytes = render_page_png(st.session_state.pdf_bytes, curr, dpi=120)
        st.image(curr_img_bytes, use_container_width=True, caption=f"สไลด์ติว / โจทย์ข้อสอบ หน้า {curr + 1}")

    with col_v2:
        if curr in st.session_state.processed_data:
            data = st.session_state.processed_data[curr]
            if f"editing_{curr}" not in st.session_state:
                st.session_state[f"editing_{curr}"] = False
            display_text = data.get("user_text") if data.get("user_text") else data.get("ai_text", "")

            if st.session_state[f"editing_{curr}"]:
                edited = st.text_area("แก้ไขบันทึกการติว:", value=display_text, height=420)
                ce1, ce2 = st.columns(2)
                if ce1.button("💾 ยืนยันการแก้ไข", type="primary", use_container_width=True):
                    st.session_state.processed_data[curr]["user_text"] = edited
                    st.session_state[f"editing_{curr}"] = False
                    rebuild_full_summaries()
                    save_workspace()
                    st.rerun()
                if ce2.button("🔄 คืนค่าต้นฉบับ AI", use_container_width=True):
                    st.session_state.processed_data[curr]["user_text"] = ""
                    st.session_state[f"editing_{curr}"] = False
                    rebuild_full_summaries()
                    save_workspace()
                    st.rerun()
            else:
                if not display_text.strip():
                    st.info("ℹ️ หน้านี้ไม่มีเนื้อหาวิชาการ หรือไม่ได้เลือกประมวลผล")
                else:
                    text_to_render = display_text
                    if st.session_state.quick_review_mode:
                        c_part, hy_part, q_part = split_content_hq(display_text)
                        key_lines = [
                            line for line in c_part.split("\n")
                            if any(k in line for k in ["แกะภาพและตาราง:", "แก่นเนื้อหาที่ใช้สอบ:", "สแกนโจทย์หาคำใบ้:", "ฟันธงคำตอบ:"])
                        ]
                        short_head = "\n\n".join(key_lines)
                        text_to_render = "\n\n".join([p for p in [short_head, hy_part, q_part] if p.strip()])

                    html_content = apply_custom_tags(text_to_render, for_pdf=False)
                    st.markdown(f"<div class='edit-box'>{html_content}</div>", unsafe_allow_html=True)

                if st.button("✏️ พิมพ์แก้ไขเนื้อหาหน้านี้"):
                    st.session_state[f"editing_{curr}"] = True
                    if st.session_state.is_running:
                        st.session_state.is_running = False
                        st.warning("⚠️ หยุดรันชั่วคราวเพื่อให้แก้ไขได้สะดวก กด Continue เพื่อรันต่อ")
                    st.rerun()
        else:
            st.info(f"⏳ หน้าที่ {curr+1} ยังไม่ได้ประมวลผล (อยู่ในคิว)...")

    # --- 9. ระบบสร้างไฟล์ PDF ฉบับสมบูรณ์ (แนบสรุปโค้งสุดท้าย 4 แผ่นอัตโนมัติ + บีบอัดเล็กสุดเป็นค่าเริ่มต้น) ---
    st.write("---")
    if len(st.session_state.processed_data) > 0:
        st.subheader("📦 จัดทำและดาวน์โหลดไฟล์ PDF คัมภีร์ติวสอบ (พร้อมสรุปโค้งสุดท้าย 4 แผ่นท้ายเล่ม)")

        col_opt1, col_opt2 = st.columns([1.4, 1])
        with col_opt1:
            comp_level = st.selectbox(
                "🗜️ ระดับการบีบอัดไฟล์ PDF (ตั้งค่าเริ่มต้นที่เล็กที่สุดเพื่อประหยัดพื้นที่เครื่อง):",
                [
                    "1. บีบอัดขั้นสุด (ไฟล์เล็กที่สุด ประหยัดพื้นที่เครื่องสูงสุด - ค่าเริ่มต้น)",
                    "2. บีบอัดสมดุล (ขนาดปานกลาง ความคมชัดสูง)",
                    "3. บีบอัดน้อย (รักษาคุณภาพภาพต้นฉบับสูงสุด)"
                ],
                index=0
            )
        with col_opt2:
            include_4_sheets = st.checkbox("✅ แนบสรุปเก็งข้อสอบ 4 แผ่นต่อท้ายไฟล์ PDF", value=True)
            force_regen_sheets = st.checkbox("🔄 บังคับให้ AI เขียนสรุป 4 แผ่นใหม่ทั้งหมด", value=False)

        if st.button("📦 รวบรวมและประกอบไฟล์ PDF ฉบับสมบูรณ์ (พร้อมสรุปโค้งสุดท้าย 4 แผ่น)", type="primary", use_container_width=True):
            pdf_prog = st.progress(0.0, text="กำลังเตรียมข้อมูลสำหรับสร้าง PDF...")

            # ขั้นตอนที่ 1: สร้างสรุป 4 แผ่นอัตโนมัติหากยังไม่มี
            if include_4_sheets and (len(st.session_state.generated_summary_sheets) < 4 or force_regen_sheets):
                def update_sheet_status(sheet_idx, msg_txt):
                    pdf_prog.progress(sheet_idx * 0.05, text=msg_txt)
                generate_all_4_summary_sheets(status_callback=update_sheet_status)

            # ขั้นตอนที่ 2: วาดสไลด์และกล่องข้อความทุกหน้า พร้อมคำนวณขนาดฟอนต์ High-Yield ให้ใหญ่เต็มกรอบ
            doc_in = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
            doc_out = fitz.open()
            arch = fitz.Archive(".")
            has_custom_font = os.path.exists("THSarabunNew.ttf")

            try:
                used_positions = {content_pos, hy_pos, quiz_pos}
                for i in range(total_pages):
                    if i % 4 == 0 or i == total_pages - 1:
                        prog_val = 0.20 + (0.65 * ((i + 1) / total_pages))
                        pdf_prog.progress(min(0.85, prog_val), text=f"กำลังประกอบสไลด์ติวหน้าที่ {i + 1} / {total_pages}...")

                    p_in = doc_in[i]
                    w, h = p_in.rect.width, p_in.rect.height

                    pad_left = (w * (margin_side_pct / 100.0)) if ("ด้านซ้าย" in used_positions and margin_side_pct > 0) else 0
                    pad_right = (w * (margin_side_pct / 100.0)) if ("ด้านขวา" in used_positions and margin_side_pct > 0) else 0
                    pad_top = (h * (margin_vert_pct / 100.0)) if ("ด้านบน" in used_positions and margin_vert_pct > 0) else 0
                    pad_bottom = (h * (margin_vert_pct / 100.0)) if ("ด้านล่าง" in used_positions and margin_vert_pct > 0) else 0

                    new_w = w + pad_left + pad_right
                    new_h = h + pad_top + pad_bottom

                    p_out = doc_out.new_page(width=new_w, height=new_h)
                    bg_color = (0.97, 0.98, 0.99)
                    p_out.draw_rect(fitz.Rect(0, 0, new_w, new_h), color=bg_color, fill=bg_color, width=0)

                    slide_rect = fitz.Rect(pad_left, pad_top, pad_left + w, pad_top + h)
                    p_out.show_pdf_page(slide_rect, doc_in, i)

                    rects = {
                        "ด้านขวา": fitz.Rect(pad_left + w + 10, 10, new_w - 10, new_h - 10) if pad_right > 25 else None,
                        "ด้านซ้าย": fitz.Rect(10, 10, pad_left - 10, new_h - 10) if pad_left > 25 else None,
                        "ด้านล่าง": fitz.Rect(pad_left + 10, pad_top + h + 10, pad_left + w - 10, new_h - 10) if pad_bottom > 25 else None,
                        "ด้านบน": fitz.Rect(pad_left + 10, 10, pad_left + w - 10, pad_top - 10) if pad_top > 25 else None
                    }

                    if i in st.session_state.processed_data:
                        raw_txt = st.session_state.processed_data[i].get("user_text") or st.session_state.processed_data[i].get("ai_text", "")
                        if raw_txt and "⚠️" not in raw_txt:
                            raw_txt = re.sub(r'^[•\-\*]\s*$', '', raw_txt, flags=re.MULTILINE)
                            c_txt, hq_txt, q_txt = split_content_hq(raw_txt)

                            box_contents = {"ด้านขวา": [], "ด้านล่าง": [], "ด้านซ้าย": [], "ด้านบน": []}
                            if c_txt:
                                box_contents[content_pos].append(("content", c_txt))
                            if hq_txt:
                                box_contents[hy_pos].append(("hy", hq_txt))
                            if q_txt:
                                box_contents[quiz_pos].append(("quiz", q_txt))

                            font_face_css = """
                            @font-face { font-family: 'T'; src: url('THSarabunNew.ttf'); }
                            @font-face { font-family: 'T'; font-weight: bold; src: url('THSarabunNew Bold.ttf'); }
                            """ if has_custom_font else ""
                            font_family_val = "'T', sans-serif" if has_custom_font else "sans-serif"

                            for pos, items in box_contents.items():
                                box = rects.get(pos)
                                if not items or box is None or box.is_empty or box.is_infinite:
                                    continue

                                combined_text = "\n\n".join([txt_val for _, txt_val in items])
                                is_hy_box = (len(items) == 1 and items[0][0] == "hy") or (pos == hy_pos and pos != content_pos)

                                html = apply_custom_tags(combined_text, for_pdf=True)
                                f_size = calc_optimal_fontsize(html, box.width, box.height, is_hy_only=is_hy_box)
                                line_h = "1.36" if is_hy_box else "1.42"

                                css = f"""
                                {font_face_css}
                                body {{ font-family: {font_family_val}; font-size: {f_size}px; line-height: {line_h}; color: #0F172A; margin: 0; padding: 0; }}
                                b, strong {{ font-weight: bold; }}
                                .box-visual {{ background-color: #EFF6FF; border-left: 4px solid #2563EB; padding: 3px 8px; margin: 4px 0; }}
                                .box-concept {{ background-color: #EEF2FF; border-left: 4px solid #4F46E5; padding: 3px 8px; margin: 4px 0; }}
                                .box-mech {{ background-color: #F1F5F9; border-left: 4px solid #334155; padding: 3px 8px; margin: 4px 0; }}
                                .box-trap {{ background-color: #FFF7ED; border-left: 4px solid #EA580C; padding: 3px 8px; margin: 4px 0; }}
                                .box-trick {{ background-color: #FEF9C3; border-left: 4px solid #CA8A04; padding: 3px 8px; margin: 4px 0; }}
                                .box-clue {{ background-color: #F5F3FF; border-left: 4px solid #7C3AED; padding: 3px 8px; margin: 4px 0; }}
                                .box-correct {{ background-color: #ECFDF5; border-left: 4px solid #059669; padding: 3px 8px; margin: 4px 0; }}
                                .box-wrong {{ background-color: #FEF2F2; border-left: 4px solid #DC2626; padding: 3px 8px; margin: 4px 0; }}
                                .box-hy {{ background-color: #FFF1F2; border-left: 5px solid #E11D48; padding: 4px 10px; margin: 4px 0 6px 0; }}
                                .box-quiz {{ background-color: #F0F9FF; border-left: 4px solid #0284C7; padding: 3px 8px; margin: 4px 0; }}
                                .box-ans {{ background-color: #F0FDF4; border-left: 4px solid #16A34A; padding: 3px 8px; margin: 4px 0; }}
                                table {{ border-collapse: collapse; width: 100%; margin: 6px 0; }}
                                th {{ background-color: #F8FAFC; border: 1px solid #CBD5E1; padding: 4px; color: #334155; text-align: left; }}
                                td {{ border: 1px solid #E2E8F0; padding: 4px; color: #475569; }}
                                ul, ol {{ margin: 4px 0; padding-left: 18px; }}
                                li {{ margin-bottom: 5px; }}
                                p {{ margin: 4px 0; }}
                                """
                                try:
                                    p_out.insert_htmlbox(box, f"<style>{css}</style><body>{html}</body>", archive=arch)
                                except Exception:
                                    try:
                                        plain_fallback = re.sub(r'<[^>]+>', '', html)
                                        p_out.insert_htmlbox(box, f"<body>{plain_fallback}</body>")
                                    except Exception:
                                        pass

                # ขั้นตอนที่ 3: แนบแผ่นสรุปโค้งสุดท้าย 4 แผ่นต่อท้ายเล่ม
                if include_4_sheets and st.session_state.generated_summary_sheets:
                    pdf_prog.progress(0.88, text="กำลังแนบแผ่นสรุปเก็งข้อสอบ 4 แผ่นต่อท้ายเล่ม...")
                    sheet_configs = [
                        {"idx": 1, "title": "🎯 EXAM SHEET 1: CLASSIC BUZZWORDS & CLUES (โจทย์บอกแบบนี้ ตอบอะไร) 🎯", "border_color": "#7C3AED", "th_bg": "#F5F3FF", "th_color": "#5B21B6"},
                        {"idx": 2, "title": "🖼️ EXAM SHEET 2: VISUAL, IMAGING & LAB INTERPRETATION GUIDE 🖼️", "border_color": "#2563EB", "th_bg": "#EFF6FF", "th_color": "#1E40AF"},
                        {"idx": 3, "title": "⚔️ EXAM SHEET 3: KILL-SWITCH DDX & CHOICE TRAPS (ตารางผ่าช้อยส์หลอก) ⚔️", "border_color": "#EA580C", "th_bg": "#FFF7ED", "th_color": "#C2410C"},
                        {"idx": 4, "title": "💊 EXAM SHEET 4: NEXT BEST STEP, GOLD STANDARD & MANAGEMENT 💊", "border_color": "#059669", "th_bg": "#ECFDF5", "th_color": "#065F46"}
                    ]
                    font_face_css = """
                    @font-face { font-family: 'T'; src: url('THSarabunNew.ttf'); }
                    @font-face { font-family: 'T'; font-weight: bold; src: url('THSarabunNew Bold.ttf'); }
                    """ if has_custom_font else ""
                    font_family_val = "'T', sans-serif" if has_custom_font else "sans-serif"

                    for cfg in sheet_configs:
                        raw_md = st.session_state.generated_summary_sheets.get(cfg["idx"], "")
                        if not raw_md:
                            continue
                        os_html = apply_custom_tags(raw_md, for_pdf=True)
                        p_os = doc_out.new_page(width=595, height=842)
                        f_size_os = calc_optimal_fontsize(os_html, 535, 760, is_hy_only=False)
                        css_os = f"""
                        {font_face_css}
                        body {{ font-family: {font_family_val}; font-size: {f_size_os}px; color: #1E293B; line-height: 1.38; margin: 0; padding: 0; }}
                        h2 {{ text-align: center; border-bottom: 2px solid {cfg['border_color']}; color: #0F172A; padding-bottom: 4px; margin-top: 0; font-size: 1.22em; }}
                        table {{ width: 100%; border-collapse: collapse; margin: 6px 0; }}
                        th, td {{ border: 1px solid #CBD5E1; padding: 5px; }}
                        th {{ background-color: {cfg['th_bg']}; color: {cfg['th_color']}; font-weight: bold; text-align: left; }}
                        ul, ol {{ margin: 4px 0; padding-left: 18px; }}
                        li {{ margin-bottom: 4px; }}
                        """
                        try:
                            p_os.insert_htmlbox(fitz.Rect(30, 30, 565, 812), f"<style>{css_os}</style><body><h2>{cfg['title']}</h2>{os_html}</body>", archive=arch)
                        except Exception:
                            pass

                # ขั้นตอนที่ 4: บีบอัดไฟล์ขั้นสุด (Ultra Compression เป็นค่าเริ่มต้น)
                pdf_prog.progress(0.95, text="กำลังบีบอัดไฟล์ให้มีขนาดเล็กที่สุด (Ultra Compression)...")

                try:
                    doc_out.subset_fonts()
                except Exception:
                    pass

                if "1. บีบอัดขั้นสุด" in comp_level:
                    try:
                        doc_out.rewrite_images(dpi_threshold=130, dpi_target=95, quality=68)
                    except Exception:
                        pass
                    final_bytes = doc_out.tobytes(garbage=4, deflate=True, clean=True)
                elif "2. บีบอัดสมดุล" in comp_level:
                    try:
                        doc_out.rewrite_images(dpi_threshold=180, dpi_target=130, quality=80)
                    except Exception:
                        pass
                    final_bytes = doc_out.tobytes(garbage=4, deflate=True, clean=True)
                else:
                    final_bytes = doc_out.tobytes(garbage=3, deflate=True)

                st.session_state.compiled_pdf_bytes = final_bytes
                st.session_state.compiled_pdf_size_mb = len(final_bytes) / (1024 * 1024)
                pdf_prog.empty()
            finally:
                doc_out.close()
                doc_in.close()
                gc.collect()

        if st.session_state.generated_summary_sheets:
            with st.expander("📋 เปิดดูเนื้อหาสรุปเก็งข้อสอบ 4 แผ่นที่จะแนบท้ายไฟล์ PDF"):
                tabs = st.tabs(["แผ่น 1: คำใบ้โจทย์ (Buzzwords)", "แผ่น 2: คู่มือดูภาพ & Lab", "แผ่น 3: ตารางผ่าช้อยส์หลอก (DDx)", "แผ่น 4: Next Best Step & ยา"])
                for idx_t, tab in enumerate(tabs, start=1):
                    with tab:
                        st.markdown(st.session_state.generated_summary_sheets.get(idx_t, "ยังไม่มีข้อมูล"))

        if st.session_state.compiled_pdf_bytes:
            sheet_msg = "พร้อมสรุปเก็งข้อสอบ 4 แผ่นท้ายเล่ม" if include_4_sheets else "เฉพาะสไลด์ติว"
            st.success(f"🎉 ประกอบและบีบอัดไฟล์ PDF สำเร็จ ({sheet_msg})! ขนาดไฟล์เหลือเพียง: **{st.session_state.compiled_pdf_size_mb:.2f} MB**")
            st.download_button(
                label=f"💾 คลิกดาวน์โหลดคัมภีร์ติวสอบ PDF ({st.session_state.compiled_pdf_size_mb:.2f} MB)",
                data=st.session_state.compiled_pdf_bytes,
                file_name=f"ExamMaster_{st.session_state.pdf_name}",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )

    # --- 10. ระบบประมวลผลหลังบ้าน (Dual-Mode Exam Tutor Processor) ---
    if st.session_state.is_running and not st.session_state.stop_clicked:
        active_m = st.session_state.current_active_model or get_best_available_model(st.session_state.flash_models_list)
        model = genai.GenerativeModel(active_m)
        config = GenerationConfig(max_output_tokens=max_tokens)
        safety = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE
        }

        # ==========================================
        # PHASE 1: GLOBAL SCAN
        # ==========================================
        if st.session_state.phase == 'global_scan':
            if st.session_state.fast_index_mode:
                action_placeholder.markdown("<div class='status-purple'><b>⚡ [Phase 1/2] กำลังสแกนโครงสร้างชีทติวและโจทย์ข้อสอบด้วยระบบ Instant Index...</b></div>", unsafe_allow_html=True)
                doc_idx = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
                try:
                    for idx in st.session_state.selected_pages:
                        if idx not in st.session_state.global_data:
                            raw_t = doc_idx[idx].get_text("text").strip()
                            lines = [ln.strip() for ln in raw_t.split("\n") if ln.strip()]
                            topic = lines[0][:45] if lines else f"หน้า {idx+1}"
                            summary = " ".join(lines[1:4])[:140] if len(lines) > 1 else "สไลด์ภาพ/โจทย์ข้อสอบ"
                            st.session_state.global_data[idx] = {'topic': topic, 'summary': summary}
                finally:
                    doc_idx.close()

                st.session_state.phase = 'detail_scan'
                save_workspace()
                st.rerun()
            else:
                target_global = next((i for i in st.session_state.selected_pages if i not in st.session_state.global_data), None)
                if target_global is None:
                    st.session_state.phase = 'detail_scan'
                    save_workspace()
                    st.rerun()
                else:
                    action_placeholder.markdown(f"<div class='status-purple'><b>🔍 [Phase 1/2] กำลังสแกนภาพรวม (หน้า {target_global+1} / {total_pages})</b></div>", unsafe_allow_html=True)
                    doc_g = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
                    p_img = doc_g[target_global].get_pixmap(dpi=50)
                    img = Image.open(io.BytesIO(p_img.tobytes("png")))
                    doc_g.close()

                    prompt_global = "วิเคราะห์สไลด์หน้านี้ ตอบตามรูปแบบนี้เท่านั้น:\nTOPIC: (ชื่อหัวข้อหรือเรื่องที่โจทย์ถาม 1-3 คำ)\nSUMMARY: (ใจความสำคัญ 1 ประโยคสั้นๆ)"
                    try:
                        fast_config = GenerationConfig(max_output_tokens=100)
                        resp = model.generate_content([prompt_global, img], safety_settings=safety, generation_config=fast_config)
                        text = resp.text.strip()
                        st.session_state.estimated_tokens_used += len(text)
                        topic = text.split("TOPIC:")[1].split("SUMMARY:")[0].strip() if "TOPIC:" in text and "SUMMARY:" in text else f"หน้า {target_global+1}"
                        summary = text.split("SUMMARY:")[1].strip() if "SUMMARY:" in text else "ข้อมูลสไลด์"
                        st.session_state.global_data[target_global] = {'topic': topic, 'summary': summary}
                    except Exception:
                        st.session_state.global_data[target_global] = {'topic': f"หน้า {target_global+1}", 'summary': ""}
                    save_workspace()
                    st.rerun()

        # ==========================================
        # PHASE 2: DETAIL SCAN (Dual-Mode: Concept Tutor vs Exam Dissection)
        # ==========================================
        elif st.session_state.phase == 'detail_scan':
            target = None
            is_recheck = False

            for i in st.session_state.selected_pages:
                if i in st.session_state.processed_data and "⚠️" in st.session_state.processed_data[i].get("ai_text", ""):
                    target = i
                    is_recheck = True
                    break

            if target is None:
                target = next((i for i in st.session_state.selected_pages if i not in st.session_state.processed_data), None)

            if target is not None:
                if is_recheck:
                    st.session_state.status_mode = 'yellow'
                    icon, msg = "🔄", f"[Phase 2/2] กำลังซ่อมหน้าที่ Error (หน้า {target+1})"
                else:
                    st.session_state.status_mode = 'blue'
                    done_count = len([k for k in st.session_state.selected_pages if k in st.session_state.processed_data])
                    icon, msg = "🎯", f"[Phase 2/2] พี่ติวเตอร์กำลังอธิบายหน้าที่ {target+1} (เสร็จแล้ว {done_count}/{len(st.session_state.selected_pages)} หน้า)"

                action_placeholder.markdown(f"<div class='status-{st.session_state.status_mode}'><b>{icon} {msg}</b><br>🤖 โมเดล: <code>{active_m}</code> | แยกโหมด [ติวเนื้อหา/แกะภาพ] vs [ผ่าข้อสอบเก่า] อัตโนมัติ</div>", unsafe_allow_html=True)

                doc_d = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
                p_img = doc_d[target].get_pixmap(dpi=90)
                img = Image.open(io.BytesIO(p_img.tobytes("png")))
                doc_d.close()

                pattern_parts = []
                if want_content:
                    trick_line = "\nTrick: (ทริคจำสั้นๆ หรือ Mnemonic ที่ใช้เข้าห้องสอบ ถ้าไม่มีให้ข้ามได้)\n" if want_trick else ""
                    content_instruction = (
                        "กรุณาตรวจสอบสไลด์หน้านี้ก่อนว่าเป็น [หน้าสรุปเนื้อหา/รูปภาพ] หรือ [หน้าโจทย์ข้อสอบเก่า] แล้วเลือกเขียนตามแพทเทิร์นเดียวที่ตรงกับหน้านี้เท่านั้น (เขียนชิดขอบซ้าย):\n\n"
                        "--- กรณีที่ 1: ถ้าสไลด์หน้านี้เป็น [เนื้อหาติว / รูปภาพ / ไดอะแกรม / ตาราง] ให้ใช้หัวข้อต่อไปนี้ ---\n"
                        "แกะภาพและตาราง: (สำคัญมาก! อธิบายแทนคนสอนว่าในภาพ/กราฟ/ไดอะแกรม/ตารางหน้านี้ ต้องดูตรงไหน ลักษณะเด่นคืออะไร และสื่อความหมายทางคลินิกอย่างไร **เพราะ...**)\n\n"
                        "แก่นเนื้อหาที่ใช้สอบ: (สรุปคอนเซปต์หลักที่ต้องจำไปสอบให้เข้าใจใน 1-2 ประโยค เน้น **ตัวหนาคำสำคัญ**)\n\n"
                        "กลไกเชื่อมโยง: (อธิบายลำดับกลไกหรืออาการด้วยลูกศร `A ➡️ B ➡️ C` พร้อมให้เหตุผลด้วยคำว่า **'...เพราะ...'** เสมอ)\n\n"
                        "จุดที่ข้อสอบชอบหลอก: (ชี้จุดที่ข้อสอบมักนำมาออกหลอก หรือจุดตัดที่ใช้แยกโรคใกล้เคียง DDx)\n"
                        f"{trick_line}\n"
                        "--- กรณีที่ 2: ถ้าสไลด์หน้านี้เป็น [โจทย์ข้อสอบเก่า / คำถาม Clinical Vignette] ให้ใช้หัวข้อต่อไปนี้แทน ---\n"
                        "สแกนโจทย์หาคำใบ้: (ดึง **คีย์เวิร์ด/คำใบ้สำคัญ** จากโจทย์ และช่วยอธิบายภาพ/ผล Lab ที่โจทย์ให้มาอย่างละเอียดว่าชี้ไปที่ภาวะอะไร **เพราะ...**)\n\n"
                        "ฟันธงคำตอบ: (ระบุคำตอบที่ถูกต้องชัดเจน พร้อมอธิบายกลไกเป็นลูกศรว่าทำไมถึงตอบข้อนี้ **เพราะ...**)\n\n"
                        "ผ่าตัดช้อยส์หลอก: (อธิบายทีละตัวเลือกว่าทำไมช้อยส์อื่นถึงผิด **และถ้าโจทย์อยากให้ตอบช้อยส์นั้น ต้องเปลี่ยนคำใบ้ในโจทย์เป็นอะไร** เพื่อให้ได้ความรู้ครบทุกช้อยส์)\n"
                        f"{trick_line}"
                    )
                    pattern_parts.append(content_instruction)

                if want_summary:
                    pattern_parts.append(
                        "High-Yield:\n"
                        "- KEY1: **(กฎเหล็กทำข้อสอบข้อที่ 1 / เจอคำใบ้อะไรให้ตอบอะไร)** (สรุปสั้นคม ชัดเจน อ่านเข้าใจทันที พร้อมเหตุผลสั้นๆ **เพราะ...**)\n"
                        "- KEY2: **(กฎเหล็กทำข้อสอบข้อที่ 2 / จุดตัดห้ามพลาด)** (สรุปสั้นคม ชัดเจน ถ้ามีประเด็นสำคัญอีกสามารถเพิ่ม KEY3 ได้)"
                    )

                if want_quiz:
                    q_lines = "\n".join([f"Q{q_i}: (เก็งคำถามสั้นๆ พลิกแพลงจากหน้านี้เพื่อเช็กความเข้าใจ)" for q_i in range(1, quiz_count + 1)])
                    q_sec = f"Quiz:\n{q_lines}"
                    if want_answer:
                        a_lines = "\n".join([f"A{q_i}: (เฉลยสั้นๆ ตรงจุด พร้อมเหตุผล **เพราะ...**)" for q_i in range(1, quiz_count + 1)])
                        q_sec += f"\n\nเฉลย:\n{a_lines}"
                    pattern_parts.append(q_sec)

                strict_pattern = "\n\n".join(pattern_parts)
                local_context = build_local_sliding_context(target, window=2)

                prompt_template = st.session_state.custom_prompt_text
                prompt = (
                    prompt_template
                    .replace("{global_context}", local_context)
                    .replace("{strict_pattern}", strict_pattern)
                    .replace("{current_page}", str(target + 1))
                    .replace("{total_pages}", str(total_pages))
                )

                is_success = False
                retry_count = 0

                while retry_count < 2 and not is_success:
                    try:
                        resp = model.generate_content([prompt, img], safety_settings=safety, generation_config=config)
                        final_text = resp.text.strip()
                        st.session_state.estimated_tokens_used += len(final_text)

                        if "NON_CONTENT" in final_text:
                            final_text = ""

                        st.session_state.processed_data[target] = {"ai_text": final_text, "user_text": ""}
                        rebuild_full_summaries()
                        save_workspace()
                        is_success = True

                    except Exception as e:
                        error_msg = str(e)
                        if "429" in error_msg or "Quota" in error_msg:
                            st.session_state.exhausted_models[active_m] = time.time() + 60
                            action_placeholder.markdown(f"<div class='status-yellow'><b>⚠️ `{active_m}` คิวเต็ม! กำลังสลับโมเดลสำรอง...</b></div>", unsafe_allow_html=True)
                            time.sleep(1.5)
                            new_model = get_best_available_model(st.session_state.flash_models_list)
                            if new_model:
                                active_m = new_model
                                st.session_state.current_active_model = new_model
                                model = genai.GenerativeModel(new_model)
                                retry_count += 1
                            else:
                                st.session_state.processed_data[target] = {"ai_text": "⚠️ โควต้าเต็มทุกโมเดล กด Pause รอ 1 นาทีแล้วกด Continue ครับ", "user_text": ""}
                                is_success = True
                        else:
                            st.session_state.processed_data[target] = {"ai_text": f"⚠️ Error: {error_msg}", "user_text": ""}
                            is_success = True

                time.sleep(0.05)
                st.rerun()
            else:
                st.session_state.is_running = False
                st.session_state.phase = 'idle'
                rebuild_full_summaries()
                save_workspace()
                action_placeholder.markdown("<div class='status-blue' style='border-left-color: #38A169; color: #2F855A; background: #F0FFF4;'><b>✅ ติวเนื้อหาและผ่าข้อสอบครบทุกหน้าที่เลือกแล้ว!</b><br>กดปุ่มรวบรวมและประกอบไฟล์ PDF ด้านล่างเพื่อรับไฟล์พร้อมสรุปเก็งข้อสอบ 4 แผ่นท้ายเล่มได้เลยครับ</div>", unsafe_allow_html=True)
