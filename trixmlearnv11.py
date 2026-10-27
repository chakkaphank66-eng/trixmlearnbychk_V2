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

    # --- ตัวแปรสำหรับ Custom Prompt เนื้อหา ---
    'use_custom_prompt': False,
    'custom_prompt_text': "",

    # --- ตัวแปรสำหรับ Custom Prompt Summary (4 แผ่น) ---
    'use_custom_summary_prompt': False,
    'custom_summary_prompt_1': "",
    'custom_summary_prompt_2': "",
    'custom_summary_prompt_3': "",
    'custom_summary_prompt_4': "",
    'generated_summary_sheets': {},

    # --- ตัวแปรสำหรับระบบดาวน์โหลด PDF ---
    'compiled_pdf_bytes': None,
    'compiled_pdf_size_mb': 0.0,
    'orig_uncompressed_mb': 0.0
}

for k, v in keys_to_init.items():
    if k not in st.session_state:
        st.session_state[k] = v

st.set_page_config(page_title="PDF Note Space 🩺", layout="wide")

# --- 2. Custom CSS & Scannable Minimalist Design ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');
    
    html, body, [class*="st-"] {
        font-family: 'Sarabun', sans-serif !important;
    }

    .stApp { background-color: #F8FAFC; }
    .main-header { font-size: 2.1rem; font-weight: 800; color: #0F172A; margin-bottom: 0.8rem; letter-spacing: -0.5px; }
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
    
    .box-visual { background-color: #EFF6FF; border-left: 4px solid #3B82F6; padding: 6px 12px; margin: 8px 0 6px 0; border-radius: 0 6px 6px 0; }
    .box-intro { background-color: #F8FAFC; border-left: 4px solid #94A3B8; padding: 4px 12px; margin: 8px 0 4px 0; border-radius: 0 6px 6px 0; }
    .box-concept { background-color: #EEF2FF; border-left: 4px solid #6366F1; padding: 5px 12px; margin: 10px 0 4px 0; border-radius: 0 6px 6px 0; }
    .box-mech { background-color: #F1F5F9; border-left: 4px solid #475569; padding: 5px 12px; margin: 10px 0 4px 0; border-radius: 0 6px 6px 0; }
    .box-clinic { background-color: #F0FDFA; border-left: 4px solid #14B8A6; padding: 5px 12px; margin: 10px 0 4px 0; border-radius: 0 6px 6px 0; }
    .box-warn { background-color: #FFF7ED; border-left: 4px solid #F97316; padding: 5px 12px; margin: 10px 0 4px 0; border-radius: 0 6px 6px 0; }
    .box-trick { background-color: #FEF9C3; border-left: 4px solid #EAB308; padding: 5px 12px; margin: 10px 0 4px 0; border-radius: 0 6px 6px 0; }
    .box-hy { background-color: #FFF1F2; border-left: 5px solid #F43F5E; padding: 8px 14px; margin: 12px 0 6px 0; border-radius: 0 6px 6px 0; }
    .box-quiz { background-color: #F0F9FF; border-left: 4px solid #0EA5E9; padding: 5px 12px; margin: 10px 0 4px 0; border-radius: 0 6px 6px 0; }
    .box-ans { background-color: #F0FDF4; border-left: 4px solid #22C55E; padding: 5px 12px; margin: 6px 0 4px 0; border-radius: 0 6px 6px 0; }
    
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

WORKSPACE_META_FILE = "autosave_workspace_meta.pkl"
WORKSPACE_PDF_FILE = "autosave_source.pdf"

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
    for path in [WORKSPACE_META_FILE, WORKSPACE_PDF_FILE, "autosave_workspace.pkl"]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

@st.cache_data(max_entries=30, show_spinner=False)
def render_page_png(pdf_bytes, page_number, dpi=110):
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
            elif "Concept หลัก:" in txt:
                c_part = txt.split("Concept หลัก:")[-1].split("\n")[0].strip()
                chunks.append(f"[หน้า {i+1}] {c_part}")
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
    - ตัดสระลอย/วรรณยุกต์ไทยออกจากการคำนวณความกว้างแนวนอน
    - หากเป็นกล่อง High-Yield จะขยายฟอนต์ให้ใหญ่เต็มพื้นที่กรอบ (สูงสุด 58px)
    """
    if not html_text or rect_width <= 0 or rect_height <= 0:
        return 20

    # แยกบรรทัดตามโครงสร้าง HTML บล็อกและรายการ
    block_split = re.sub(r'</?(li|p|div|tr|h\d|br)[^>]*>', '\n', html_text)
    raw_lines = [re.sub(r'<[^>]+>', '', ln).strip() for ln in block_split.split('\n')]
    raw_lines = [ln for ln in raw_lines if ln]

    if not raw_lines:
        return 20

    # นับเฉพาะตัวอักษรที่กินพื้นที่แนวนอน (ไม่นับสระลอยและวรรณยุกต์ไทย)
    thai_combining = r'[\u0E31\u0E34-\u0E3A\u0E47-\u0E4E]'
    eff_lengths = [max(1, len(re.sub(thai_combining, '', ln))) for ln in raw_lines]
    num_blocks = len(eff_lengths)

    max_f = 58 if is_hy_only else 40
    min_f = 20 if is_hy_only else 13
    # ฟอนต์ THSarabunNew มีขนาดตัวแคบ จึงใช้ค่าสัมประสิทธิ์ความกว้างต่อตัวอักษรต่ำ (0.37 - 0.40)
    char_width_factor = 0.37 if is_hy_only else 0.41
    line_height_factor = 1.35 if is_hy_only else 1.42
    target_fill_ratio = 0.94 if is_hy_only else 0.88

    for f_size in range(max_f, min_f - 1, -1):
        usable_w = max(40.0, rect_width - 20.0)
        chars_per_line = max(8.0, usable_w / (f_size * char_width_factor))

        total_lines = 0.0
        for length in eff_lengths:
            total_lines += math.ceil(length / chars_per_line)

        # บวกพื้นที่ระยะห่างระหว่างหัวข้อและขอบกล่อง
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
    layout_map[c_pos].append("<span style='color: #334155;'><b>เนื้อหา</b></span>")
    layout_map[hy_pos].append("<span style='color: #BE123C;'><b>High-Yield</b></span>")
    layout_map[q_pos].append("<span style='color: #0369A1;'><b>Quiz</b></span>")

    right_box = f"<div style='flex: 0.35; background: #F8FAFC; padding: 5px; font-size: 8px; border-left: 1px solid #E2E8F0;'>{'<br><br>'.join(layout_map['ด้านขวา'])}</div>" if layout_map['ด้านขวา'] else ""
    left_box = f"<div style='flex: 0.35; background: #F8FAFC; padding: 5px; font-size: 8px; border-right: 1px solid #E2E8F0;'>{'<br><br>'.join(layout_map['ด้านซ้าย'])}</div>" if layout_map['ด้านซ้าย'] else ""
    bottom_box = f"<div style='height: 40px; background: #F8FAFC; padding: 5px; font-size: 8px; border-top: 1px solid #E2E8F0; text-align: center;'>{' | '.join(layout_map['ด้านล่าง'])}</div>" if layout_map['ด้านล่าง'] else ""
    top_box = f"<div style='height: 40px; background: #F8FAFC; padding: 5px; font-size: 8px; border-bottom: 1px solid #E2E8F0; text-align: center;'>{' | '.join(layout_map['ด้านบน'])}</div>" if layout_map['ด้านบน'] else ""

    html_str = f"""<div style="width: 100%; height: 170px; border-radius: 10px; background: white; border: 2px solid #E2E8F0; display: flex; flex-direction: column; overflow: hidden;">{top_box}<div style="flex: 1; display: flex; flex-direction: row;">{left_box}<div style="flex: 1; background: #F1F5F9; border: 2px dashed #CBD5E1; margin: 6px; display: flex; align-items: center; justify-content: center; font-size: 12px; color: #64748B; font-weight: bold; border-radius: 6px;">Slide</div>{right_box}</div>{bottom_box}</div>"""
    st.markdown(html_str, unsafe_allow_html=True)

def apply_custom_tags(text, for_pdf=False):
    lines = text.split('\n')
    colors = ["#DC2626", "#2563EB", "#059669", "#7C3AED", "#EA580C", "#0891B2", "#DB2777"]
    color_idx = 0
    in_high_yield = False
    new_lines = []

    for line in lines:
        if "High-Yield:" in line or "🚨 High-Yield" in line:
            in_high_yield = True
            color_idx = 0
        elif any(sec in line for sec in ["Quiz:", "Trick:", "การนำไปใช้ในคลินิก:", "ระวัง:", "กลไก/รายละเอียดและอาการ:", "Concept หลัก:", "จุดโฟกัสบนสไลด์:", "Intro:", "เฉลย:"]):
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

    if not for_pdf and "เฉลย:" in text:
        parts = text.split("เฉลย:", 1)
        before_ans = markdown.markdown(parts[0], extensions=['tables'])
        ans_html = markdown.markdown(parts[1].strip(), extensions=['tables'])
        html = f"{before_ans}<details class='ans-toggle'><summary>🎯 คลิกเพื่อดูเฉลย (ฝึกคิดคำตอบก่อนเปิด)</summary><div style='margin-top:8px;'>{ans_html}</div></details>"
    else:
        html = markdown.markdown(text, extensions=['tables'])

    replacements = [
        ("จุดโฟกัสบนสไลด์:", "<div class='box-visual'><b style='color: #1D4ED8; font-size: 0.95em;'>👁️ จุดต้องมองบนสไลด์ (Visual Anchor)</b></div>"),
        ("<strong>จุดโฟกัสบนสไลด์:</strong>", "<div class='box-visual'><b style='color: #1D4ED8; font-size: 0.95em;'>👁️ จุดต้องมองบนสไลด์ (Visual Anchor)</b></div>"),

        ("Intro:", "<div class='box-intro'><b style='color: #475569; font-size: 0.95em;'>🔗 เชื่อมโยงเนื้อหา</b></div>"),
        ("<strong>Intro:</strong>", "<div class='box-intro'><b style='color: #475569; font-size: 0.95em;'>🔗 เชื่อมโยงเนื้อหา</b></div>"),

        ("Concept หลัก:", "<div class='box-concept'><b style='color: #4338CA; font-size: 0.95em;'>🎯 Concept หลัก (รู้เรื่องใน 5 วิ)</b></div>"),
        ("<strong>Concept หลัก:</strong>", "<div class='box-concept'><b style='color: #4338CA; font-size: 0.95em;'>🎯 Concept หลัก (รู้เรื่องใน 5 วิ)</b></div>"),

        ("กลไก/รายละเอียดและอาการ:", "<div class='box-mech'><b style='color: #334155; font-size: 0.95em;'>⚡ กลไกและเหตุผลเชื่อมโยง</b></div>"),
        ("<strong>กลไก/รายละเอียดและอาการ:</strong>", "<div class='box-mech'><b style='color: #334155; font-size: 0.95em;'>⚡ กลไกและเหตุผลเชื่อมโยง</b></div>"),

        ("การนำไปใช้ในคลินิก:", "<div class='box-clinic'><b style='color: #0F766E; font-size: 0.95em;'>🩺 จุดใช้จริงบนวอร์ด & ข้อสอบ</b></div>"),
        ("<strong>การนำไปใช้ในคลินิก:</strong>", "<div class='box-clinic'><b style='color: #0F766E; font-size: 0.95em;'>🩺 จุดใช้จริงบนวอร์ด & ข้อสอบ</b></div>"),

        ("ระวัง:", "<div class='box-warn'><b style='color: #C2410C; font-size: 0.95em;'>⚠️ ระวังโดนหลอก (Pitfall / DDx)</b></div>"),
        ("<strong>ระวัง:</strong>", "<div class='box-warn'><b style='color: #C2410C; font-size: 0.95em;'>⚠️ ระวังโดนหลอก (Pitfall / DDx)</b></div>"),

        ("Trick:", "<div class='box-trick'><b style='color: #A16207; font-size: 0.95em;'>💡 Trick จำติดสมอง</b></div>"),
        ("<strong>Trick:</strong>", "<div class='box-trick'><b style='color: #A16207; font-size: 0.95em;'>💡 Trick จำติดสมอง</b></div>"),

        ("High-Yield:", "<div class='box-hy'><b style='color: #BE123C; font-size: 1.02em;'>🚨 High-Yield จุดออกสอบห้ามพลาด</b></div>"),
        ("<strong>High-Yield:</strong>", "<div class='box-hy'><b style='color: #BE123C; font-size: 1.02em;'>🚨 High-Yield จุดออกสอบห้ามพลาด</b></div>"),

        ("Quiz:", "<div class='box-quiz'><b style='color: #0369A1; font-size: 0.95em;'>📝 ทดสอบความจำ (Active Recall)</b></div>"),
        ("<strong>Quiz:</strong>", "<div class='box-quiz'><b style='color: #0369A1; font-size: 0.95em;'>📝 ทดสอบความจำ (Active Recall)</b></div>"),

        ("เฉลย:", "<div class='box-ans'><b style='color: #15803D; font-size: 0.95em;'>🎯 เฉลย</b></div>"),
        ("<strong>เฉลย:</strong>", "<div class='box-ans'><b style='color: #15803D; font-size: 0.95em;'>🎯 เฉลย</b></div>"),
    ]

    for old, new in replacements:
        html = html.replace(old, new)
        html = html.replace(f"<p>{new}</p>", new)

    return html

def generate_all_4_summary_sheets(status_callback=None):
    """สร้างสรุป 4 แผ่นอัตโนมัติจากเนื้อหา High-Yield ทั้งหมด"""
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
        ("custom_summary_prompt_1", "แผ่นที่ 1: Overview & Core Concepts"),
        ("custom_summary_prompt_2", "แผ่นที่ 2: Pathophysiology & Symptoms"),
        ("custom_summary_prompt_3", "แผ่นที่ 3: Diagnosis & DDx"),
        ("custom_summary_prompt_4", "แผ่นที่ 4: Management & Treatment")
    ]
    for idx, (pk, label) in enumerate(prompt_keys, start=1):
        if status_callback:
            status_callback(idx, f"กำลังสกัดสรุปท้ายเล่ม {label} ({idx}/4)...")
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

    st.markdown("### 💳 Token Tracker (จำลอง)")
    token_used = st.session_state.estimated_tokens_used
    st.progress(min(token_used / 1000000, 1.0))
    st.caption(f"ใช้ไปแล้ว: **{token_used:,} Tokens**")

    st.divider()
    med_year = st.selectbox("ระดับ นสพ.", [2, 3, 4, 5, 6], index=2, disabled=is_locked)
    max_tokens = st.number_input("กำหนด Max Output Tokens", min_value=100, max_value=8192, value=4000, step=500, disabled=is_locked)

    st.session_state.fast_index_mode = st.checkbox(
        "⚡ สแกนบริบทความเร็วสูง (0.1 วินาที ไม่เสียโควตา AI ใน Phase 1)",
        value=st.session_state.fast_index_mode,
        disabled=is_locked
    )

    st.markdown("### 📐 จัดสรรพื้นที่กระดาษ (Layout)")
    margin_side_pct = st.slider("ขยายพื้นที่ด้านข้าง (%)", 0, 100, 45, disabled=is_locked)
    margin_vert_pct = st.slider("ขยายพื้นที่ด้านบน/ล่าง (%)", 0, 100, 45, disabled=is_locked)

    pos_options = ["ด้านขวา", "ด้านล่าง", "ด้านซ้าย", "ด้านบน"]
    content_pos = st.selectbox("วาง [เนื้อหา] ไว้ที่:", pos_options, index=0, disabled=is_locked)
    hy_pos = st.selectbox("วาง [High-Yield] ไว้ที่:", pos_options, index=1, disabled=is_locked)
    quiz_pos = st.selectbox("วาง [Quiz] ไว้ที่:", pos_options, index=0, disabled=is_locked)

    st.markdown("### 📋 ข้อมูลที่ต้องการ")
    want_content = st.checkbox("คำอธิบายเนื้อหา (กระชับ+ชี้จุดดูสไลด์)", value=True, disabled=is_locked)
    want_summary = st.checkbox("สรุป High-Yield (ฟอนต์ใหญ่เต็มกรอบ)", value=True, disabled=is_locked)
    want_trick = st.checkbox("💡 ทริคจำ (Trick)", value=True, disabled=is_locked)
    want_quiz = st.checkbox("Quiz", value=True, disabled=is_locked)

    quiz_count = 2
    want_answer = True
    if want_quiz:
        quiz_count = st.slider("จำนวนข้อ Quiz:", 1, 5, 2, disabled=is_locked)
        want_answer = st.checkbox("รวมเฉลย", value=True, disabled=is_locked)

    get_layout_preview(content_pos, hy_pos, quiz_pos)

    # 🌟 ระบบ Customize Prompt เนื้อหาหลัก
    st.markdown("### 🛠️ ปรับแต่ง Prompt เนื้อหาหลัก")
    use_custom_prompt = st.checkbox("เปิดใช้งานแก้ไข Prompt หลัก", value=st.session_state.use_custom_prompt, disabled=is_locked)

    base_prompt_template = f"""คุณคือรุ่นพี่แพทย์ที่ติวเก่งที่สุด กำลังสรุปสไลด์ให้น้อง นสพ. ปี {med_year}
เป้าหมายสูงสุด: **อ่านสนุก กระชับ ตรงจุดสำคัญ ใช้เวลาอ่านน้อย และดึงสายตาน้องกลับไปดูภาพ/ตารางบนสไลด์เสมอ**

**บริบทหน้าใกล้เคียง (Sliding Context):**
{{global_context}}

**กฎเหล็ก 7 ข้อ (ต้องทำตามอย่างเคร่งครัด):**
1. **ห้ามทักทาย ห้ามเกริ่นน้ำท่วมทุ่ง** เขียนชิดขอบซ้ายทันที
2. **บังคับดึงสายตากลับไปดูสไลด์:** ในหัวข้อ `จุดโฟกัสบนสไลด์:` ต้องระบุชัดเจนว่าให้มองจุดไหนของสไลด์หน้านี้ (เช่น กราฟเส้นสีแดง, ตารางคอลัมน์ขวา, ภาพ X-ray/Patho, หรือไดอะแกรม) และจุดนั้นกำลังสื่ออะไร
3. **ใช้ลูกศรเชื่อมเหตุ-ผลแทนการเขียนเรียงความยาวๆ:** การอธิบายกลไกหรืออาการ ให้เขียนเป็นลำดับลูกศร `A ➡️ B ➡️ C (**เพราะ**...)` เพื่อให้กวาดสายตาอ่านเข้าใจได้ในไม่กี่วินาที
4. **เน้นตัวหนาที่คำสำคัญเสมอ** และทุกกลไกสำคัญต้องให้เหตุผลด้วยคำว่า **'...เพราะ...'** เพื่อให้เข้าใจถึงแก่นและจำได้นาน
5. **คำย่อและศัพท์แพทย์:** ใส่วงเล็บคำเต็มหรือภาษาอังกฤษเมื่อปรากฏครั้งแรก (เช่น หอบเหนื่อย (dyspnea))
6. **ปรับความยาวตามเนื้อหาจริง (Adaptive Brevity):** ถ้าสไลด์มีเนื้อหาน้อยหรือเป็นหน้าหัวข้อ ให้เขียนสั้นๆ เฉพาะแก่น ไม่ต้องฝืนเขียนยาว
7. **กฎพิเศษสำหรับข้อสอบ:** ถ้าสไลด์เป็นโจทย์ข้อสอบ ให้เปลี่ยนเป็นเฉลย: โจทย์ถามอะไร (หา Keyword) ➡️ ตอบข้อไหน ➡️ ทำไมถูก (**เพราะ...**) ➡️ ทำไมช้อยส์อื่นผิด และถ้าเป็นหน้าว่างให้ตอบแค่ 'NON_CONTENT'

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

    # 🌟 ระบบ Customize Prompt สำหรับ One-Sheet Summary (4 แผ่น)
    st.markdown("### 📝 ปรับแต่ง Prompt สำหรับ One-Sheet Summary (4 แผ่น)")
    use_custom_summary_prompt = st.checkbox("เปิดใช้งานแก้ไข Prompt สำหรับ Summary", value=st.session_state.use_custom_summary_prompt, disabled=is_locked)

    default_summary_prompt_1 = f"""สรุป High-Yield แผ่นที่ 1 (Overview & Core Concepts) สำหรับ นสพ.ปี {med_year} รูปแบบมินิมอล กระชับที่สุด:
- จัดกลุ่มโรคหรือหัวข้อหลักเป็น **Markdown Table** ทันทีเพื่อเปรียบเทียบภาพรวม
- ใส่ **คำสำคัญตัวหนา** (Hook Keyword) และเหตุผลสั้นๆ (**'...เพราะ...'**) ในแต่ละหัวข้อ
ข้อมูลอ้างอิง:
{{full_summaries}}"""

    default_summary_prompt_2 = f"""สร้าง Clinical One-Sheet Summary แผ่นที่ 2 (Pathophysiology & Clinical Manifestations) สำหรับ นสพ.ปี {med_year}:
1. **กลไกการเกิดโรคแบบลูกศร (Pathophysiology Pathway):** เขียนในรูปแบบ `สาเหตุ ➡️ กลไก ➡️ พยาธิสภาพ (**เพราะ...**)`
2. **อาการแสดงสำคัญ (Classic Presentation & Red Flags):** เน้น **ตัวหนาที่อาการเด่น** ที่ใช้จับทางข้อสอบ
3. **ภาวะแทรกซ้อนที่ต้องเฝ้าระวัง (Complications)**
ข้อมูลอ้างอิง:
{{full_summaries}}"""

    default_summary_prompt_3 = f"""สร้าง Clinical One-Sheet Summary แผ่นที่ 3 (Diagnosis, DDx & Mnemonics) สำหรับ นสพ.ปี {med_year}:
1. **ตารางแยกโรค (Differential Diagnosis Table):** ใช้ตารางเปรียบเทียบจุดเหมือนและ **จุดตัดที่ใช้แยกโรค**
2. **การส่งตรวจยืนยัน (Initial Test vs Gold Standard):** ระบุชัดเจนว่าส่งทำไม (**...เพราะ...**)
3. **ทริคจำ (Mnemonics & High-Yield Pearls)**
ข้อมูลอ้างอิง:
{{full_summaries}}"""

    default_summary_prompt_4 = f"""สร้าง Clinical One-Sheet Summary แผ่นที่ 4 (Management & Clinical Pearls) สำหรับ นสพ.ปี {med_year}:
1. **แนวทางการรักษาตามลำดับขั้น (Stepwise Management):** First-line ➡️ Next step
2. **ตารางสรุปยาสำคัญ (Drug of Choice, กลไกสำคัญ, ผลข้างเคียงที่ต้องระวัง)**
3. **ข้อบ่งชี้การผ่าตัด / Admit / Refer** (ถ้ามีในเนื้อหา)
ข้อมูลอ้างอิง:
{{full_summaries}}"""

    if use_custom_summary_prompt:
        st.session_state.custom_summary_prompt_1 = st.text_area("Prompt แผ่นที่ 1", value=st.session_state.custom_summary_prompt_1 or default_summary_prompt_1, height=140, disabled=is_locked)
        st.session_state.custom_summary_prompt_2 = st.text_area("Prompt แผ่นที่ 2", value=st.session_state.custom_summary_prompt_2 or default_summary_prompt_2, height=140, disabled=is_locked)
        st.session_state.custom_summary_prompt_3 = st.text_area("Prompt แผ่นที่ 3", value=st.session_state.custom_summary_prompt_3 or default_summary_prompt_3, height=140, disabled=is_locked)
        st.session_state.custom_summary_prompt_4 = st.text_area("Prompt แผ่นที่ 4", value=st.session_state.custom_summary_prompt_4 or default_summary_prompt_4, height=140, disabled=is_locked)
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
st.markdown("<div class='main-header'>📚 PDF Note Space: Visual-First Smart Reader</div>", unsafe_allow_html=True)

if not st.session_state.pdf_bytes:
    if os.path.exists(WORKSPACE_META_FILE) and os.path.exists(WORKSPACE_PDF_FILE):
        st.info("💾 **พบงานที่ทำค้างไว้!** (ระบบ Auto-save แบบแยกไฟล์ความเร็วสูง รองรับมากกว่า 100 หน้า)")
        if st.button("🔄 กู้คืนงานที่ทำค้างไว้", type="primary"):
            with st.spinner("กำลังโหลดข้อมูล..."):
                if load_workspace():
                    st.success("กู้คืนสำเร็จ!")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("ไฟล์กู้คืนมีปัญหา")

    uploaded_file = st.file_uploader("อัปโหลดสไลด์อาจารย์ (PDF) - รองรับ 100–400+ หน้าโดยไม่ค้าง", type="pdf")
    if uploaded_file:
        with st.status(f"กำลังนำเข้าไฟล์: {uploaded_file.name}...", expanded=True) as status:
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
        st.info(f"📄 ไฟล์ปัจจุบัน: **{st.session_state.pdf_name}** (ทั้งหมด **{total_pages} หน้า** | ประมวลผลแล้ว **{len(st.session_state.processed_data)} หน้า**)")
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
        with st.expander(f"🖼️ เลือกหน้าที่ต้องการประมวลผล (เลือกไว้ {len(st.session_state.selected_pages)}/{total_pages} หน้า)", expanded=True):
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
        if st.button(f"⚙️ ตั้งค่าเลือกหน้าสไลด์ (ปัจจุบันเลือกไว้ {len(st.session_state.selected_pages)}/{total_pages} หน้า)"):
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
            st.markdown("### 📊 สรุปข้อมูลก่อนเริ่มสร้างโน้ต")
            pages_to_do = len([i for i in st.session_state.selected_pages if i not in st.session_state.processed_data])
            est_tokens = pages_to_do * 1200
            st.info(f"""
            - หน้าที่ต้องประมวลผลเพิ่ม: **{pages_to_do} หน้า**
            - โหมดสแกนบริบท: **{'⚡ Instant PyMuPDF Index (เสร็จใน 0.1 วินาที)' if st.session_state.fast_index_mode else '🤖 AI Scan ทีละหน้า'}**
            - คาดการณ์ Token ที่ต้องใช้: **~{est_tokens:,} Tokens**
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

    col_run1, col_ctrl2, col_ctrl3 = st.columns([1, 1, 1.5])
    if col_run1.button("🚀 Start / Continue", type="primary", disabled=is_locked, use_container_width=True):
        st.session_state.show_start_popup = True
        st.rerun()
    if col_ctrl2.button("🛑 Stop / Pause", disabled=not st.session_state.is_running, use_container_width=True):
        st.session_state.is_running = False
        st.session_state.stop_clicked = True
        save_workspace()
        st.rerun()
    with col_ctrl3:
        st.session_state.quick_review_mode = st.toggle(
            "⚡ โหมดทวนด่วน (แสดงเฉพาะ สไลด์ + High-Yield + Quiz)",
            value=st.session_state.quick_review_mode
        )

    # --- 8. E-BOOK READER & EDITING ---
    st.write("---")
    st.subheader(f"📖 Clinical E-Book: หน้า {st.session_state.page_idx + 1} / {total_pages}")

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
        st.image(curr_img_bytes, use_container_width=True, caption=f"สไลด์หน้า {curr + 1} (มองภาพควบคู่กับจุดโฟกัสด้านขวา)")

    with col_v2:
        if curr in st.session_state.processed_data:
            data = st.session_state.processed_data[curr]
            if f"editing_{curr}" not in st.session_state:
                st.session_state[f"editing_{curr}"] = False
            display_text = data.get("user_text") if data.get("user_text") else data.get("ai_text", "")

            if st.session_state[f"editing_{curr}"]:
                edited = st.text_area("แก้ไขเนื้อหา:", value=display_text, height=420)
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
                    st.info("ℹ️ หน้านี้ไม่มีเนื้อหาการแพทย์ หรือไม่ได้เลือกประมวลผล")
                else:
                    text_to_render = display_text
                    if st.session_state.quick_review_mode:
                        c_part, hy_part, q_part = split_content_hq(display_text)
                        visual_lines = [line for line in c_part.split("\n") if "จุดโฟกัสบนสไลด์:" in line or "Concept หลัก:" in line]
                        short_head = "\n\n".join(visual_lines)
                        text_to_render = "\n\n".join([p for p in [short_head, hy_part, q_part] if p.strip()])

                    html_content = apply_custom_tags(text_to_render, for_pdf=False)
                    st.markdown(f"<div class='edit-box'>{html_content}</div>", unsafe_allow_html=True)

                if st.button("✏️ พิมพ์แก้ไขเนื้อหานี้"):
                    st.session_state[f"editing_{curr}"] = True
                    if st.session_state.is_running:
                        st.session_state.is_running = False
                        st.warning("⚠️ หยุดรันชั่วคราวเพื่อให้แก้ไขได้สะดวก กด Continue เพื่อรันต่อ")
                    st.rerun()
        else:
            st.info(f"⏳ หน้าที่ {curr+1} ยังไม่ได้ประมวลผล (อยู่ในคิว)...")

    # --- 9. ระบบสร้างไฟล์ PDF ฉบับสมบูรณ์ (แนบสรุป 4 แผ่นท้ายเล่มอัตโนมัติ + บีบอัดเล็กสุดเป็นค่าเริ่มต้น) ---
    st.write("---")
    if len(st.session_state.processed_data) > 0:
        st.subheader("📦 จัดทำและดาวน์โหลดไฟล์ PDF ฉบับสมบูรณ์ (พร้อมสรุป 4 แผ่นท้ายเล่ม)")

        col_opt1, col_opt2 = st.columns([1.4, 1])
        with col_opt1:
            # ตั้งค่า Default (index=0) ให้เป็นบีบอัดขั้นสุด (เล็กที่สุด) เพื่อประหยัดพื้นที่เครื่อง
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
            include_4_sheets = st.checkbox("✅ แนบสรุป One-Sheet 4 แผ่นต่อท้ายไฟล์ PDF", value=True)
            force_regen_sheets = st.checkbox("🔄 บังคับให้ AI เขียนสรุป 4 แผ่นใหม่ทั้งหมด", value=False)

        if st.button("📦 รวบรวมและประกอบไฟล์ PDF ฉบับสมบูรณ์ (พร้อมสรุป 4 แผ่นท้ายเล่ม)", type="primary", use_container_width=True):
            pdf_prog = st.progress(0.0, text="กำลังเตรียมข้อมูลสำหรับสร้าง PDF...")

            # ขั้นตอนที่ 1: สร้างสรุป 4 แผ่นอัตโนมัติหากยังไม่มี หรือหากผู้ใช้สั่งเขียนใหม่
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
                        pdf_prog.progress(min(0.85, prog_val), text=f"กำลังประกอบสไลด์หน้าที่ {i + 1} / {total_pages}...")

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

                    # จัดกรอบพื้นที่ให้สมดุล: ด้านขวา/ซ้ายกินความสูงเต็มหน้า, ด้านล่าง/บนกินความกว้างใต้สไลด์พอดีเพื่อให้ฟอนต์ High-Yield ใหญ่เต็มกรอบ
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
                                .box-visual {{ background-color: #EFF6FF; border-left: 3.5px solid #3B82F6; padding: 3px 8px; margin: 4px 0; }}
                                .box-intro {{ background-color: #F8FAFC; border-left: 3.5px solid #94A3B8; padding: 3px 8px; margin: 4px 0; }}
                                .box-concept {{ background-color: #EEF2FF; border-left: 3.5px solid #6366F1; padding: 3px 8px; margin: 4px 0; }}
                                .box-mech {{ background-color: #F1F5F9; border-left: 3.5px solid #475569; padding: 3px 8px; margin: 4px 0; }}
                                .box-clinic {{ background-color: #F0FDFA; border-left: 3.5px solid #14B8A6; padding: 3px 8px; margin: 4px 0; }}
                                .box-warn {{ background-color: #FFF7ED; border-left: 3.5px solid #F97316; padding: 3px 8px; margin: 4px 0; }}
                                .box-trick {{ background-color: #FEF9C3; border-left: 3.5px solid #EAB308; padding: 3px 8px; margin: 4px 0; }}
                                .box-hy {{ background-color: #FFF1F2; border-left: 4.5px solid #F43F5E; padding: 4px 10px; margin: 4px 0 6px 0; }}
                                .box-quiz {{ background-color: #F0F9FF; border-left: 3.5px solid #0EA5E9; padding: 3px 8px; margin: 4px 0; }}
                                .box-ans {{ background-color: #F0FDF4; border-left: 3.5px solid #22C55E; padding: 3px 8px; margin: 4px 0; }}
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

                # ขั้นตอนที่ 3: แนบแผ่นสรุป One-Sheet Summary ทั้ง 4 แผ่นต่อท้ายเล่มเสมอ
                if include_4_sheets and st.session_state.generated_summary_sheets:
                    pdf_prog.progress(0.88, text="กำลังแนบแผ่นสรุป One-Sheet Summary 4 แผ่นต่อท้ายเล่ม...")
                    sheet_configs = [
                        {"idx": 1, "title": "⭐ CLINICAL ONE-SHEET 1: OVERVIEW & CORE CONCEPTS ⭐", "border_color": "#0EA5E9", "th_bg": "#F8FAFC", "th_color": "#0F172A"},
                        {"idx": 2, "title": "⚙️ CLINICAL ONE-SHEET 2: PATHOPHYSIOLOGY & SYMPTOMS ⚙️", "border_color": "#14B8A6", "th_bg": "#F0FDFA", "th_color": "#0F766E"},
                        {"idx": 3, "title": "🎯 CLINICAL ONE-SHEET 3: DIAGNOSIS & DDX 🎯", "border_color": "#6366F1", "th_bg": "#EEF2FF", "th_color": "#4338CA"},
                        {"idx": 4, "title": "🩺 CLINICAL ONE-SHEET 4: MANAGEMENT & TREATMENT 🩺", "border_color": "#F97316", "th_bg": "#FFF7ED", "th_color": "#C2410C"}
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
                        p_os = doc_out.new_page(width=595, height=842)  # ขนาด A4 มาตรฐาน
                        f_size_os = calc_optimal_fontsize(os_html, 535, 760, is_hy_only=False)
                        css_os = f"""
                        {font_face_css}
                        body {{ font-family: {font_family_val}; font-size: {f_size_os}px; color: #1E293B; line-height: 1.38; margin: 0; padding: 0; }}
                        h2 {{ text-align: center; border-bottom: 2px solid {cfg['border_color']}; color: #0F172A; padding-bottom: 4px; margin-top: 0; font-size: 1.25em; }}
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

                # ขั้นตอนที่ 4: บีบอัดไฟล์ขั้นสุด (ตัดฟอนต์ส่วนเกิน + ย่อรูปสไลด์ + รวบขยะโครงสร้าง PDF)
                pdf_prog.progress(0.95, text="กำลังบีบอัดไฟล์ให้มีขนาดเล็กที่สุด (Ultra Compression)...")

                try:
                    # ตัดชุดตัวอักษรในฟอนต์ที่ไม่ได้ใช้ออกเพื่อลดขนาดไฟล์ฟอนต์ฝังใน PDF
                    doc_out.subset_fonts()
                except Exception:
                    pass

                if "1. บีบอัดขั้นสุด" in comp_level:
                    try:
                        # บีบอัดรูปภาพความละเอียดสูงในสไลด์ต้นฉบับให้เล็กลงโดยยังอ่านชัดเจนบน iPad
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

        # แสดงตัวอย่างแผ่นสรุป 4 แผ่นให้ตรวจทานหรือแก้ไขได้บนเว็บ
        if st.session_state.generated_summary_sheets:
            with st.expander("📋 เปิดดูเนื้อหาสรุป One-Sheet Summary ทั้ง 4 แผ่นที่จะแนบท้ายไฟล์ PDF"):
                tabs = st.tabs(["แผ่น 1: Overview", "แผ่น 2: Patho & อาการ", "แผ่น 3: Diagnosis & DDx", "แผ่น 4: Management"])
                for idx_t, tab in enumerate(tabs, start=1):
                    with tab:
                        st.markdown(st.session_state.generated_summary_sheets.get(idx_t, "ยังไม่มีข้อมูล"))

        if st.session_state.compiled_pdf_bytes:
            sheet_msg = "พร้อมสรุป 4 แผ่นท้ายเล่ม" if include_4_sheets else "เฉพาะสไลด์โน้ต"
            st.success(f"🎉 ประกอบและบีบอัดไฟล์ PDF สำเร็จ ({sheet_msg})! ขนาดไฟล์เหลือเพียง: **{st.session_state.compiled_pdf_size_mb:.2f} MB**")
            st.download_button(
                label=f"💾 คลิกดาวน์โหลดไฟล์ PDF ฉบับสมบูรณ์ ({st.session_state.compiled_pdf_size_mb:.2f} MB)",
                data=st.session_state.compiled_pdf_bytes,
                file_name=f"SmartNote_{st.session_state.pdf_name}",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )

    # --- 10. ระบบประมวลผลหลังบ้าน (Memory-Safe 2-Phase Processor) ---
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
                action_placeholder.markdown("<div class='status-purple'><b>⚡ [Phase 1/2] กำลังดึงโครงสร้างสไลด์ทั้งหมดด้วยระบบ Instant Index...</b></div>", unsafe_allow_html=True)
                doc_idx = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
                try:
                    for idx in st.session_state.selected_pages:
                        if idx not in st.session_state.global_data:
                            raw_t = doc_idx[idx].get_text("text").strip()
                            lines = [ln.strip() for ln in raw_t.split("\n") if ln.strip()]
                            topic = lines[0][:45] if lines else f"สไลด์หน้า {idx+1}"
                            summary = " ".join(lines[1:4])[:140] if len(lines) > 1 else "สไลด์ภาพ/กราฟิก"
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

                    prompt_global = "วิเคราะห์สไลด์หน้านี้ ตอบตามรูปแบบนี้เท่านั้น:\nTOPIC: (ชื่อหัวข้อ 1-3 คำ)\nSUMMARY: (ใจความสำคัญ 1 ประโยคสั้นๆ)"
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
        # PHASE 2: DETAIL SCAN
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
                    icon, msg = "⚡", f"[Phase 2/2] กำลังสรุปหน้าที่ {target+1} (เสร็จแล้ว {done_count}/{len(st.session_state.selected_pages)} หน้าที่เลือก)"

                action_placeholder.markdown(f"<div class='status-{st.session_state.status_mode}'><b>{icon} {msg}</b><br>🤖 โมเดล: <code>{active_m}</code> | ใช้ Sliding Context ประหยัด Token</div>", unsafe_allow_html=True)

                doc_d = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
                p_img = doc_d[target].get_pixmap(dpi=85)
                img = Image.open(io.BytesIO(p_img.tobytes("png")))
                doc_d.close()

                pattern_parts = []
                if want_content:
                    content_instruction = (
                        "รูปแบบการเขียนเนื้อหาหลัก (เขียนชิดซ้าย กระชับ ตรงประเด็น):\n"
                        "จุดโฟกัสบนสไลด์: (ชี้เป้า 1 บรรทัดว่าในสไลด์หน้านี้ต้องมองที่ภาพ กราฟ ตาราง หรือไดอะแกรมจุดไหน และจุดนั้นสำคัญอย่างไร เพื่อเชื่อมภาพเข้ากับความจำ)\n\n"
                        "Concept หลัก: (สรุปแก่นของสไลด์หน้านี้ใน 1-2 ประโยคให้เข้าใจทันทีว่าต้องการสอนอะไร)\n\n"
                        "กลไก/รายละเอียดและอาการ: (ใช้ลูกศรเชื่อมลำดับเหตุการณ์ เช่น `A ➡️ B ➡️ C` พร้อมเน้น **คำสำคัญตัวหนา** และอธิบายเหตุผลด้วยคำว่า **'...เพราะ...'** เสมอ)\n\n"
                        "การนำไปใช้ในคลินิก: (จุดสังเกตผู้ป่วยจริง การส่งตรวจ หรือการรักษา และถ้ามีจุดที่มักสับสนในข้อสอบ ให้ขึ้นบรรทัดใหม่ว่า `ระวัง:` เพื่อเปรียบเทียบจุดตัดแยกโรค)\n"
                    )
                    if want_trick:
                        content_instruction += "\nTrick: (ทริคจำสั้นๆ หรือจุดสังเกตที่ทำให้จำได้แม่นยำ ถ้าหน้านี้ไม่มีจุดต้องใช้ทริค ให้ข้ามหัวข้อนี้ได้)\n"
                    pattern_parts.append(content_instruction)

                if want_summary:
                    pattern_parts.append(
                        "High-Yield:\n"
                        "- KEY1: **(คำสำคัญ/จุดออกสอบที่ 1)** (อธิบายให้ชัดเจน กระชับ อ่านเข้าใจง่ายและจำได้ทันที พร้อมเหตุผลสั้นๆ **เพราะ...**)\n"
                        "- KEY2: **(คำสำคัญ/จุดออกสอบที่ 2)** (อธิบายให้ชัดเจน กระชับ อ่านเข้าใจง่ายและจำได้ทันที ถ้ามีประเด็นสำคัญอีกสามารถเพิ่ม KEY3, KEY4 ได้ตามความเหมาะสม)"
                    )

                if want_quiz:
                    q_lines = "\n".join([f"Q{q_i}: (คำถามสั้นๆ กระตุ้นให้คิดตามจากสไลด์)" for q_i in range(1, quiz_count + 1)])
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
                action_placeholder.markdown("<div class='status-blue' style='border-left-color: #38A169; color: #2F855A; background: #F0FFF4;'><b>✅ ประมวลผลครบทุกหน้าที่เลือกแล้ว!</b><br>กดปุ่มรวบรวมและประกอบไฟล์ PDF ด้านล่างเพื่อรับไฟล์พร้อมสรุป 4 แผ่นท้ายเล่มได้เลยครับ</div>", unsafe_allow_html=True)
