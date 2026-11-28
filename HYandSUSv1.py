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

    # ระบบบริบท ±5 หน้า (Grounded Continuity)
    'phase': 'idle',  # idle, global_scan, detail_scan
    'global_data': {},
    'ai_peek_image_pages': True,  # ส่อง AI เฉพาะสไลด์ภาพล้วนใน Phase 1 เพื่อกันมั่วบริบท
    'context_window': 5,

    # การเลือกหน้าและโหมดฝึกคิด
    'customizer_page': 0,
    'expander_open': False,
    'hide_qa_answers': False,

    # ปรับแต่ง Prompt
    'use_custom_prompt': False,
    'custom_prompt_text': "",

    # ระบบดาวน์โหลด PDF
    'compiled_pdf_bytes': None,
    'compiled_pdf_size_mb': 0.0,
}

for k, v in keys_to_init.items():
    if k not in st.session_state:
        st.session_state[k] = v

st.set_page_config(page_title="Smart Study Buddy 🩺", layout="wide")

# --- 2. Custom CSS ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');

    html, body, [class*="st-"] {
        font-family: 'Sarabun', sans-serif !important;
    }

    .stApp { background-color: #F8FAFC; }
    .main-header { font-size: 2.0rem; font-weight: 800; color: #0F172A; margin-bottom: 0.6rem; letter-spacing: -0.4px; }
    .stButton>button { border-radius: 8px; transition: all 0.2s; font-weight: 600; font-family: 'Sarabun', sans-serif !important; }
    .stButton>button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }

    .reader-container {
        border: 1px solid #E2E8F0;
        border-radius: 14px;
        padding: 18px 20px;
        background: #FFFFFF;
        font-size: 16px;
        line-height: 1.68;
        color: #1E293B;
        box-shadow: 0 4px 14px -2px rgba(0, 0, 0, 0.04);
    }

    .hy-header {
        background: #FFF1F2;
        border-left: 5px solid #E11D48;
        color: #9F1239;
        font-weight: 700;
        padding: 6px 12px;
        border-radius: 0 8px 8px 0;
        margin-bottom: 10px;
        font-size: 1.02em;
    }
    .hy-body { padding: 2px 4px 10px 4px; margin-bottom: 12px; }
    .hy-body p { margin-bottom: 8px; }
    .hy-body ul { margin: 4px 0 8px 0; padding-left: 1.3rem; }
    .hy-body li { margin-bottom: 5px; }

    .qa-header {
        background: #EFF6FF;
        border-left: 5px solid #2563EB;
        color: #1E3A8A;
        font-weight: 700;
        padding: 6px 12px;
        border-radius: 0 8px 8px 0;
        margin: 8px 0 10px 0;
        font-size: 1.02em;
    }
    .qa-item {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 10px 14px;
        margin-bottom: 9px;
    }
    .qa-q { color: #1D4ED8; font-weight: 700; margin-bottom: 4px; line-height: 1.5; }
    .qa-a { color: #1E293B; line-height: 1.58; padding-left: 4px; }

    details.qa-toggle {
        margin-top: 4px;
        background: #F0FDF4;
        border: 1px solid #BBF7D0;
        border-radius: 6px;
        padding: 5px 10px;
        cursor: pointer;
    }
    details.qa-toggle summary { font-weight: 700; color: #15803D; font-size: 0.92em; outline: none; }

    .status-blue { background: #EBF8FF; border-left: 5px solid #3182CE; color: #2B6CB0; padding: 12px 14px; border-radius: 10px; margin-bottom: 14px;}
    .status-yellow { background: #FFFFF0; border-left: 5px solid #D69E2E; color: #B7791F; padding: 12px 14px; border-radius: 10px; margin-bottom: 14px;}
    .status-purple { background: #FAF5FF; border-left: 5px solid #805AD5; color: #553C9A; padding: 12px 14px; border-radius: 10px; margin-bottom: 14px;}
</style>
""", unsafe_allow_html=True)

# --- 3. ฟังก์ชันจัดการไฟล์ Auto-Save และยูทิลิตี้ ---

WORKSPACE_META_FILE = "autosave_v13_meta.pkl"
WORKSPACE_PDF_FILE = "autosave_v13_source.pdf"

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
        'use_custom_prompt': st.session_state.use_custom_prompt,
        'ai_peek_image_pages': st.session_state.ai_peek_image_pages,
        'context_window': st.session_state.context_window,
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
        return pix.tobytes("png")
    finally:
        doc.close()

def split_hy_qa(raw_text):
    """แยกข้อความออกเป็น 2 ส่วน: (high_yield_text, curious_qa_text)"""
    if not raw_text:
        return "", ""

    text = raw_text.strip()
    hy_text, qa_text = "", ""

    qa_pattern = re.compile(
        r'(?:^|\n)\s*(?:#{1,3}\s*|\*\*)?(?:\[CURIOUS-QA\]|CURIOUS-QA:|เด็กช่างสงสัย:?)(?:\*\*)?\s*',
        flags=re.IGNORECASE
    )
    hy_pattern = re.compile(
        r'(?:^|\n)\s*(?:#{1,3}\s*|\*\*)?(?:\[HIGH-YIELD\]|HIGH-YIELD:)(?:\*\*)?\s*',
        flags=re.IGNORECASE
    )

    qa_match = qa_pattern.search(text)
    if qa_match:
        before_qa = text[:qa_match.start()].strip()
        qa_text = text[qa_match.end():].strip()
        hy_text = hy_pattern.sub("", before_qa, count=1).strip()
    else:
        hy_text = hy_pattern.sub("", text, count=1).strip()

    return hy_text, qa_text

def _clean_oneline(txt, max_len=240):
    clean = re.sub(r'\*\*|__|#+', '', txt)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return (clean[:max_len] + "…") if len(clean) > max_len else clean

def build_grounded_context(target_idx, window=5):
    """
    สร้างบริบทที่ยึดตามความจริง 100% ย้อนหลัง `window` หน้า และล่วงหน้า `window` หน้า
    - หน้าก่อนหน้า: ดึงจาก High-Yield ที่ประมวลผลจริงก่อน (แม่นสุดแม้เป็นสไลด์ภาพ) ถ้าไม่มีจึงใช้ global_data
    - หน้าถัดไป: ดึงจาก global_data (ข้อความจริงจาก PDF หรือ AI peek) เพื่อรู้ทิศทางล่วงหน้า
    - ถ้าหน้าไหนไม่มีข้อมูลจริง จะระบุชัดว่า [ไม่มีข้อมูลข้อความ — ห้ามเดา]
    """
    sorted_pages = sorted(st.session_state.selected_pages)
    if target_idx in sorted_pages:
        pos = sorted_pages.index(target_idx)
        prev_pages = sorted_pages[max(0, pos - window):pos]
        next_pages = sorted_pages[pos + 1:min(len(sorted_pages), pos + 1 + window)]
    else:
        prev_pages = [p for p in sorted_pages if target_idx - window <= p < target_idx][-window:]
        next_pages = [p for p in sorted_pages if target_idx < p <= target_idx + window][:window]

    def describe_page(idx, prefer_processed=True):
        if prefer_processed and idx in st.session_state.processed_data:
            raw_p = st.session_state.processed_data[idx].get("user_text") or st.session_state.processed_data[idx].get("ai_text", "")
            if raw_p and "⚠️" not in raw_p:
                hy_p, _ = split_hy_qa(raw_p)
                if hy_p.strip():
                    return f"หน้า {idx+1} [สรุปจริง]: {_clean_oneline(hy_p, 250)}"
            elif raw_p == "":
                return f"หน้า {idx+1}: [หน้าว่าง/หน้าปก ไม่มีเนื้อหา]"

        g = st.session_state.global_data.get(idx, {})
        topic = g.get('topic', '').strip()
        summary = g.get('summary', '').strip()
        if summary and "ไม่มีข้อมูลข้อความ" not in summary:
            label = f"{topic} — {summary}" if topic and topic not in summary else (summary or topic)
            return f"หน้า {idx+1}: {_clean_oneline(label, 220)}"
        return f"หน้า {idx+1}: [ไม่มีข้อมูลข้อความในหน้านี้ — ห้ามเดาหรืออ้างอิง]"

    past_lines = [f"- {describe_page(idx, prefer_processed=True)}" for idx in prev_pages]
    future_lines = [f"- {describe_page(idx, prefer_processed=True)}" for idx in next_pages]

    past_block = "\n".join(past_lines) if past_lines else "- (ไม่มี — หน้านี้คือหน้าแรกของชุดสไลด์)"
    future_block = "\n".join(future_lines) if future_lines else "- (ไม่มี — หน้านี้คือหน้าสุดท้ายของชุดสไลด์)"

    return (
        f"### 1) บริบทจริง {len(prev_pages)} หน้าก่อนหน้า (อ้างอิงได้เฉพาะสิ่งที่มีเขียนจริงข้างล่างนี้เท่านั้น):\n"
        f"{past_block}\n\n"
        f"### 2) แผนที่เนื้อหาจริง {len(next_pages)} หน้าถัดไป (ใช้ดูทิศทางล่วงหน้าเพื่อไม่เขียนซ้ำซ้อน ห้ามแต่งเติมเกินนี้):\n"
        f"{future_block}"
    )

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

# --- 4. ฟังก์ชันจัดรูปแบบ HTML / PDF และคำนวณฟอนต์ ---

def style_bold_keywords(text, color="#BE123C"):
    return re.sub(
        r'\*\*(.*?)\*\*',
        f"<strong style='color: {color}; font-weight: 700;'>\\1</strong>",
        text
    )

def format_hy_html(hy_text, for_pdf=False):
    if not hy_text.strip():
        return ""
    colored = style_bold_keywords(hy_text.strip(), color="#BE123C")
    body_html = markdown.markdown(colored, extensions=['tables'])
    return f"<div class='hy-header'>⚡ High-Yield สาระสำคัญ &amp; จุดสังเกต</div><div class='hy-body'>{body_html}</div>"

def format_qa_html(qa_text, for_pdf=False, hide_answers=False):
    if not qa_text.strip():
        return ""

    lines = qa_text.strip().split("\n")
    pairs = []
    curr_q, curr_a = [], []
    mode = None

    q_re = re.compile(r'^\s*(?:[-*]\s*)?(?:\*\*)?Q\s*\d*\s*[:.]\s*(?:\*\*)?\s*(.*)', re.IGNORECASE)
    a_re = re.compile(r'^\s*(?:[-*]\s*)?(?:\*\*)?A\s*\d*\s*[:.]\s*(?:\*\*)?\s*(.*)', re.IGNORECASE)

    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        qm = q_re.match(s)
        am = a_re.match(s)
        if qm:
            if curr_q or curr_a:
                pairs.append((" ".join(curr_q).strip(), " ".join(curr_a).strip()))
            curr_q = [qm.group(1).strip()]
            curr_a = []
            mode = 'q'
        elif am:
            curr_a = [am.group(1).strip()]
            mode = 'a'
        else:
            if mode == 'q':
                curr_q.append(s)
            elif mode == 'a':
                curr_a.append(s)

    if curr_q or curr_a:
        pairs.append((" ".join(curr_q).strip(), " ".join(curr_a).strip()))

    header = "<div class='qa-header'>🙋‍♂️ เด็กช่างสงสัย (ถามลึกเรียงตามความสำคัญ)</div>"

    if not pairs:
        colored = style_bold_keywords(qa_text.strip(), color="#B91C1C")
        return f"{header}<div class='qa-body'>{markdown.markdown(colored, extensions=['tables'])}</div>"

    items_html = []
    for idx, (q_txt, a_txt) in enumerate(pairs, start=1):
        q_clean = style_bold_keywords(q_txt, color="#1E3A8A")
        a_clean = style_bold_keywords(a_txt, color="#B91C1C")

        if for_pdf:
            item = (
                f"<div class='qa-item'>"
                f"<div class='qa-q'>Q{idx}: {q_clean}</div>"
                f"<div class='qa-a'><b>A:</b> {a_clean}</div>"
                f"</div>"
            )
        else:
            if hide_answers:
                item = (
                    f"<div class='qa-item'>"
                    f"<div class='qa-q'>Q{idx}: {q_clean}</div>"
                    f"<details class='qa-toggle'><summary>💡 คิดคำตอบก่อน แล้วคลิกดูเฉลย A{idx}</summary>"
                    f"<div class='qa-a' style='margin-top:5px;'>{a_clean}</div></details>"
                    f"</div>"
                )
            else:
                item = (
                    f"<div class='qa-item'>"
                    f"<div class='qa-q'>Q{idx}: {q_clean}</div>"
                    f"<div class='qa-a'><b>A{idx}:</b> {a_clean}</div>"
                    f"</div>"
                )
        items_html.append(item)

    return header + "".join(items_html)

def calc_optimal_fontsize(html_text, rect_width, rect_height, mode="combined"):
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

    if mode == "hy":
        max_f, min_f, char_w, line_h, fill_ratio, blk_gap = 46, 16, 0.38, 1.34, 0.92, 0.24
    elif mode == "qa":
        max_f, min_f, char_w, line_h, fill_ratio, blk_gap = 32, 12, 0.40, 1.32, 0.91, 0.22
    else:
        max_f, min_f, char_w, line_h, fill_ratio, blk_gap = 34, 12, 0.40, 1.34, 0.90, 0.25

    for f_size in range(max_f, min_f - 1, -1):
        usable_w = max(40.0, rect_width - 18.0)
        chars_per_line = max(8.0, usable_w / (f_size * char_w))
        total_lines = sum(math.ceil(length / chars_per_line) for length in eff_lengths)
        est_height = (total_lines + num_blocks * blk_gap) * (f_size * line_h)
        if est_height <= rect_height * fill_ratio:
            return f_size

    return min_f

def render_layout_preview(hy_pos, qa_pos, want_hy, want_qa):
    layout_map = {"ด้านขวา": [], "ด้านล่าง": [], "ด้านซ้าย": [], "ด้านบน": []}
    if want_hy:
        layout_map[hy_pos].append("<span style='color:#BE123C;'><b>⚡ High-Yield</b></span>")
    if want_qa:
        layout_map[qa_pos].append("<span style='color:#1D4ED8;'><b>🙋‍♂️ ช่างสงสัย</b></span>")

    right_box = f"<div style='flex:0.36;background:#F8FAFC;padding:6px;font-size:9px;border-left:1px solid #CBD5E1;display:flex;flex-direction:column;justify-content:center;gap:6px;'>{'<br>'.join(layout_map['ด้านขวา'])}</div>" if layout_map['ด้านขวา'] else ""
    left_box = f"<div style='flex:0.36;background:#F8FAFC;padding:6px;font-size:9px;border-right:1px solid #CBD5E1;display:flex;flex-direction:column;justify-content:center;gap:6px;'>{'<br>'.join(layout_map['ด้านซ้าย'])}</div>" if layout_map['ด้านซ้าย'] else ""
    bottom_box = f"<div style='height:38px;background:#F8FAFC;padding:6px;font-size:9px;border-top:1px solid #CBD5E1;display:flex;align-items:center;justify-content:center;gap:10px;'>{' | '.join(layout_map['ด้านล่าง'])}</div>" if layout_map['ด้านล่าง'] else ""
    top_box = f"<div style='height:38px;background:#F8FAFC;padding:6px;font-size:9px;border-bottom:1px solid #CBD5E1;display:flex;align-items:center;justify-content:center;gap:10px;'>{' | '.join(layout_map['ด้านบน'])}</div>" if layout_map['ด้านบน'] else ""

    html_str = (
        f"<div style='width:100%;height:165px;border-radius:10px;background:white;border:2px solid #E2E8F0;"
        f"display:flex;flex-direction:column;overflow:hidden;'>"
        f"{top_box}"
        f"<div style='flex:1;display:flex;flex-direction:row;'>"
        f"{left_box}"
        f"<div style='flex:1;background:#F1F5F9;border:2px dashed #CBD5E1;margin:6px;display:flex;align-items:center;justify-content:center;font-size:12px;color:#64748B;font-weight:700;border-radius:6px;'>Slide</div>"
        f"{right_box}"
        f"</div>"
        f"{bottom_box}"
        f"</div>"
    )
    st.markdown(html_str, unsafe_allow_html=True)

# --- 5. Sidebar ---
with st.sidebar:
    st.markdown("<h2 style='color: #0F172A; margin-bottom: 0.2rem;'>🩺 Study Buddy Settings</h2>", unsafe_allow_html=True)
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
                st.info("🔒 ล็อกการตั้งค่าขณะรัน")
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
            st.error("API Key ไม่ถูกต้อง หรือดึงรายชื่อโมเดลไม่ได้")

    st.caption(f"💳 Token ที่ใช้ไป (ประมาณการ): **{st.session_state.estimated_tokens_used:,}**")
    st.divider()

    med_year = st.selectbox("ระดับชั้น นสพ.", [2, 3, 4, 5, 6], index=2, disabled=is_locked)
    want_hy = st.checkbox("⚡ High-Yield (สาระสำคัญ + จุดสังเกต)", value=True, disabled=is_locked)
    want_qa = st.checkbox("🙋‍♂️ ระบบเด็กช่างสงสัย (Q:/A: เชิงเหตุผล)", value=True, disabled=is_locked)

    qa_min, qa_max = 2, 4
    if want_qa:
        qa_min, qa_max = st.slider(
            "จำนวนคำถามเด็กช่างสงสัย (ขั้นต่ำ - สูงสุด):",
            min_value=1, max_value=7, value=(2, 4), disabled=is_locked
        )

    st.divider()

    # ตั้งค่าระบบร้อยเรียงบริบท ±5 หน้า
    st.markdown("### 🔗 ระบบร้อยเรียงเนื้อหาข้ามหน้า")
    st.session_state.context_window = st.slider(
        "ช่วงมองบริบทก่อนหน้า–ถัดไป (หน้า):",
        min_value=2, max_value=8, value=st.session_state.context_window, disabled=is_locked,
        help="ค่าเริ่มต้น 5 หน้า = รู้จริงทั้ง 5 หน้าก่อนหน้าและ 5 หน้าถัดไป"
    )
    st.session_state.ai_peek_image_pages = st.checkbox(
        "👁️ สแกน AI เฉพาะสไลด์ภาพล้วนใน Phase 1",
        value=st.session_state.ai_peek_image_pages,
        disabled=is_locked,
        help="หน้าที่มีตัวอักษรจะสแกนทันที (0 Token) แต่ถ้าเจอหน้าภาพล้วนจะให้ AI ส่องสั้นๆ เพื่อไม่ให้มั่วบริบท 5 หน้าถัดไป"
    )

    st.divider()

    # ตั้งค่าตำแหน่ง PDF
    st.markdown("### 📐 จัดตำแหน่งบนกระดาษ (PDF Layout)")
    pos_options = ["ด้านบน", "ด้านล่าง", "ด้านซ้าย", "ด้านขวา"]
    hy_pos = st.selectbox("วาง [⚡ High-Yield] ไว้ที่:", pos_options, index=1, disabled=is_locked or not want_hy)
    qa_pos = st.selectbox("วาง [🙋‍♂️ เด็กช่างสงสัย] ไว้ที่:", pos_options, index=3, disabled=is_locked or not want_qa)

    margin_side_pct = st.slider("ขยายพื้นที่ ซ้าย/ขวา (%)", 20, 100, 50, disabled=is_locked)
    margin_vert_pct = st.slider("ขยายพื้นที่ บน/ล่าง (%)", 20, 100, 42, disabled=is_locked)
    render_layout_preview(hy_pos, qa_pos, want_hy, want_qa)

    st.divider()
    max_tokens = st.number_input("Max Output Tokens", min_value=500, max_value=8192, value=2500, step=250, disabled=is_locked)

    base_prompt_template = f"""คุณคือติวเตอร์แพทย์ที่สรุปคมที่สุด และเพื่อนร่วมเรียนหัวกะทิที่นั่งเรียนข้าง นสพ. ปี {med_year}
เป้าหมาย: ตัดน้ำทิ้งทั้งหมด เหลือเฉพาะสิ่งที่อ่านแล้ว **"ลื่นไหล เข้าใจแก่นทันที ไม่สะดุด และได้มุมมองเชิงเหตุผลที่คนอ่านมักมองข้าม"**

**ข้อมูลบริบทจริงรอบข้าง (ยึดตามความจริง 100% เท่านั้น):**
{{global_context}}

**กฎเหล็กเรื่องความถูกต้องและการร้อยเรียง (ห้ามละเมิดเด็ดขาด):**
1. **ห้ามมั่วบริบทเด็ดขาด (Zero Hallucination):** อ้างอิงเนื้อหาหน้าก่อนหน้าหรือหน้าถัดไปได้ **เฉพาะสิ่งที่ปรากฏเป็นลายลักษณ์อักษรในข้อมูลบริบทข้างต้นเท่านั้น** หากไม่พบคำ/หัวข้อนั้นในบริบท หรือระบุว่า `[ไม่มีข้อมูลข้อความ]` ห้ามแต่งเติมหรือเดาเองโดยเด็ดขาด (เช่น ห้ามพูดว่า "จากอนาโตมี่หน้าที่แล้ว..." ถ้า 5 หน้าก่อนหน้าไม่ได้พูดถึงอนาโตมี่จริง)
2. **ห้ามฝืนเกริ่นให้เสียเวลาอ่าน (No Forced Transitions):**
   - **ห้ามใช้ประโยคซ้ำซาก/หุ่นยนต์** เช่น "จากเรื่อง...ที่เรียนไปในหน้าที่แล้ว หน้านี้จะอธิบายถึง..." หรือ "ต่อเนื่องจากสไลด์ก่อนหน้า..."
   - ถ้าหน้านี้ **ขึ้นประเด็นใหม่ หรือจบความในตัวเองได้** ให้ **เข้าแก่นเนื้อหาทันที** ไม่ต้องย้อนความให้เสียเวลา
   - ถ้าหน้านี้ **ต่อยอดเชิงเหตุ-ผลตรงๆ** จากหน้าก่อนหน้า ให้ร้อยเข้าประโยคอย่างเป็นธรรมชาติด้วยคำเชื่อมเชิงเนื้อหา (เช่น *"เมื่อเกิดภาวะนี้แล้ว ขั้นตอนถัดไปคือ..."* หรือ *"จากกลไกดังกล่าว จึงทำให้ตรวจพบ..."*) โดยไม่ต้องเอ่ยคำว่า "หน้าที่แล้ว/สไลด์ก่อนหน้า" พร่ำเพรื่อ
   - ใช้ข้อมูล **5 หน้าถัดไป** เพื่อรู้ขอบเขต (รู้ว่าเรื่องไหนเดี๋ยวหน้าถัดไปจะลงลึกอยู่แล้ว หน้านี้จะได้ไม่เขียนซ้ำซ้อนล่วงหน้า)
3. **เน้นตัวหนา (`**คำสำคัญ**`)** ที่คำสำคัญ กลไกหลัก และจุดตัดสำคัญเสมอ เพื่อให้กวาดสายตาแล้วจับใจความได้ทันทีและจำได้นาน
4. ศัพท์แพทย์หรือตัวย่อสำคัญ ให้ใส่วงเล็บคำเต็มหรือภาษาอังกฤษเมื่อปรากฏครั้งแรก
5. **ถ้าสไลด์เป็นหน้าปก หน้าว่าง หรือไม่มีเนื้อหาการแพทย์เลย** ให้ตอบเพียงคำเดียวว่า `NON_CONTENT`
6. **ถ้าสไลด์เป็นโจทย์ข้อสอบ** ให้ใช้ `[HIGH-YIELD]` สรุป Keyword โจทย์ ➡️ คำตอบที่ถูกพร้อมเหตุผล และใช้ `[CURIOUS-QA]` เจาะเหตุผลว่าทำไมตัวลวงอื่นผิดหรือถ้าเปลี่ยนเงื่อนไขโจทย์คำตอบจะเปลี่ยนอย่างไร

{{section_instructions}}"""

    use_custom_prompt = st.checkbox("🛠️ แก้ไข Master Prompt เอง", value=st.session_state.use_custom_prompt, disabled=is_locked)
    if use_custom_prompt:
        st.session_state.custom_prompt_text = st.text_area(
            "ปรับแต่ง Prompt (ห้ามลบ {global_context} และ {section_instructions})",
            value=st.session_state.custom_prompt_text or base_prompt_template,
            height=260,
            disabled=is_locked
        )
    else:
        st.session_state.custom_prompt_text = base_prompt_template
    st.session_state.use_custom_prompt = use_custom_prompt

    current_settings = {
        "year": med_year, "want_hy": want_hy, "want_qa": want_qa,
        "qa_range": (qa_min, qa_max), "hy_pos": hy_pos, "qa_pos": qa_pos,
        "m_side": margin_side_pct, "m_vert": margin_vert_pct, "max_tok": max_tokens,
        "ctx_win": st.session_state.context_window
    }
    if not is_locked and st.session_state.last_settings and current_settings != st.session_state.last_settings:
        st.session_state.settings_changed_alert = True
    st.session_state.last_settings = current_settings

# --- 6. หน้าหลัก: อัปโหลดและจัดการไฟล์ ---
st.markdown("<div class='main-header'>🩺 Smart Study Buddy: High-Yield + เด็กช่างสงสัย</div>", unsafe_allow_html=True)

if not st.session_state.pdf_bytes:
    if os.path.exists(WORKSPACE_META_FILE) and os.path.exists(WORKSPACE_PDF_FILE):
        st.info("💾 **พบงานที่ทำค้างไว้!** สามารถกดกู้คืนเพื่อทำต่อได้ทันที")
        if st.button("🔄 กู้คืนงานเดิม", type="primary"):
            if load_workspace():
                st.success("กู้คืนสำเร็จ!")
                time.sleep(0.3)
                st.rerun()
            else:
                st.error("ไม่สามารถกู้คืนไฟล์ได้")

    uploaded_file = st.file_uploader("อัปโหลดไฟล์สไลด์ (PDF)", type="pdf")
    if uploaded_file:
        with st.status(f"กำลังนำเข้า {uploaded_file.name}...", expanded=True) as status:
            st.session_state.pdf_bytes = uploaded_file.getvalue()
            st.session_state.pdf_name = uploaded_file.name
            doc_tmp = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
            total_p = len(doc_tmp)
            doc_tmp.close()
            st.session_state.selected_pages = list(range(total_p))
            save_workspace(save_pdf_binary=True)
            status.update(label=f"✅ นำเข้าสำเร็จ: {uploaded_file.name} ({total_p} หน้า)", state="complete")
        st.rerun()
else:
    doc_meta = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
    total_pages = len(doc_meta)
    doc_meta.close()

    col_i1, col_i2 = st.columns([3.2, 1])
    with col_i1:
        st.info(f"📄 **{st.session_state.pdf_name}** | ทั้งหมด **{total_pages} หน้า** | ประมวลผลแล้ว **{len(st.session_state.processed_data)} หน้า**")
    with col_i2:
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

# --- 7. เลือกหน้าที่ต้องการประมวลผล (Paginated) ---
if st.session_state.pdf_bytes and not is_locked:
    if st.session_state.expander_open:
        with st.expander(f"🖼️ เลือกหน้าที่ต้องการประมวลผล ({len(st.session_state.selected_pages)}/{total_pages} หน้า)", expanded=True):
            c1, c2, c3, c4 = st.columns([1, 1, 2, 1.5])
            if c1.button("✅ เลือกทั้งหมด", use_container_width=True):
                st.session_state.selected_pages = list(range(total_pages))
                st.rerun()
            if c2.button("❌ ล้างที่เลือก", use_container_width=True):
                st.session_state.selected_pages = []
                st.rerun()
            with c3:
                range_input = st.text_input("ช่วงหน้า:", label_visibility="collapsed", placeholder="เช่น 1-30, 35, 40-60")
            if c4.button("🎯 เลือกตามช่วง", use_container_width=True) and range_input:
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
            cust_page = st.number_input(f"ชุดสไลด์ที่ (1 - {max_cust_pages}):", 1, max_cust_pages, st.session_state.customizer_page + 1) - 1
            st.session_state.customizer_page = cust_page

            start_idx = cust_page * ITEMS_PER_PAGE
            end_idx = min(total_pages, start_idx + ITEMS_PER_PAGE)

            doc_thumb = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
            for row_idx in range(start_idx, end_idx, 5):
                cols = st.columns(5)
                for col_idx in range(5):
                    p_num = row_idx + col_idx
                    if p_num < end_idx:
                        with cols[col_idx]:
                            pix = doc_thumb[p_num].get_pixmap(dpi=36)
                            st.image(pix.tobytes("png"), use_container_width=True)
                            chk = st.checkbox(f"หน้า {p_num+1}", value=(p_num in st.session_state.selected_pages), key=f"chk_{p_num}")
                            if chk and p_num not in st.session_state.selected_pages:
                                st.session_state.selected_pages.append(p_num)
                            elif not chk and p_num in st.session_state.selected_pages:
                                st.session_state.selected_pages.remove(p_num)
            doc_thumb.close()

            if st.button("💾 ยืนยันและพับเก็บ", type="primary", use_container_width=True):
                st.session_state.expander_open = False
                save_workspace()
                st.rerun()
    else:
        if st.button(f"⚙️ เลือกหน้าสไลด์ (เลือกไว้ {len(st.session_state.selected_pages)}/{total_pages} หน้า)"):
            st.session_state.expander_open = True
            st.rerun()

# --- 8. แผงควบคุมการรัน & E-Book Reader ---
if st.session_state.pdf_bytes:
    if st.session_state.settings_changed_alert and not st.session_state.is_running:
        st.warning("🔔 มีการเปลี่ยนการตั้งค่า: หน้าถัดไปที่รันจะใช้รูปแบบใหม่ (ตำแหน่ง PDF ปรับเปลี่ยนตอนกดประกอบไฟล์ได้ทันที)")
        if st.button("รับทราบ"):
            st.session_state.settings_changed_alert = False
            st.rerun()

    if st.session_state.show_start_popup:
        pages_to_do = len([i for i in st.session_state.selected_pages if i not in st.session_state.processed_data])
        st.info(
            f"📊 เตรียมประมวลผลเพิ่ม **{pages_to_do} หน้า** | "
            f"บริบทเชื่อมโยง: **±{st.session_state.context_window} หน้าจริง** | "
            f"คำถามช่างสงสัย: **{qa_min}–{qa_max} ข้อ/หน้า**"
        )
        c_s1, c_s2 = st.columns(2)
        if c_s1.button("✅ ยืนยันเริ่มรัน", type="primary", use_container_width=True):
            if not api_key:
                st.error("กรุณาใส่ Gemini API Key ในแถบด้านซ้ายก่อนครับ")
            elif not (want_hy or want_qa):
                st.error("กรุณาเลือกอย่างน้อย 1 ส่วน (High-Yield หรือ เด็กช่างสงสัย)")
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

    c_r1, c_r2, c_r3 = st.columns([1, 1, 1.5])
    if c_r1.button("🚀 Start / Continue", type="primary", disabled=is_locked, use_container_width=True):
        st.session_state.show_start_popup = True
        st.rerun()
    if c_r2.button("🛑 Stop / Pause", disabled=not st.session_state.is_running, use_container_width=True):
        st.session_state.is_running = False
        st.session_state.stop_clicked = True
        save_workspace()
        st.rerun()
    with c_r3:
        st.session_state.hide_qa_answers = st.toggle(
            "🙈 โหมดฝึกคิด (ซ่อนคำตอบ A: ของเด็กช่างสงสัย)",
            value=st.session_state.hide_qa_answers
        )

    # E-BOOK READER
    st.write("---")
    st.subheader(f"📖 หน้า {st.session_state.page_idx + 1} / {total_pages}")

    cn1, cn2, cn3 = st.columns([1, 2.5, 1])
    with cn1:
        if st.button("⬅️ ก่อนหน้า", use_container_width=True) and st.session_state.page_idx > 0:
            st.session_state.page_idx -= 1
            st.rerun()
    with cn2:
        new_p = st.slider("ไปที่หน้า:", 1, total_pages, st.session_state.page_idx + 1, label_visibility="collapsed")
        if new_p - 1 != st.session_state.page_idx:
            st.session_state.page_idx = new_p - 1
            st.rerun()
    with cn3:
        if st.button("ถัดไป ➡️", use_container_width=True) and st.session_state.page_idx < total_pages - 1:
            st.session_state.page_idx += 1
            st.rerun()

    curr = st.session_state.page_idx
    col_v1, col_v2 = st.columns([1.1, 1])

    with col_v1:
        st.image(render_page_png(st.session_state.pdf_bytes, curr, dpi=120), use_container_width=True, caption=f"สไลด์หน้า {curr + 1}")
        if st.session_state.global_data:
            with st.expander(f"🔗 ตรวจสอบบริบทจริง ±{st.session_state.context_window} หน้าที่ระบบส่งให้ AI หน้านี้"):
                st.markdown(build_grounded_context(curr, window=st.session_state.context_window))

    with col_v2:
        if curr in st.session_state.processed_data:
            data = st.session_state.processed_data[curr]
            edit_key = f"editing_{curr}"
            if edit_key not in st.session_state:
                st.session_state[edit_key] = False
            display_text = data.get("user_text") if data.get("user_text") else data.get("ai_text", "")

            if st.session_state[edit_key]:
                edited = st.text_area("แก้ไขเนื้อหา (คงแท็ก [HIGH-YIELD] และ [CURIOUS-QA] ไว้):", value=display_text, height=420)
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
                    st.info("ℹ️ หน้านี้ไม่มีเนื้อหาสำคัญ (NON_CONTENT)")
                elif "⚠️" in display_text:
                    st.warning(display_text)
                else:
                    hy_txt, qa_txt = split_hy_qa(display_text)
                    html_parts = []
                    if hy_txt:
                        html_parts.append(format_hy_html(hy_txt, for_pdf=False))
                    if qa_txt:
                        html_parts.append(format_qa_html(qa_txt, for_pdf=False, hide_answers=st.session_state.hide_qa_answers))
                    st.markdown(f"<div class='reader-container'>{''.join(html_parts)}</div>", unsafe_allow_html=True)

                c_ed1, c_ed2 = st.columns(2)
                if c_ed1.button("✏️ แก้ไขโน้ตหน้านี้", use_container_width=True):
                    st.session_state[edit_key] = True
                    st.session_state.is_running = False
                    st.rerun()
                if c_ed2.button("🔁 สั่ง AI สร้างหน้านี้ใหม่", disabled=is_locked, use_container_width=True):
                    del st.session_state.processed_data[curr]
                    save_workspace()
                    st.rerun()
        else:
            st.info(f"⏳ หน้า {curr + 1} ยังไม่ได้ประมวลผล")

    # --- 9. ประกอบไฟล์ PDF และบีบอัด ---
    st.write("---")
    if len(st.session_state.processed_data) > 0:
        st.subheader("📦 ประกอบและดาวน์โหลดไฟล์ PDF")

        comp_level = st.selectbox(
            "🗜️ ระดับการบีบอัดไฟล์ PDF:",
            [
                "1. บีบอัดขั้นสุด (ไฟล์เล็กที่สุด ประหยัดพื้นที่เครื่อง - แนะนำ)",
                "2. บีบอัดสมดุล (คมชัดสูง ขนาดกลาง)",
                "3. บีบอัดน้อย (รักษาคุณภาพต้นฉบับสูงสุด)"
            ],
            index=0
        )

        if st.button("📦 ประกอบไฟล์ PDF ตามตำแหน่งกระดาษที่ตั้งไว้", type="primary", use_container_width=True):
            pdf_prog = st.progress(0.0, text="กำลังเตรียมประกอบไฟล์ PDF...")
            doc_in = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
            doc_out = fitz.open()
            arch = fitz.Archive(".")
            has_custom_font = os.path.exists("THSarabunNew.ttf")

            try:
                used_positions = set()
                if want_hy:
                    used_positions.add(hy_pos)
                if want_qa:
                    used_positions.add(qa_pos)

                font_face_css = (
                    "@font-face { font-family: 'T'; src: url('THSarabunNew.ttf'); }"
                    "@font-face { font-family: 'T'; font-weight: bold; src: url('THSarabunNew Bold.ttf'); }"
                ) if has_custom_font else ""
                font_family_val = "'T', sans-serif" if has_custom_font else "sans-serif"

                for i in range(total_pages):
                    if i % 4 == 0 or i == total_pages - 1:
                        pdf_prog.progress(min(0.88, 0.88 * ((i + 1) / total_pages)), text=f"กำลังจัดวางหน้าที่ {i + 1} / {total_pages}...")

                    p_in = doc_in[i]
                    w, h = p_in.rect.width, p_in.rect.height

                    pad_left = (w * (margin_side_pct / 100.0)) if ("ด้านซ้าย" in used_positions) else 0
                    pad_right = (w * (margin_side_pct / 100.0)) if ("ด้านขวา" in used_positions) else 0
                    pad_top = (h * (margin_vert_pct / 100.0)) if ("ด้านบน" in used_positions) else 0
                    pad_bottom = (h * (margin_vert_pct / 100.0)) if ("ด้านล่าง" in used_positions) else 0

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
                        "ด้านบน": fitz.Rect(pad_left + 10, 10, pad_left + w - 10, pad_top - 10) if pad_top > 25 else None,
                    }

                    if i in st.session_state.processed_data:
                        raw_txt = st.session_state.processed_data[i].get("user_text") or st.session_state.processed_data[i].get("ai_text", "")
                        if raw_txt and "⚠️" not in raw_txt:
                            hy_txt, qa_txt = split_hy_qa(raw_txt)
                            box_items = {"ด้านบน": [], "ด้านล่าง": [], "ด้านซ้าย": [], "ด้านขวา": []}

                            if want_hy and hy_txt:
                                box_items[hy_pos].append(("hy", format_hy_html(hy_txt, for_pdf=True)))
                            if want_qa and qa_txt:
                                box_items[qa_pos].append(("qa", format_qa_html(qa_txt, for_pdf=True)))

                            for pos, items in box_items.items():
                                box = rects.get(pos)
                                if not items or box is None or box.is_empty or box.is_infinite:
                                    continue

                                combined_html = "".join([html_part for _, html_part in items])
                                types_in_box = {t for t, _ in items}
                                size_mode = "hy" if types_in_box == {"hy"} else ("qa" if types_in_box == {"qa"} else "combined")

                                f_size = calc_optimal_fontsize(combined_html, box.width, box.height, mode=size_mode)
                                line_h = "1.32" if size_mode == "qa" else "1.35"

                                css = f"""
                                {font_face_css}
                                body {{ font-family: {font_family_val}; font-size: {f_size}px; line-height: {line_h}; color: #0F172A; margin: 0; padding: 0; }}
                                b, strong {{ font-weight: bold; }}
                                .hy-header {{ background-color: #FFF1F2; border-left: 4px solid #E11D48; color: #9F1239; font-weight: bold; padding: 2px 7px; margin: 0 0 4px 0; }}
                                .hy-body p {{ margin: 2px 0 4px 0; }}
                                .hy-body ul {{ margin: 2px 0 4px 0; padding-left: 16px; }}
                                .hy-body li {{ margin-bottom: 3px; }}
                                .qa-header {{ background-color: #EFF6FF; border-left: 4px solid #2563EB; color: #1E3A8A; font-weight: bold; padding: 2px 7px; margin: 4px 0 4px 0; }}
                                .qa-item {{ background-color: #FFFFFF; border: 1px solid #CBD5E1; padding: 3px 6px; margin-bottom: 4px; }}
                                .qa-q {{ color: #1D4ED8; font-weight: bold; margin-bottom: 1px; }}
                                .qa-a {{ color: #1E293B; margin: 0; }}
                                table {{ border-collapse: collapse; width: 100%; margin: 4px 0; }}
                                th, td {{ border: 1px solid #CBD5E1; padding: 3px; text-align: left; }}
                                """
                                try:
                                    p_out.insert_htmlbox(box, f"<style>{css}</style><body>{combined_html}</body>", archive=arch)
                                except Exception:
                                    try:
                                        plain = re.sub(r'<[^>]+>', '', combined_html)
                                        p_out.insert_htmlbox(box, f"<body>{plain}</body>")
                                    except Exception:
                                        pass

                pdf_prog.progress(0.95, text="กำลังบีบอัดไฟล์ PDF...")
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
            st.success(f"🎉 ประกอบไฟล์ PDF สำเร็จ! ขนาดไฟล์: **{st.session_state.compiled_pdf_size_mb:.2f} MB**")
            st.download_button(
                label=f"💾 ดาวน์โหลด PDF ({st.session_state.compiled_pdf_size_mb:.2f} MB)",
                data=st.session_state.compiled_pdf_bytes,
                file_name=f"StudyBuddy_{st.session_state.pdf_name}",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )

    # --- 10. ระบบประมวลผลหลังบ้าน (Hybrid Grounded 2-Phase Processor) ---
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
        # PHASE 1: HYBRID GROUNDED INDEX (Text Instant + AI Peek เฉพาะหน้าภาพล้วน)
        # ==========================================
        if st.session_state.phase == 'global_scan':
            doc_idx = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
            need_rerun_for_peek = False
            try:
                for idx in st.session_state.selected_pages:
                    if idx in st.session_state.global_data:
                        continue

                    raw_t = doc_idx[idx].get_text("text").strip()
                    lines = [ln.strip() for ln in raw_t.split("\n") if ln.strip()]
                    full_clean_text = " ".join(lines)

                    # ถ้ามีข้อความจริงเพียงพอ -> ดึงทันที 0 Token
                    if len(full_clean_text) >= 25:
                        topic = lines[0][:55]
                        summary = full_clean_text[:240]
                        st.session_state.global_data[idx] = {'topic': topic, 'summary': summary}
                    else:
                        # หน้าภาพล้วน/สแกนที่ไม่มีตัวอักษร
                        if st.session_state.ai_peek_image_pages:
                            action_placeholder.markdown(
                                f"<div class='status-purple'><b>👁️ [Phase 1/2] พบหน้าภาพล้วน (หน้า {idx+1}/{total_pages}) — กำลังสแกนหัวข้อสั้นๆ เพื่อทำแผนที่บริบท 5 หน้า...</b></div>",
                                unsafe_allow_html=True
                            )
                            img_peek = Image.open(io.BytesIO(doc_idx[idx].get_pixmap(dpi=55).tobytes("png")))
                            try:
                                resp_p = model.generate_content(
                                    [
                                        "ดูสไลด์ภาพนี้แล้วสรุปสั้นมากเพื่อทำสารบัญ (ห้ามแต่งเพิ่มจากภาพ):\n"
                                        "TOPIC: (ชื่อหัวข้อ 2-5 คำ ถ้าเป็นหน้าว่าง/หน้าปกตอบ 'หน้าปก/ว่าง')\n"
                                        "SUMMARY: (ใจความหลัก 1 ประโยคสั้นๆ ไม่เกิน 25 คำ)",
                                        img_peek
                                    ],
                                    safety_settings=safety,
                                    generation_config=GenerationConfig(max_output_tokens=90)
                                )
                                txt_p = resp_p.text.strip()
                                st.session_state.estimated_tokens_used += len(txt_p)
                                if "TOPIC:" in txt_p and "SUMMARY:" in txt_p:
                                    topic = txt_p.split("TOPIC:")[1].split("SUMMARY:")[0].strip()
                                    summary = txt_p.split("SUMMARY:")[1].strip()
                                else:
                                    topic = f"หน้า {idx+1}"
                                    summary = _clean_oneline(txt_p, 180)
                                st.session_state.global_data[idx] = {'topic': topic, 'summary': summary}
                            except Exception as e:
                                if "429" in str(e) or "Quota" in str(e):
                                    st.session_state.exhausted_models[active_m] = time.time() + 60
                                    new_m = get_best_available_model(st.session_state.flash_models_list)
                                    if new_m and new_m != active_m:
                                        st.session_state.current_active_model = new_m
                                        time.sleep(1.0)
                                        need_rerun_for_peek = True
                                        break
                                st.session_state.global_data[idx] = {
                                    'topic': f"หน้า {idx+1}",
                                    'summary': "[ไม่มีข้อมูลข้อความ — หน้าภาพล้วน]"
                                }
                            save_workspace()
                            need_rerun_for_peek = True
                            break
                        else:
                            st.session_state.global_data[idx] = {
                                'topic': f"หน้า {idx+1}",
                                'summary': "[ไม่มีข้อมูลข้อความ — หน้าภาพล้วน]"
                            }
            finally:
                doc_idx.close()

            if need_rerun_for_peek:
                st.rerun()
            else:
                st.session_state.phase = 'detail_scan'
                save_workspace()
                st.rerun()

        # ==========================================
        # PHASE 2: HIGH-YIELD + CURIOUS STUDY BUDDY (Grounded ±5 Context)
        # ==========================================
        elif st.session_state.phase == 'detail_scan':
            target = next(
                (i for i in st.session_state.selected_pages if i in st.session_state.processed_data and "⚠️" in st.session_state.processed_data[i].get("ai_text", "")),
                None
            )
            is_recheck = target is not None
            if target is None:
                target = next((i for i in st.session_state.selected_pages if i not in st.session_state.processed_data), None)

            if target is not None:
                done_cnt = len([k for k in st.session_state.selected_pages if k in st.session_state.processed_data and "⚠️" not in st.session_state.processed_data[k].get("ai_text", "")])
                mode_cls = "yellow" if is_recheck else "blue"
                msg = f"🔄 ซ่อมหน้าที่ Error (หน้า {target+1})" if is_recheck else f"⚡ กำลังสรุปหน้า {target+1} (เชื่อมบริบทจริง ±{st.session_state.context_window} หน้า | เสร็จ {done_cnt}/{len(st.session_state.selected_pages)})"
                action_placeholder.markdown(f"<div class='status-{mode_cls}'><b>{msg}</b><br>🤖 โมเดล: <code>{active_m}</code></div>", unsafe_allow_html=True)

                doc_d = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
                img = Image.open(io.BytesIO(doc_d[target].get_pixmap(dpi=85).tobytes("png")))
                doc_d.close()

                sections = []
                if want_hy:
                    sections.append(
                        "[HIGH-YIELD]\n"
                        "เขียนสรุปสไลด์หน้านี้ให้จบในที่เดียวแบบ **อ่านลื่น เป็นธรรมชาติ กระชับ และไม่ซ้ำแพทเทิร์น**:\n"
                        "- **วิธีเปิดเรื่องให้ลื่น (สำคัญมาก):**\n"
                        "  • ถ้าหน้านี้ **เป็นหัวข้อใหม่ หรือเข้าใจได้ในตัวมันเอง** ให้ **เข้าประเด็นสำคัญทันที** ห้ามเกริ่นย้อนถึงหน้าที่แล้วให้เสียเวลา\n"
                        "  • ถ้าหน้านี้ **เป็นเหตุ-ผลต่อเนื่องตรงๆ** จากเรื่องที่มีอยู่จริงใน 5 หน้าก่อนหน้า ให้ร้อยต่ออย่างเนียนๆ ด้วยเหตุผลของเนื้อหาโดยตรง **ไม่ต้องใช้คำฟุ่มเฟือยว่า 'จากหน้าที่แล้วที่เราเรียนเรื่อง...'**\n"
                        "  • ถ้าหน้านี้เป็น **สไลด์ปูทาง** ไปสู่เนื้อหาสำคัญใน 5 หน้าถัดไป ให้เน้นเฉพาะจุดที่ต้องใช้ต่อยอด และไม่ต้องเขียนซ้ำรายละเอียดที่หน้าถัดไปจะพูดอยู่แล้ว\n"
                        "- **องค์ประกอบต้องครบ:** แก่นสำคัญของหน้านี้ + **เหตุผล/กลไกเชื่อมโยง** (ใช้ `➡️` ได้เมื่อไล่ลำดับเหตุผล) + **จุดสังเกตหรือข้อควรระวัง** ที่มักพลาดในข้อสอบหรือหน้างานจริง\n"
                        "- ความยาวกระชับพอดีกับเนื้อหาจริง (ประมาณ 1 ย่อหน้า หรือ 2–4 บูลเล็ตสั้นๆ อ่านจบใน 15–20 วินาที) เน้น **ตัวหนา** ที่คำสำคัญเสมอ"
                    )

                if want_qa:
                    sections.append(
                        f"[CURIOUS-QA]\n"
                        f"สวมบทบาท **เพื่อนร่วมเรียนหัวกะทิช่างสงสัย** ที่คอยถามอาจารย์ในจุดสำคัญที่คนอ่านมักมองข้ามหรือลืมเอะใจ\n"
                        f"- สร้างจำนวน **{qa_min} ถึง {qa_max} ข้อ** (ปรับจำนวนตามความแน่นของเนื้อหาจริงในสไลด์ ห้ามฝืนสร้างคำถามขยะ)\n"
                        f"- **เรียงลำดับจากคำถามที่สำคัญที่สุด/เปิดมุมมองที่สุด/ออกสอบบ่อยที่สุดไว้ข้อ 1 ไล่ลงมา**\n"
                        f"- เขียนกระชับ คุ้มพื้นที่กระดาษ ใช้รูปแบบนี้เท่านั้น:\n"
                        f"Q1: (คำถามเชิงเหตุผลที่คมและชวนคิด)\n"
                        f"A1: (คำตอบกระชับ 1–3 บรรทัด อธิบายเหตุผลเชื่อมโยงชัดเจน เน้น **คำสำคัญตัวหนา**)\n\n"
                        f"**เกณฑ์คัดกรองคำถามที่ดี (เลือกถามเฉพาะ 5 ประเภทนี้ เรียงตามน้ำหนักความสำคัญ):**\n"
                        f"1. **ถามหาเหตุผลเบื้องหลัง (Why-Mechanism):** ไม่ถามว่า 'คืออะไร' แต่ถามว่า 'ทำไมกลไกนี้ถึงเกิดผลลัพธ์แบบนี้?' หรือ 'ทำไมต้องใช้เกณฑ์/ตัวเลขนี้?' เพื่อเชื่อมเหตุไปหาผลโดยไม่ต้องท่องจำ\n"
                        f"2. **ถามจุดตัดและกับดัก (Why-This-Not-That):** 'ทำไมเคสนี้ต้องเลือก A แทน B ทั้งที่ดูคล้ายกัน?' หรือ 'ถ้าเผลอทำ X จะเกิดผลเสียอะไรตามมา?' เพื่อดักจุดสับสนในห้องสอบและหน้างาน\n"
                        f"3. **ถามข้อยกเว้น/จุดพลิกเกม (What-If / Boundary):** 'แล้วถ้าผู้ป่วยมีเงื่อนไขพิเศษแบบนี้ แนวทางในหน้านี้ยังใช้ได้ไหม หรือต้องเปลี่ยน?' เพื่ออุดช่องโหว่จากกรณีมาตรฐานบนสไลด์\n"
                        f"4. **ถามเชื่อมสู่การใช้งานจริง (So-What):** 'รู้ข้อมูล/ค่านี้แล้ว มันเปลี่ยนการตัดสินใจวินิจฉัยหรือรักษาอย่างไร?' เพื่อให้เห็นภาพการใช้งานจริง\n"
                        f"5. **ถามรอยต่อที่อาจารย์ละไว้ในฐานที่เข้าใจ (Hidden Assumption):** จุดที่ผู้สอนข้ามไปเพราะนึกว่านักศึกษารู้อยู่แล้ว แต่จริงๆ เป็นรอยต่อที่ทำให้เข้าใจเรื่องไม่ติด\n\n"
                        f"**คำถามต้องห้าม (ตัดทิ้งเด็ดขาด):**\n"
                        f"- ห้ามถามนิยาม/ความจำผิวเผินแบบ Flashcard ('มีกี่ชนิด?', 'ย่อมาจากอะไร?', 'ค่าปกติเท่าไร?')\n"
                        f"- ห้ามถามลึกเกินระดับ นสพ. ปี {med_year} จนไม่ช่วยทำข้อสอบหรือดูแลคนไข้\n"
                        f"- ห้ามถามคำถามที่คำตอบซ้ำกับสิ่งที่สรุปไว้แล้วใน [HIGH-YIELD]"
                    )

                grounded_context = build_grounded_context(target, window=st.session_state.context_window)
                prompt = (
                    st.session_state.custom_prompt_text
                    .replace("{global_context}", grounded_context)
                    .replace("{section_instructions}", "\n\n".join(sections))
                )

                is_success = False
                retry_count = 0
                while retry_count < 2 and not is_success:
                    try:
                        resp = model.generate_content([prompt, img], safety_settings=safety, generation_config=config)
                        final_text = resp.text.strip()
                        st.session_state.estimated_tokens_used += len(final_text)

                        if "NON_CONTENT" in final_text and len(final_text) < 40:
                            final_text = ""

                        st.session_state.processed_data[target] = {"ai_text": final_text, "user_text": ""}
                        save_workspace()
                        is_success = True
                    except Exception as e:
                        err_msg = str(e)
                        if "429" in err_msg or "Quota" in err_msg:
                            st.session_state.exhausted_models[active_m] = time.time() + 60
                            action_placeholder.markdown(f"<div class='status-yellow'><b>⚠️ `{active_m}` โควตาเต็ม กำลังสลับโมเดลสำรอง...</b></div>", unsafe_allow_html=True)
                            time.sleep(1.5)
                            new_model = get_best_available_model(st.session_state.flash_models_list)
                            if new_model and new_model != active_m:
                                active_m = new_model
                                st.session_state.current_active_model = new_model
                                model = genai.GenerativeModel(new_model)
                                retry_count += 1
                            else:
                                st.session_state.processed_data[target] = {"ai_text": "⚠️ โควตาเต็มทุกโมเดล รอ 1 นาทีแล้วกด Continue ครับ", "user_text": ""}
                                is_success = True
                        else:
                            st.session_state.processed_data[target] = {"ai_text": f"⚠️ Error: {err_msg}", "user_text": ""}
                            is_success = True

                time.sleep(0.05)
                st.rerun()
            else:
                st.session_state.is_running = False
                st.session_state.phase = 'idle'
                save_workspace()
                action_placeholder.markdown(
                    "<div class='status-blue' style='border-left-color:#16A34A;color:#166534;background:#F0FDF4;'>"
                    "<b>✅ ประมวลผลครบทุกหน้าที่เลือกแล้ว!</b> กดปุ่มประกอบไฟล์ PDF ด้านล่างได้เลยครับ</div>",
                    unsafe_allow_html=True
                )
