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
    'processed_data': {},  # {page_idx: {'ai_text': '', 'user_text': ''}}
    'page_idx': 0,
    'is_running': False,
    'stop_clicked': False,
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

    # --- บริบทหน้าใกล้เคียง (เพื่อให้ High-Yield เกริ่นเชื่อมโยงจากหน้าก่อนได้ลื่นไหล) ---
    'phase': 'idle',  # idle, global_scan, detail_scan
    'global_data': {},
    'fast_index_mode': True,

    # --- ตัวแปรหน้าเลือกสไลด์ & Custom Prompt ---
    'customizer_page': 0,
    'use_custom_prompt': False,
    'custom_prompt_text': "",

    # --- ตัวแปร PDF ส่งออก ---
    'compiled_pdf_bytes': None,
    'compiled_pdf_size_mb': 0.0
}

for k, v in keys_to_init.items():
    if k not in st.session_state:
        st.session_state[k] = v

st.set_page_config(page_title="High-Yield & Curious Peer Tutor 🧠", layout="wide")

# --- 2. Custom CSS: สะอาด อ่านไว เน้นโฟกัสแค่ 2 ส่วนหลัก ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');

    html, body, [class*="st-"] {
        font-family: 'Sarabun', sans-serif !important;
    }

    .stApp { background-color: #F8FAFC; }
    .main-header { font-size: 2.0rem; font-weight: 800; color: #0F172A; margin-bottom: 0.35rem; letter-spacing: -0.4px; }
    .sub-badge { display: inline-block; background: #E0F2FE; color: #0369A1; padding: 4px 12px; border-radius: 99px; font-weight: 700; font-size: 0.9rem; margin-bottom: 1rem; }
    .stButton>button { border-radius: 8px; transition: all 0.2s; font-weight: 600; font-family: 'Sarabun', sans-serif !important; }
    .stButton>button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }

    .reader-card {
        border: 1px solid #E2E8F0;
        border-radius: 14px;
        padding: 18px 22px;
        background: #FFFFFF;
        font-size: 16.5px;
        line-height: 1.72;
        color: #1E293B;
        box-shadow: 0 4px 14px -2px rgba(0, 0, 0, 0.04);
    }

    /* กล่อง High-Yield Flow */
    .hy-wrapper {
        background: #FFF1F2;
        border-left: 5px solid #E11D48;
        border-radius: 0 10px 10px 0;
        padding: 12px 16px;
        margin-bottom: 16px;
    }
    .hy-title {
        font-weight: 800;
        color: #BE123C;
        font-size: 1.02em;
        margin-bottom: 6px;
    }

    /* กล่องระบบเด็กช่างสงสัย */
    .qa-header {
        background: #EEF2FF;
        border-left: 5px solid #4F46E5;
        border-radius: 0 8px 8px 0;
        padding: 7px 14px;
        font-weight: 800;
        color: #3730A3;
        font-size: 1.0em;
        margin-bottom: 10px;
    }
    .qa-item {
        border-bottom: 1px dashed #CBD5E1;
        padding: 8px 0;
    }
    .qa-item:last-child { border-bottom: none; padding-bottom: 2px; }
    .qa-q {
        color: #1E3A8A;
        font-weight: 700;
        margin-bottom: 3px;
    }
    .qa-a {
        color: #1E293B;
        padding-left: 10px;
        border-left: 3px solid #94A3B8;
    }

    .status-blue { background: #EBF8FF; border-left: 5px solid #3182CE; color: #2B6CB0; padding: 14px; border-radius: 10px; margin-bottom: 15px; }
    .status-yellow { background: #FFFFF0; border-left: 5px solid #D69E2E; color: #B7791F; padding: 14px; border-radius: 10px; margin-bottom: 15px; }
    .status-purple { background: #FAF5FF; border-left: 5px solid #805AD5; color: #553C9A; padding: 14px; border-radius: 10px; margin-bottom: 15px; }
</style>
""", unsafe_allow_html=True)

# --- 3. ระบบจัดการ Workspace, หน่วยความจำ และตัวช่วยคำนวณฟอนต์ ---
WORKSPACE_META_FILE = "autosave_curious_v2_meta.pkl"
WORKSPACE_PDF_FILE = "autosave_curious_v2_source.pdf"

def save_workspace(save_pdf_binary=False):
    if save_pdf_binary and st.session_state.pdf_bytes:
        try:
            with open(WORKSPACE_PDF_FILE, "wb") as f_pdf:
                f_pdf.write(st.session_state.pdf_bytes)
        except Exception:
            pass

    clean_processed = {
        k: {"ai_text": v.get("ai_text", ""), "user_text": v.get("user_text", "")}
        for k, v in st.session_state.processed_data.items()
    }

    data_to_save = {
        'pdf_name': st.session_state.pdf_name,
        'processed_data': clean_processed,
        'global_data': st.session_state.global_data,
        'selected_pages': st.session_state.selected_pages,
        'user_api_key': st.session_state.user_api_key,
        'custom_prompt_text': st.session_state.custom_prompt_text,
        'use_custom_prompt': st.session_state.use_custom_prompt
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
        pix = doc[page_number].get_pixmap(dpi=dpi)
        img_bytes = pix.tobytes("png")
    finally:
        doc.close()
    return img_bytes

def build_local_sliding_context(target_idx, window=2):
    """ส่งบริบทหน้าก่อนหน้าและหน้าถัดไป เพื่อให้ High-Yield เชื่อมเรื่องได้อย่างเป็นธรรมชาติ"""
    lines = []
    sorted_pages = sorted(st.session_state.selected_pages)
    if target_idx in sorted_pages:
        pos = sorted_pages.index(target_idx)
        near_pages = sorted_pages[max(0, pos - window): min(len(sorted_pages), pos + window + 1)]
    else:
        near_pages = [p for p in sorted_pages if abs(p - target_idx) <= window]

    for idx in near_pages:
        g_info = st.session_state.global_data.get(idx, {})
        topic = g_info.get('topic', f"หน้า {idx+1}")
        summary = g_info.get('summary', "")
        if idx < target_idx:
            tag = f"หน้าก่อนหน้า (หน้า {idx+1})"
        elif idx == target_idx:
            tag = f"👉 หน้าปัจจุบัน (หน้า {idx+1})"
        else:
            tag = f"หน้าถัดไป (หน้า {idx+1})"
        lines.append(f"- {tag} [{topic}]: {summary}")
    return "\n".join(lines) if lines else "ไม่มีบริบทหน้าข้างเคียง"

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

def split_hy_and_qa(text):
    """แยกข้อมูลออกเป็น 2 ส่วนชัดเจน: High-Yield Flow และ ระบบเด็กช่างสงสัย (Q&A)"""
    if not text or not text.strip():
        return "", ""

    hy_txt, qa_txt = "", ""
    # รูปแบบมาตรฐานตาม Tag ที่สั่ง AI
    if "===CURIOUS_QA===" in text:
        parts = text.split("===CURIOUS_QA===", 1)
        hy_txt = parts[0].replace("===HIGH_YIELD===", "").strip()
        qa_txt = parts[1].strip()
    elif "===HIGH_YIELD===" in text:
        hy_txt = text.replace("===HIGH_YIELD===", "").strip()
    else:
        # Fallback กรณีผู้ใช้แก้ไขข้อความเองหรือโมเดลหลุด Tag
        m_qa = re.search(r'(?:^|\n)(?:#+\s*)?(?:เด็กช่างสงสัย|CURIOUS_QA|Q1\s*:)', text, flags=re.IGNORECASE)
        if m_qa:
            hy_txt = text[:m_qa.start()].strip()
            qa_txt = text[m_qa.start():].strip()
        else:
            hy_txt = text.strip()

    # ล้างหัวข้อซ้ำที่อาจหลุดมา
    hy_txt = re.sub(r'^(?:#+\s*)?(?:\*\*)?High-Yield(?:\s*Flow)?\s*:?(?:\*\*)?\s*', '', hy_txt, flags=re.IGNORECASE).strip()
    qa_txt = re.sub(r'^(?:#+\s*)?(?:\*\*)?(?:ระบบ)?เด็กช่างสงสัย\s*:?(?:\*\*)?\s*', '', qa_txt, flags=re.IGNORECASE).strip()
    return hy_txt, qa_txt

def format_bold_html(text, color_hex):
    return re.sub(r'\*\*(.*?)\*\*', f"<strong style='color: {color_hex}; font-weight: bold;'>\\1</strong>", text)

def build_hy_html(hy_txt, for_pdf=False):
    if not hy_txt.strip():
        return ""
    styled = format_bold_html(hy_txt.strip(), "#BE123C")
    body_html = markdown.markdown(styled, extensions=['tables'])
    if for_pdf:
        return f"<div class='hy-wrapper'><div class='hy-title'>📌 High-Yield Flow (จับประเด็นเชื่อมโยง)</div>{body_html}</div>"
    return f"<div class='hy-wrapper'><div class='hy-title'>📌 High-Yield Flow (จับประเด็นเชื่อมโยง)</div>{body_html}</div>"

def build_qa_html(qa_txt, for_pdf=False):
    if not qa_txt.strip():
        return ""

    # แยกเป็นคู่ Q / A เพื่อให้จัดหน้ากระชับและอ่านง่ายที่สุด
    lines = [ln.strip() for ln in qa_txt.strip().split('\n') if ln.strip()]
    items = []
    cur_q, cur_a = "", []

    q_pattern = re.compile(r'^(?:[-*]\s*)?(?:\*\*)?Q\d*\s*[:\.](?:\*\*)?\s*(.*)', re.IGNORECASE)
    a_pattern = re.compile(r'^(?:[-*]\s*)?(?:\*\*)?A\d*\s*[:\.](?:\*\*)?\s*(.*)', re.IGNORECASE)

    for ln in lines:
        mq = q_pattern.match(ln)
        ma = a_pattern.match(ln)
        if mq:
            if cur_q or cur_a:
                items.append((cur_q, " ".join(cur_a)))
            cur_q = mq.group(1).strip()
            cur_a = []
        elif ma:
            cur_a.append(ma.group(1).strip())
        else:
            if cur_a:
                cur_a.append(ln)
            elif cur_q:
                cur_q += " " + ln
            else:
                cur_a.append(ln)

    if cur_q or cur_a:
        items.append((cur_q, " ".join(cur_a)))

    html_parts = ["<div class='qa-header'>🙋‍♂️ เด็กช่างสงสัย (เรียงจากสำคัญที่สุด)</div>"]
    if items:
        for idx, (q_text, a_text) in enumerate(items, start=1):
            q_html = format_bold_html(q_text, "#1E3A8A")
            a_html = format_bold_html(a_text, "#B91C1C")
            block = "<div class='qa-item'>"
            if q_html:
                block += f"<div class='qa-q'>Q{idx}: {q_html}</div>"
            if a_html:
                block += f"<div class='qa-a'><b>A:</b> {a_html}</div>"
            block += "</div>"
            html_parts.append(block)
    else:
        fallback = markdown.markdown(format_bold_html(qa_txt, "#B91C1C"), extensions=['tables'])
        html_parts.append(fallback)

    return "".join(html_parts)

def calc_optimal_fontsize(html_text, rect_width, rect_height, is_hy_only=False):
    """จำลองการตัดบรรทัดภาษาไทยเพื่อขยายขนาดฟอนต์ให้เต็มกรอบพอดีโดยไม่ล้นขอบ"""
    if not html_text or rect_width <= 0 or rect_height <= 0:
        return 18

    block_split = re.sub(r'</?(li|p|div|tr|h\d|br)[^>]*>', '\n', html_text)
    raw_lines = [re.sub(r'<[^>]+>', '', ln).strip() for ln in block_split.split('\n')]
    raw_lines = [ln for ln in raw_lines if ln]
    if not raw_lines:
        return 18

    thai_combining = r'[\u0E31\u0E34-\u0E3A\u0E47-\u0E4E]'
    eff_lengths = [max(1, len(re.sub(thai_combining, '', ln))) for ln in raw_lines]
    num_blocks = len(eff_lengths)

    max_f = 48 if is_hy_only else 34
    min_f = 16 if is_hy_only else 12
    char_width_factor = 0.39 if is_hy_only else 0.41
    line_height_factor = 1.34 if is_hy_only else 1.36
    target_fill_ratio = 0.90 if is_hy_only else 0.87

    for f_size in range(max_f, min_f - 1, -1):
        usable_w = max(40.0, rect_width - 22.0)
        chars_per_line = max(8.0, usable_w / (f_size * char_width_factor))

        total_lines = sum(math.ceil(length / chars_per_line) for length in eff_lengths)
        block_spacing_lines = num_blocks * (0.20 if is_hy_only else 0.24)
        est_height = (total_lines + block_spacing_lines) * (f_size * line_height_factor)

        if est_height <= rect_height * target_fill_ratio:
            return f_size

    return min_f

def get_layout_preview(hy_pos, qa_pos):
    layout_map = {"ด้านขวา": [], "ด้านล่าง": [], "ด้านซ้าย": [], "ด้านบน": []}
    layout_map[hy_pos].append("<span style='color: #BE123C;'><b>📌 High-Yield Flow</b></span>")
    layout_map[qa_pos].append("<span style='color: #3730A3;'><b>🙋‍♂️ เด็กช่างสงสัย (Q&A)</b></span>")

    right_box = f"<div style='flex: 0.42; background: #F8FAFC; padding: 6px; font-size: 8.5px; border-left: 1px solid #CBD5E1; display:flex; flex-direction:column; justify-content:center; gap:6px;'>{'<br>'.join(layout_map['ด้านขวา'])}</div>" if layout_map['ด้านขวา'] else ""
    left_box = f"<div style='flex: 0.42; background: #F8FAFC; padding: 6px; font-size: 8.5px; border-right: 1px solid #CBD5E1; display:flex; flex-direction:column; justify-content:center; gap:6px;'>{'<br>'.join(layout_map['ด้านซ้าย'])}</div>" if layout_map['ด้านซ้าย'] else ""
    bottom_box = f"<div style='min-height: 36px; background: #FFF1F2; padding: 5px; font-size: 8.5px; border-top: 1px solid #FECDD3; text-align: center; display:flex; align-items:center; justify-content:center;'>{' &nbsp;|&nbsp; '.join(layout_map['ด้านล่าง'])}</div>" if layout_map['ด้านล่าง'] else ""
    top_box = f"<div style='min-height: 36px; background: #FFF1F2; padding: 5px; font-size: 8.5px; border-bottom: 1px solid #FECDD3; text-align: center; display:flex; align-items:center; justify-content:center;'>{' &nbsp;|&nbsp; '.join(layout_map['ด้านบน'])}</div>" if layout_map['ด้านบน'] else ""

    html_str = f"""
    <div style="width: 100%; height: 165px; border-radius: 10px; background: white; border: 2px solid #CBD5E1; display: flex; flex-direction: column; overflow: hidden;">
        {top_box}
        <div style="flex: 1; display: flex; flex-direction: row;">
            {left_box}
            <div style="flex: 1; background: #F1F5F9; border: 2px dashed #94A3B8; margin: 6px; display: flex; align-items: center; justify-content: center; font-size: 11px; color: #475569; font-weight: bold; border-radius: 6px;">สไลด์ต้นฉบับ</div>
            {right_box}
        </div>
        {bottom_box}
    </div>
    """
    st.markdown(html_str, unsafe_allow_html=True)

# --- 4. Sidebar: ตั้งค่าแบบกระชับ เหลือเฉพาะสิ่งที่จำเป็นจริง ---
with st.sidebar:
    st.markdown("<h2 style='color: #0F172A;'>🧠 ตั้งค่าการติว (Lean Mode)</h2>", unsafe_allow_html=True)
    is_locked = st.session_state.is_running

    api_input = st.text_input("🔑 Gemini API Key:", type="password", value=st.session_state.user_api_key, disabled=is_locked)
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
                st.info("🔒 ล็อกการตั้งค่าขณะประมวลผล")
            else:
                display_options, model_map = [], {}
                for m in st.session_state.flash_models_list:
                    status = "⏳ [รอ]" if m in st.session_state.exhausted_models else "✅ [พร้อม]"
                    opt = f"{status} {m}"
                    display_options.append(opt)
                    model_map[opt] = m
                selected_display = st.selectbox("AI Model (สลับอัตโนมัติ):", display_options, index=0)
                st.session_state.current_active_model = model_map[selected_display]
        except Exception:
            st.error("API Key ไม่ถูกต้อง หรือไม่สามารถดึงรายชื่อโมเดลได้")

    token_used = st.session_state.estimated_tokens_used
    st.caption(f"💳 Token ที่ใช้ไป: **{token_used:,}**")

    st.divider()
    med_year = st.selectbox(
        "ระดับชั้น / เป้าหมาย:",
        ["นสพ. ปี 4 (ชั้นคลินิก / NL1)", "นสพ. ปี 5 (Clinical)", "นสพ. ปี 6 (NL2 / Comprehensive)", "นสพ. พรีคลินิก (ปี 2-3)"],
        index=0,
        disabled=is_locked
    )
    q_min, q_max = st.slider(
        "🙋‍♂️ จำนวนคำถามเด็กช่างสงสัย (ขั้นต่ำ - สูงสุด/หน้า):",
        min_value=1, max_value=7, value=(2, 5),
        disabled=is_locked,
        help="AI จะปรับจำนวนข้อตามความแน่นของเนื้อหาในหน้านั้นโดยไม่ฝืนปั้นคำถามไร้สาระ"
    )
    max_tokens = st.number_input("Max Output Tokens:", min_value=300, max_value=4096, value=1800, step=200, disabled=is_locked)

    st.divider()
    st.markdown("### 📐 ตำแหน่งวางบนกระดาษ PDF")
    pos_options = ["ด้านบน", "ด้านล่าง", "ด้านขวา", "ด้านซ้าย"]
    hy_pos = st.selectbox("วาง [📌 High-Yield Flow] ไว้ที่:", pos_options, index=0, disabled=is_locked)
    qa_pos = st.selectbox("วาง [🙋‍♂️ เด็กช่างสงสัย Q&A] ไว้ที่:", pos_options, index=2, disabled=is_locked)

    margin_side_pct = st.slider("พื้นที่ขยาย ด้านซ้าย/ขวา (%):", 0, 100, 52, disabled=is_locked)
    margin_vert_pct = st.slider("พื้นที่ขยาย ด้านบน/ล่าง (%):", 0, 100, 32, disabled=is_locked)
    get_layout_preview(hy_pos, qa_pos)

    st.divider()
    # --- Prompt หลักที่ฝังแนวคิด High-Yield Flow + เกณฑ์เด็กช่างสงสัย 5 ระดับ ---
    base_prompt_template = f"""คุณทำหน้าที่ 2 บทบาทพร้อมกันให้ {med_year} เพื่อให้ผู้อ่านเข้าใจเชื่อมโยงได้ในที่เดียวและไม่เสียเวลาอ่านน้ำท่วมทุ่ง

**บริบทหน้าใกล้เคียง (ใช้เชื่อมโยงเรื่องจากหน้าก่อนแบบเนียนๆ):**
{{global_context}}

**กฎการเขียนเด็ดขาด:**
- ห้ามทักทาย ห้ามเกริ่นนำนอกเรื่อง
- เน้น **ตัวหนาที่คำสำคัญ (Keywords / จุดตัด / กลไกหลัก)** เสมอ เพื่อให้สายตากวาดจับได้ทันที
- หากหน้านี้เป็นหน้าปก หน้าคั่น หรือไม่มีเนื้อหาวิชาการ ให้ตอบสั้นๆ แค่คำว่า `NON_CONTENT` เท่านั้น
- ตอบตามโครงสร้าง 2 ส่วนนี้เท่านั้น โดยใช้ตัวคั่น `===HIGH_YIELD===` และ `===CURIOUS_QA===` ให้ตรงเป๊ะ:

===HIGH_YIELD===
(เขียนเป็น **คำพูดเกริ่นนำผสานเนื้อหาสำคัญของหน้านี้** ความยาวกระชับ 3–5 ประโยคใน 1 ย่อหน้าเดียวจบ ให้ผู้อ่านอ่านแค่ตรงนี้ก็เก็ตทันทีว่า:
1. หน้านี้เชื่อมโยงมาจากเรื่องก่อนหน้าหรือภาพรวมอย่างไร และกำลังอธิบายแก่นอะไร (ถ้ามีภาพ/ตารางสำคัญในสไลด์ ให้สรุปจุดที่ต้องมองแบบเนียนๆ เข้าไปในประโยคเลย)
2. สิ่งที่ต้องจำไปใช้จริง จุดสังเกต หรือข้อควรระวัง/กับดักสำคัญคืออะไร พร้อมเหตุผลสั้นๆ ว่า **เพราะอะไร**
**สำคัญมากเรื่องสำนวน:** ห้ามใช้โครงสร้างประโยคซ้ำๆ แบบหุ่นยนต์ (อย่าขึ้นต้นด้วย "เมื่อทราบ..." ทุกหน้า) ให้เปลี่ยนลีลาการเปิดเรื่องอย่างเป็นธรรมชาติและอ่านลื่นไหลตามเนื้อหาแต่ละหน้า เช่น เปิดด้วยจุดเชื่อมกลไก, เปิดด้วยปัญหาหน้างาน, เปิดด้วยจุดที่คนมักเข้าใจผิด หรือเปิดด้วยภาพรวม)

===CURIOUS_QA===
(สวมบท **"เพื่อนร่วมเรียนหัวกะทิที่ช่างสงสัย"** นั่งเรียนข้างๆ แล้วถามอาจารย์แทนผู้อ่านในเรื่องที่ผู้อ่านมักมองข้าม ให้สร้างคำถาม-คำตอบจำนวน **{q_min} ถึง {q_max} ข้อ** ตามความแน่นของเนื้อหาจริงในหน้านี้ **เรียงข้อที่สำคัญที่สุดไว้ข้อแรกๆ**)

**เกณฑ์คัดกรอง "คำถามที่ดี" (เลือกใช้และเรียงลำดับตามน้ำหนักความสำคัญ 5 ประเภทนี้):**
1. **Why-Mechanism (ถามหาเหตุผลเบื้องหลัง):** ไม่ถามว่า "คืออะไร" แต่ถามว่า "ทำไมกลไกนี้ถึงเกิดผลลัพธ์แบบนี้?" หรือ "ทำไมต้องใช้เกณฑ์/ตัวเลขนี้?" เพื่อเชื่อมเหตุไปหาผลโดยไม่ต้องท่องจำ
2. **Why-This-Not-That (ถามจุดตัดและกับดัก):** "ทำไมเคสนี้ต้องเลือก A แทน B ทั้งที่ดูคล้ายกัน?" หรือ "ถ้าเผลอทำ X จะเกิดผลเสียอะไรตามมา?" เพื่อดักจุดที่มักสับสนในห้องสอบและหน้างานจริง
3. **What-If / Boundary (ถามข้อยกเว้น/จุดพลิกเกม):** "แล้วถ้าผู้ป่วยมีเงื่อนไขพิเศษแบบนี้ แนวทางในหน้านี้ยังใช้ได้ไหม หรือต้องเปลี่ยน?" เพื่ออุดช่องโหว่ที่สไลด์พูดแค่กรณีมาตรฐาน
4. **So-What (ถามเชื่อมสู่การใช้งานจริง):** "รู้ข้อมูล/ค่านี้แล้ว มันเปลี่ยนการตัดสินใจวินิจฉัยหรือรักษาอย่างไร?" ไม่ให้จำข้อมูลลอยๆ
5. **Hidden Assumption (ถามรอยต่อที่อาจารย์ละไว้ในฐานที่เข้าใจ):** จุดที่คนสอนข้ามไปเพราะนึกว่าคนเรียนรู้อยู่แล้ว แต่จริงๆ เป็นจุดที่ทำให้ต่อเรื่องไม่ติด

**คำถามต้องห้าม (ตัดทิ้งเด็ดขาด ห้ามสร้างเด็ดขาด):**
- ❌ คำถามนิยาม/ความจำผิวเผินแบบ Flashcard เช่น "มีกี่ชนิด?", "ย่อมาจากอะไร?", "ค่าปกติคือเท่าไหร่?"
- ❌ คำถามลึกเกินระดับชั้น {med_year} ที่ไม่ช่วยทำข้อสอบหรือดูแลคนไข้
- ❌ คำถามที่คำตอบไปซ้ำกับสิ่งที่เขียนอธิบายไว้แล้วในส่วน `===HIGH_YIELD===`

**รูปแบบการเขียน (ต้องกระชับ ประหยัดพื้นที่กระดาษ 1-2 ประโยคต่อคำตอบ):**
Q1: (คำถามที่คมและสำคัญที่สุด)
A1: (คำตอบตรงประเด็น อธิบายเหตุผลชัดเจน เน้น **ตัวหนาคำสำคัญ**)
Q2: ...
A2: ..."""

    with st.expander("🛠️ ดู/ปรับแต่ง Prompt หลัก"):
        use_custom_prompt = st.checkbox("แก้ไข Prompt เอง", value=st.session_state.use_custom_prompt, disabled=is_locked)
        if use_custom_prompt:
            st.session_state.custom_prompt_text = st.text_area(
                "Prompt (ห้ามลบ {global_context} และตัวคั่น ===HIGH_YIELD=== / ===CURIOUS_QA===)",
                value=st.session_state.custom_prompt_text or base_prompt_template,
                height=260,
                disabled=is_locked
            )
        else:
            st.session_state.custom_prompt_text = base_prompt_template
        st.session_state.use_custom_prompt = use_custom_prompt

    current_settings = {
        "year": med_year, "q_range": (q_min, q_max), "max_tok": max_tokens,
        "hy_pos": hy_pos, "qa_pos": qa_pos,
        "m_side": margin_side_pct, "m_vert": margin_vert_pct
    }
    if not is_locked and st.session_state.last_settings and current_settings != st.session_state.last_settings:
        st.session_state.settings_changed_alert = True
    st.session_state.last_settings = current_settings

# --- 5. หน้าหลัก: อัปโหลด / กู้คืนไฟล์ ---
st.markdown("<div class='main-header'>🧠 High-Yield Flow & Curious Peer Tutor</div>", unsafe_allow_html=True)
st.markdown("<div class='sub-badge'>✨ ตัดส่วนเกินทั้งหมด เหลือแค่: อ่านเชื่อมโยงจบในที่เดียว + เพื่อนช่างสงสัยถามจุดสำคัญแทนคุณ</div>", unsafe_allow_html=True)

if not st.session_state.pdf_bytes:
    if os.path.exists(WORKSPACE_META_FILE) and os.path.exists(WORKSPACE_PDF_FILE):
        st.info("💾 **พบงานที่ทำค้างไว้!** กดกู้คืนเพื่อทำต่อได้ทันที")
        if st.button("🔄 กู้คืนงานเดิม", type="primary"):
            if load_workspace():
                st.rerun()
            else:
                st.error("ไม่สามารถกู้คืนไฟล์ได้")

    uploaded_file = st.file_uploader("อัปโหลดสไลด์หรือชีทเรียน (PDF)", type="pdf")
    if uploaded_file:
        with st.spinner(f"กำลังนำเข้า {uploaded_file.name}..."):
            st.session_state.pdf_bytes = uploaded_file.getvalue()
            st.session_state.pdf_name = uploaded_file.name
            doc_tmp = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
            total_p = len(doc_tmp)
            doc_tmp.close()
            st.session_state.selected_pages = list(range(total_p))
            save_workspace(save_pdf_binary=True)
        st.rerun()
else:
    doc_meta = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
    total_pages = len(doc_meta)
    doc_meta.close()

    col_info1, col_info2 = st.columns([3.2, 1])
    with col_info1:
        st.info(f"📄 ไฟล์ปัจจุบัน: **{st.session_state.pdf_name}** ({total_pages} หน้า | ประมวลผลแล้ว **{len(st.session_state.processed_data)}/{len(st.session_state.selected_pages)} หน้า**)")
    with col_info2:
        if st.button("🗑️ เปลี่ยนไฟล์ (Reset)", use_container_width=True):
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

# --- 6. เลือกหน้าสไลด์ (Paginated) ---
if st.session_state.pdf_bytes and not is_locked:
    if "expander_open" not in st.session_state:
        st.session_state.expander_open = False

    if st.session_state.expander_open:
        with st.expander(f"🖼️ เลือกหน้าที่ต้องการประมวลผล ({len(st.session_state.selected_pages)}/{total_pages} หน้า)", expanded=True):
            c_btn1, c_btn2, c_btn3, c_btn4 = st.columns([1, 1, 2, 1.5])
            if c_btn1.button("✅ เลือกทั้งหมด", use_container_width=True):
                st.session_state.selected_pages = list(range(total_pages))
                st.rerun()
            if c_btn2.button("❌ ล้างที่เลือก", use_container_width=True):
                st.session_state.selected_pages = []
                st.rerun()
            with c_btn3:
                range_input = st.text_input("ช่วงหน้า:", label_visibility="collapsed", placeholder="ระบุช่วงหน้า เช่น 1-20, 25, 30-50")
            if c_btn4.button("🎯 เลือกตามช่วง", use_container_width=True) and range_input:
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
            cust_page = st.number_input(f"ชุดตัวอย่างหน้า (1 - {max_cust_pages}):", min_value=1, max_value=max_cust_pages, value=st.session_state.customizer_page + 1) - 1
            st.session_state.customizer_page = cust_page

            start_idx = cust_page * ITEMS_PER_PAGE
            end_idx = min(total_pages, start_idx + ITEMS_PER_PAGE)

            doc_thumb = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
            try:
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
            finally:
                doc_thumb.close()

            if st.button("💾 ยืนยันหน้าและพับเก็บ", type="primary", use_container_width=True):
                st.session_state.expander_open = False
                save_workspace()
                st.rerun()
    else:
        if st.button(f"⚙️ เลือกหน้าสไลด์ (เลือกไว้ {len(st.session_state.selected_pages)}/{total_pages} หน้า)"):
            st.session_state.expander_open = True
            st.rerun()

# --- 7. ปุ่มควบคุมการรัน ---
if st.session_state.pdf_bytes:
    if st.session_state.settings_changed_alert and not st.session_state.is_running:
        st.info("🔔 เปลี่ยนการตั้งค่าแล้ว: หน้าถัดไป (หรือการสร้าง PDF ใหม่) จะใช้ค่าใหม่ทันที")
        st.session_state.settings_changed_alert = False

    if st.session_state.show_start_popup:
        pages_to_do = len([i for i in st.session_state.selected_pages if i not in st.session_state.processed_data])
        st.info(f"🚀 พร้อมประมวลผลเพิ่ม **{pages_to_do} หน้า** (คาดการณ์ ~{pages_to_do * 700:,} Tokens — ประหยัดกว่าเดิมเกือบครึ่ง)")
        c_s1, c_s2 = st.columns(2)
        if c_s1.button("✅ เริ่มเลย", type="primary", use_container_width=True):
            if not api_key:
                st.error("กรุณาใส่ Gemini API Key ที่แถบด้านซ้ายก่อนครับ")
            else:
                if not st.session_state.current_active_model or st.session_state.current_active_model in st.session_state.exhausted_models:
                    st.session_state.current_active_model = get_best_available_model(st.session_state.flash_models_list)
                if st.session_state.phase == 'idle':
                    st.session_state.phase = 'global_scan'
                st.session_state.is_running = True
                st.session_state.stop_clicked = False
                st.session_state.show_start_popup = False
                st.rerun()
        if c_s2.button("❌ ยกเลิก", use_container_width=True):
            st.session_state.show_start_popup = False
            st.rerun()

    action_placeholder = st.empty()

    c_run1, c_run2 = st.columns(2)
    if c_run1.button("🚀 Start / Continue", type="primary", disabled=is_locked, use_container_width=True):
        st.session_state.show_start_popup = True
        st.rerun()
    if c_run2.button("🛑 Stop / Pause", disabled=not st.session_state.is_running, use_container_width=True):
        st.session_state.is_running = False
        st.session_state.stop_clicked = True
        save_workspace()
        st.rerun()

    # --- 8. หน้าจออ่านและแก้ไขทีละหน้า ---
    st.write("---")
    st.subheader(f"📖 หน้า {st.session_state.page_idx + 1} / {total_pages}")

    c_nav1, c_nav2, c_nav3 = st.columns([1, 2.5, 1])
    with c_nav1:
        if st.button("⬅️ ก่อนหน้า", use_container_width=True) and st.session_state.page_idx > 0:
            st.session_state.page_idx -= 1
            st.rerun()
    with c_nav2:
        new_page = st.slider("ไปหน้า:", 1, total_pages, st.session_state.page_idx + 1, label_visibility="collapsed")
        if new_page - 1 != st.session_state.page_idx:
            st.session_state.page_idx = new_page - 1
            st.rerun()
    with c_nav3:
        if st.button("ถัดไป ➡️", use_container_width=True) and st.session_state.page_idx < total_pages - 1:
            st.session_state.page_idx += 1
            st.rerun()

    curr = st.session_state.page_idx
    col_v1, col_v2 = st.columns([1.1, 1])

    with col_v1:
        curr_img_bytes = render_page_png(st.session_state.pdf_bytes, curr, dpi=120)
        st.image(curr_img_bytes, use_container_width=True, caption=f"สไลด์หน้า {curr + 1}")

    with col_v2:
        if curr in st.session_state.processed_data:
            data = st.session_state.processed_data[curr]
            edit_key = f"editing_{curr}"
            if edit_key not in st.session_state:
                st.session_state[edit_key] = False

            display_text = data.get("user_text") or data.get("ai_text", "")

            if st.session_state[edit_key]:
                edited = st.text_area("แก้ไขข้อความ (คงตัวคั่น ===HIGH_YIELD=== และ ===CURIOUS_QA=== ไว้):", value=display_text, height=380)
                ce1, ce2 = st.columns(2)
                if ce1.button("💾 บันทึกการแก้ไข", type="primary", use_container_width=True):
                    st.session_state.processed_data[curr]["user_text"] = edited
                    st.session_state[edit_key] = False
                    save_workspace()
                    st.rerun()
                if ce2.button("🔄 คืนค่าต้นฉบับ AI", use_container_width=True):
                    st.session_state.processed_data[curr]["user_text"] = ""
                    st.session_state[edit_key] = False
                    save_workspace()
                    st.rerun()
            else:
                if not display_text.strip():
                    st.info("ℹ️ หน้านี้ไม่มีเนื้อหาวิชาการ (ข้ามอัตโนมัติ)")
                elif "⚠️" in display_text:
                    st.error(display_text)
                else:
                    hy_txt, qa_txt = split_hy_and_qa(display_text)
                    rendered_html = build_hy_html(hy_txt, for_pdf=False) + build_qa_html(qa_txt, for_pdf=False)
                    st.markdown(f"<div class='reader-card'>{rendered_html}</div>", unsafe_allow_html=True)

                c_ed1, c_ed2 = st.columns(2)
                if c_ed1.button("✏️ แก้ไขหน้านี้", use_container_width=True):
                    st.session_state[edit_key] = True
                    st.session_state.is_running = False
                    st.rerun()
                if c_ed2.button("🔄 สร้างหน้านี้ใหม่", disabled=is_locked, use_container_width=True):
                    del st.session_state.processed_data[curr]
                    save_workspace()
                    st.session_state.phase = 'detail_scan'
                    st.session_state.is_running = True
                    st.session_state.stop_clicked = False
                    st.rerun()
        else:
            st.info(f"⏳ หน้าที่ {curr+1} ยังไม่ได้ประมวลผล")

    # --- 9. ประกอบไฟล์ PDF (จัดวางตามตำแหน่งที่ผู้ใช้เลือก บน/ซ้าย/ขวา/ล่าง + บีบอัดประหยัดพื้นที่) ---
    st.write("---")
    if len(st.session_state.processed_data) > 0:
        st.subheader("📦 ส่งออกไฟล์ PDF (วางตำแหน่งตามตั้งค่า + ฟอนต์ปรับขนาดอัตโนมัติ)")

        comp_level = st.selectbox(
            "🗜️ ระดับการบีบอัดไฟล์ PDF:",
            [
                "1. บีบอัดขั้นสุด (ไฟล์เล็กที่สุด ประหยัดพื้นที่เครื่อง - แนะนำ)",
                "2. บีบอัดสมดุล (ขนาดกลาง ภาพคมชัด)",
                "3. บีบอัดน้อย (รักษาความคมชัดต้นฉบับสูงสุด)"
            ],
            index=0
        )

        if st.button("📦 ประกอบไฟล์ PDF", type="primary", use_container_width=True):
            pdf_prog = st.progress(0.0, text="กำลังเริ่มประกอบไฟล์ PDF...")
            doc_in = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
            doc_out = fitz.open()
            arch = fitz.Archive(".")
            has_custom_font = os.path.exists("THSarabunNew.ttf")

            font_face_css = """
            @font-face { font-family: 'T'; src: url('THSarabunNew.ttf'); }
            @font-face { font-family: 'T'; font-weight: bold; src: url('THSarabunNew Bold.ttf'); }
            """ if has_custom_font else ""
            font_family_val = "'T', sans-serif" if has_custom_font else "sans-serif"

            try:
                used_positions = {hy_pos, qa_pos}
                for i in range(total_pages):
                    if i % 3 == 0 or i == total_pages - 1:
                        pdf_prog.progress(min(0.88, (i + 1) / total_pages * 0.88), text=f"กำลังจัดวางหน้า {i + 1} / {total_pages}...")

                    p_in = doc_in[i]
                    w, h = p_in.rect.width, p_in.rect.height

                    pad_left = (w * (margin_side_pct / 100.0)) if ("ด้านซ้าย" in used_positions and margin_side_pct > 0) else 0
                    pad_right = (w * (margin_side_pct / 100.0)) if ("ด้านขวา" in used_positions and margin_side_pct > 0) else 0
                    pad_top = (h * (margin_vert_pct / 100.0)) if ("ด้านบน" in used_positions and margin_vert_pct > 0) else 0
                    pad_bottom = (h * (margin_vert_pct / 100.0)) if ("ด้านล่าง" in used_positions and margin_vert_pct > 0) else 0

                    new_w = w + pad_left + pad_right
                    new_h = h + pad_top + pad_bottom

                    p_out = doc_out.new_page(width=new_w, height=new_h)
                    bg_color = (0.98, 0.99, 1.0)
                    p_out.draw_rect(fitz.Rect(0, 0, new_w, new_h), color=bg_color, fill=bg_color, width=0)

                    slide_rect = fitz.Rect(pad_left, pad_top, pad_left + w, pad_top + h)
                    p_out.show_pdf_page(slide_rect, doc_in, i)

                    rects = {
                        "ด้านขวา": fitz.Rect(pad_left + w + 10, 10, new_w - 10, new_h - 10) if pad_right > 25 else None,
                        "ด้านซ้าย": fitz.Rect(10, 10, pad_left - 10, new_h - 10) if pad_left > 25 else None,
                        "ด้านล่าง": fitz.Rect(pad_left + 10, pad_top + h + 8, pad_left + w - 10, new_h - 8) if pad_bottom > 25 else None,
                        "ด้านบน": fitz.Rect(pad_left + 10, 8, pad_left + w - 10, pad_top - 8) if pad_top > 25 else None
                    }

                    if i in st.session_state.processed_data:
                        raw_txt = st.session_state.processed_data[i].get("user_text") or st.session_state.processed_data[i].get("ai_text", "")
                        if raw_txt and "⚠️" not in raw_txt:
                            hy_txt, qa_txt = split_hy_and_qa(raw_txt)
                            box_buckets = {"ด้านขวา": [], "ด้านล่าง": [], "ด้านซ้าย": [], "ด้านบน": []}
                            if hy_txt:
                                box_buckets[hy_pos].append(("hy", build_hy_html(hy_txt, for_pdf=True)))
                            if qa_txt:
                                box_buckets[qa_pos].append(("qa", build_qa_html(qa_txt, for_pdf=True)))

                            for pos, items in box_buckets.items():
                                box = rects.get(pos)
                                if not items or box is None or box.is_empty or box.is_infinite:
                                    continue

                                combined_html = "".join(h_part for _, h_part in items)
                                is_hy_only = (len(items) == 1 and items[0][0] == "hy")
                                f_size = calc_optimal_fontsize(combined_html, box.width, box.height, is_hy_only=is_hy_only)
                                line_h = "1.32" if is_hy_only else "1.34"

                                css = f"""
                                {font_face_css}
                                body {{ font-family: {font_family_val}; font-size: {f_size}px; line-height: {line_h}; color: #0F172A; margin: 0; padding: 0; }}
                                b, strong {{ font-weight: bold; }}
                                p {{ margin: 2px 0 4px 0; }}
                                .hy-wrapper {{ background-color: #FFF1F2; border-left: 5px solid #E11D48; padding: 5px 10px; margin-bottom: 6px; }}
                                .hy-title {{ font-weight: bold; color: #BE123C; margin-bottom: 3px; }}
                                .qa-header {{ background-color: #EEF2FF; border-left: 4px solid #4F46E5; padding: 3px 8px; font-weight: bold; color: #3730A3; margin-bottom: 5px; }}
                                .qa-item {{ border-bottom: 1px solid #E2E8F0; padding: 4px 0; }}
                                .qa-q {{ color: #1E3A8A; font-weight: bold; margin-bottom: 2px; }}
                                .qa-a {{ color: #1E293B; padding-left: 6px; border-left: 2px solid #94A3B8; }}
                                """
                                try:
                                    p_out.insert_htmlbox(box, f"<style>{css}</style><body>{combined_html}</body>", archive=arch)
                                except Exception:
                                    try:
                                        plain_fb = re.sub(r'<[^>]+>', '', combined_html)
                                        p_out.insert_htmlbox(box, f"<body>{plain_fb}</body>")
                                    except Exception:
                                        pass

                pdf_prog.progress(0.94, text="กำลังบีบอัดไฟล์ PDF...")
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

        if st.session_state.compiled_pdf_bytes:
            st.success(f"🎉 สร้างไฟล์ PDF สำเร็จ! ขนาดไฟล์: **{st.session_state.compiled_pdf_size_mb:.2f} MB**")
            st.download_button(
                label=f"💾 ดาวน์โหลด PDF ({st.session_state.compiled_pdf_size_mb:.2f} MB)",
                data=st.session_state.compiled_pdf_bytes,
                file_name=f"HighYield_Curious_{st.session_state.pdf_name}",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )

    # --- 10. ระบบประมวลผลเบื้องหลัง ---
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

        # PHASE 1: Instant Context Scan (ดึงหัวข้อหน้าก่อน/หลังเพื่อใช้เชื่อมโยง)
        if st.session_state.phase == 'global_scan':
            action_placeholder.markdown("<div class='status-purple'><b>⚡ [1/2] กำลังอ่านโครงสร้างสไลด์เพื่อเชื่อมโยงบริบทแต่ละหน้า...</b></div>", unsafe_allow_html=True)
            doc_idx = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
            try:
                for idx in st.session_state.selected_pages:
                    if idx not in st.session_state.global_data:
                        raw_t = doc_idx[idx].get_text("text").strip()
                        lines = [ln.strip() for ln in raw_t.split("\n") if ln.strip()]
                        topic = lines[0][:50] if lines else f"หน้า {idx+1}"
                        summary = " ".join(lines[1:4])[:140] if len(lines) > 1 else "สไลด์ภาพ/แผนภาพ"
                        st.session_state.global_data[idx] = {'topic': topic, 'summary': summary}
            finally:
                doc_idx.close()

            st.session_state.phase = 'detail_scan'
            save_workspace()
            st.rerun()

        # PHASE 2: สร้าง High-Yield Flow + เด็กช่างสงสัย ทีละหน้า
        elif st.session_state.phase == 'detail_scan':
            target = next(
                (i for i in st.session_state.selected_pages
                 if i in st.session_state.processed_data and "⚠️" in st.session_state.processed_data[i].get("ai_text", "")),
                None
            )
            is_recheck = target is not None
            if target is None:
                target = next((i for i in st.session_state.selected_pages if i not in st.session_state.processed_data), None)

            if target is not None:
                done_count = len([k for k in st.session_state.selected_pages if k in st.session_state.processed_data and "⚠️" not in st.session_state.processed_data[k].get("ai_text", "")])
                mode_cls = "yellow" if is_recheck else "blue"
                label = f"🔄 ซ่อมหน้าที่ Error (หน้า {target+1})" if is_recheck else f"🧠 กำลังวิเคราะห์หน้า {target+1} (เสร็จแล้ว {done_count}/{len(st.session_state.selected_pages)} หน้า)"
                action_placeholder.markdown(f"<div class='status-{mode_cls}'><b>{label}</b><br>🤖 โมเดล: <code>{active_m}</code></div>", unsafe_allow_html=True)

                doc_d = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
                try:
                    p_img = doc_d[target].get_pixmap(dpi=95)
                    img = Image.open(io.BytesIO(p_img.tobytes("png")))
                finally:
                    doc_d.close()

                local_context = build_local_sliding_context(target, window=2)
                prompt = st.session_state.custom_prompt_text.replace("{global_context}", local_context)

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
                        save_workspace()
                        is_success = True
                    except Exception as e:
                        error_msg = str(e)
                        if "429" in error_msg or "Quota" in error_msg:
                            st.session_state.exhausted_models[active_m] = time.time() + 60
                            action_placeholder.markdown(f"<div class='status-yellow'><b>⚠️ `{active_m}` คิวเต็ม กำลังสลับโมเดลสำรอง...</b></div>", unsafe_allow_html=True)
                            time.sleep(1.5)
                            new_model = get_best_available_model(st.session_state.flash_models_list)
                            if new_model:
                                active_m = new_model
                                st.session_state.current_active_model = new_model
                                model = genai.GenerativeModel(new_model)
                                retry_count += 1
                            else:
                                st.session_state.processed_data[target] = {"ai_text": "⚠️ โควต้าเต็มทุกโมเดล รอ 1 นาทีแล้วกด Continue"}
                                is_success = True
                        else:
                            st.session_state.processed_data[target] = {"ai_text": f"⚠️ Error: {error_msg}"}
                            is_success = True

                time.sleep(0.05)
                st.rerun()
            else:
                st.session_state.is_running = False
                st.session_state.phase = 'idle'
                save_workspace()
                action_placeholder.markdown(
                    "<div class='status-blue' style='border-left-color:#16A34A; color:#166534; background:#F0FDF4;'>"
                    "<b>✅ ประมวลผลครบทุกหน้าแล้ว!</b> กดปุ่ม <b>ประกอบไฟล์ PDF</b> ด้านล่างได้เลย</div>",
                    unsafe_allow_html=True
                )
