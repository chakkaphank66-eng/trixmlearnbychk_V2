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

# --- 1. การตั้งค่าเริ่มต้น และ Session State ---
keys_to_init = {
    'processed_data': {}, 'page_idx': 0, 'is_running': False, 'stop_clicked': False, 
    'exhausted_models': {}, 'current_active_model': None, 'flash_models_list': [], 
    'pdf_bytes': None, 'pdf_name': "", 'selected_pages': [],
    'show_reset_confirm': False, 'show_start_popup': False, 'estimated_tokens_used': 0, 
    'status_mode': 'blue', 'user_api_key': "", 'phase': 'idle', 'global_data': {}, 
    'use_custom_prompt': False, 'custom_prompt_text': "",
    'show_download_modal': False, 'base_pdf_doc_bytes': None,
    'layout_prefs': {}
}

for k, v in keys_to_init.items():
    if k not in st.session_state: st.session_state[k] = v

st.set_page_config(page_title="Textbook Note Space 🩺", layout="wide")

# --- 2. Custom CSS ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');
    html, body, [class*="st-"] { font-family: 'Sarabun', sans-serif !important; }
    .stApp { background-color: #F8FAFC; }
    .main-header { font-size: 2.2rem; font-weight: 800; color: #0F172A; margin-bottom: 1rem; }
    .reading-box { background: #FFFFFF; border-radius: 12px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border-top: 5px solid #3B82F6; font-size: 16px; line-height: 1.6; color: #1E293B; margin-bottom: 15px;}
    .reading-box strong, .reading-box b { color: #0F172A; font-weight: 700; background: #FEF9C3; padding: 0 4px; border-radius: 4px; }
    .reading-box table { width: 100%; border-collapse: collapse; margin: 15px 0; border-radius: 8px; overflow: hidden; }
    .reading-box th { background-color: #F1F5F9; padding: 10px; border-bottom: 2px solid #CBD5E1; text-align: left; }
    .reading-box td { border: 1px solid #E2E8F0; padding: 10px; }
    .status-blue { background: #EBF8FF; border-left: 5px solid #3182CE; color: #2B6CB0; padding: 15px; border-radius: 10px; margin-bottom: 15px;}
    .status-yellow { background: #FFFFF0; border-left: 5px solid #D69E2E; color: #B7791F; padding: 15px; border-radius: 10px; margin-bottom: 15px;}
    .status-red { background: #FFF5F5; border-left: 5px solid #E53E3E; color: #C53030; padding: 15px; border-radius: 10px; margin-bottom: 15px;}
    .status-purple { background: #FAF5FF; border-left: 5px solid #805AD5; color: #553C9A; padding: 15px; border-radius: 10px; margin-bottom: 15px;}
    
    /* กล่องสีสำหรับหัวข้อต่างๆ */
    .box-topic { padding: 4px 8px; margin: 8px 0 4px 0; border-radius: 4px; font-weight: bold; font-size: 0.95em; }
    .box-intro { background-color: #F8FAFC; border-left: 4px solid #94A3B8; color: #475569; }
    .box-concept { background-color: #EEF2FF; border-left: 4px solid #6366F1; color: #4338CA; }
    .box-mech { background-color: #F1F5F9; border-left: 4px solid #475569; color: #334155; }
    .box-clinic { background-color: #F0FDFA; border-left: 4px solid #14B8A6; color: #0F766E; }
    .box-warn { background-color: #FFF7ED; border-left: 4px solid #F97316; color: #C2410C; }
    .box-hy { background-color: #FFF1F2; border-left: 4px solid #F43F5E; color: #BE123C; }
    .box-trick { background-color: #FEF9C3; border-left: 4px solid #EAB308; color: #A16207; }
    .box-quiz { background-color: #F0F9FF; border-left: 4px solid #0EA5E9; color: #0369A1; }
</style>
""", unsafe_allow_html=True)

# --- 3. ฟังก์ชันอัจฉริยะ (Helpers) ---
def extract_images_from_page(doc, page_num):
    page = doc[page_num]
    image_list = page.get_images(full=True)
    extracted_images = []
    for img_index, img in enumerate(image_list):
        xref = img[0]
        try:
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            im = Image.open(io.BytesIO(image_bytes))
            if im.width >= 150 and im.height >= 150: extracted_images.append(image_bytes)
        except: pass
    return extracted_images

def get_best_available_model(models_list):
    current_time = time.time()
    st.session_state.exhausted_models = {k: v for k, v in st.session_state.exhausted_models.items() if v > current_time}
    preferred = ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash"]
    sorted_models = sorted(models_list, key=lambda x: next((i for i, p in enumerate(preferred) if p in x), 99))
    for m in sorted_models:
        if m not in st.session_state.exhausted_models: return m
    return "gemini-3.1-flash-lite" 

# --- 4. Sidebar: ตั้งค่า Layout แบบละเอียด ---
with st.sidebar:
    st.markdown("<h2 style='color: #2D3748;'>⚙️ ควบคุมโครงสร้างแอป</h2>", unsafe_allow_html=True)
    is_locked = st.session_state.is_running
    
    api_input = st.text_input("🔑 Gemini API Key:", type="password", value=st.session_state.user_api_key, disabled=is_locked)
    if api_input != st.session_state.user_api_key: st.session_state.user_api_key = api_input; st.rerun()
        
    api_key = st.session_state.user_api_key
    if api_key:
        genai.configure(api_key=api_key)
        all_models = [m.name.replace("models/", "") for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        flash_models = [m for m in all_models if "flash" in m.lower() or "3.1" in m.lower()] or ["gemini-3.1-flash-lite"]
        st.session_state.flash_models_list = sorted(flash_models, key=lambda x: 0 if "3.1" in x else 1)
        st.session_state.current_active_model = get_best_available_model(st.session_state.flash_models_list)

    st.divider()
    st.markdown("### 📐 จัดสรรพื้นที่กระดาษ (Export)")
    margin_right_pct = st.slider("เพิ่มพื้นที่ด้านขวา (%)", 0, 150, 70, disabled=is_locked)
    margin_bottom_pct = st.slider("เพิ่มพื้นที่ด้านล่าง (%)", 0, 150, 30, disabled=is_locked)

    st.markdown("### 📋 เลือกหัวข้อ & ตำแหน่ง (ขวา/ล่าง)")
    
    sections = [
        ("intro", "🔗 Intro / วัตถุประสงค์", True, "ด้านขวา"),
        ("concept", "🎯 Concept หลัก", True, "ด้านขวา"),
        ("mech", "⚙️ กลไกและเหตุผล", True, "ด้านขวา"),
        ("example", "💡 ตัวอย่าง", True, "ด้านขวา"),
        ("clinic", "🩺 นำไปใช้ในคลินิก", True, "ด้านขวา"),
        ("warn", "⚠️ ระวัง / ล้าสมัย", True, "ด้านล่าง"),
        ("hy", "🚨 High-Yield / สรุป", True, "ด้านล่าง"),
        ("trick", "💡 Trick & Cross-ref", True, "ด้านล่าง"),
        ("quiz", "📝 Quiz", True, "ด้านล่าง")
    ]
    
    prefs = {}
    with st.expander("เปิด/ปิด และ จัดตำแหน่ง", expanded=True):
        st.caption("พื้นที่ขวาจะลากยาวลงมาสุดขอบล่างแล้ว แนะนำให้เอาเนื้อหาหลักไว้ขวาครับ")
        for key, label, def_want, def_pos in sections:
            c1, c2 = st.columns([3, 2])
            w = c1.checkbox(label, value=def_want, disabled=is_locked, key=f"w_{key}")
            p = c2.selectbox(" ", ["ด้านขวา", "ด้านล่าง"], index=0 if def_pos=="ด้านขวา" else 1, key=f"p_{key}", disabled=is_locked or not w, label_visibility="collapsed")
            prefs[key] = {"want": w, "pos": p, "label": label, "tag": key.upper()}
    st.session_state.layout_prefs = prefs

    st.markdown("### 🛠️ ปรับแต่ง Prompt")
    use_custom_prompt = st.checkbox("เปิดแก้ไข Prompt หลัก", value=st.session_state.use_custom_prompt, disabled=is_locked)
    
    # สร้างโครงสร้าง Tag ให้ AI แบบอัตโนมัติตามที่เลือก
    tag_instructions = "\n".join([f"[{v['tag']}]\n(เขียนเนื้อหา {v['label']} ตรงนี้)\n[/{v['tag']}]" for k, v in prefs.items() if v['want']])
    
    base_prompt_template = f"""คุณคือผู้เชี่ยวชาญการจัดโครงสร้างข้อมูลการแพทย์ (Medical Information Architect)
เป้าหมาย: อ่านหน้าสไลด์/Textbook และจัดระเบียบเนื้อหาให้กระชับ เป็นคีย์เวิร์ด เรียบเรียงตามต้นฉบับ ห้ามข้ามเนื้อหาสำคัญ เพื่อให้นำไปทบทวนได้รวดเร็วและจำได้นาน

**บริบทความเชื่อมโยง (อดีต 5 หน้า, อนาคต 10 หน้า):**
{{global_context}}

**ข้อความ Text ดิบจากหน้านี้ (ป้องกันข้อมูลยา/ปริมาณตกหล่น):**
---
{{raw_text}}
---

**กฎข้อบังคับ (Strict Rules):**
1. **จัดรูปแบบเป็นตาราง:** ถ้าย่อหน้ามีข้อมูลหลายมิติ หรือต้นฉบับเป็นตาราง ให้ทำเป็น Markdown Table เสมอ
2. **ตัวหนา:** เน้นตัวหนา (**Keyword**) ที่คำสำคัญเพื่อกวาดสายตาไว
3. **ความเป็นเหตุเป็นผล:** การอธิบายกลไก (Patho) ให้แทรกคำว่า **'...เพราะ...'** เสมอ
4. **รูปภาพ:** ตรงไหนมีรูปภาพในต้นฉบับ ให้พิมพ์คำว่า `[IMAGE_PLACEHOLDER]` เพื่อให้ระบบดึงรูปเดิมมาแปะ
5. หากเป็นหน้าเกริ่นนำ ให้สรุปสั้นๆ และพิมพ์บอกว่า '⏩ ข้ามได้เพราะ...'

**จงสร้างเนื้อหาโดยครอบด้วยแท็ก (Tags) ต่อไปนี้เท่านั้น ห้ามพิมพ์นอกแท็กเด็ดขาด:**
{tag_instructions}"""

    if use_custom_prompt:
        st.session_state.custom_prompt_text = st.text_area("แก้ไข Prompt", value=st.session_state.custom_prompt_text or base_prompt_template, height=400, disabled=is_locked)
    else:
        st.session_state.custom_prompt_text = base_prompt_template
    st.session_state.use_custom_prompt = use_custom_prompt

# --- 5. Main UI: อัปโหลด ---
st.markdown("<div class='main-header'>📚 Clinical Master Note: จัดโครงสร้างอัตโนมัติ</div>", unsafe_allow_html=True)

if not st.session_state.pdf_bytes:
    uploaded_file = st.file_uploader("อัปโหลด Textbook / สไลด์เนื้อหาแน่นๆ (PDF)", type="pdf")
    if uploaded_file:
        st.session_state.pdf_bytes = uploaded_file.getvalue()
        st.session_state.pdf_name = uploaded_file.name
        doc_tmp = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
        st.session_state.selected_pages = list(range(len(doc_tmp))); st.rerun()
else:
    st.info(f"📄 ไฟล์ปัจจุบัน: **{st.session_state.pdf_name}** | {len(fitz.open(stream=st.session_state.pdf_bytes, filetype='pdf'))} หน้า")
    if st.button("🗑️ เปลี่ยนเอกสาร (Reset)"): [st.session_state.pop(k) for k in keys_to_init if k in st.session_state]; st.rerun()

# --- 6. แถบสถานะการรันอัตโนมัติ ---
if st.session_state.pdf_bytes:
    doc_in = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
    total_pages = len(doc_in)
    
    if st.session_state.show_start_popup:
        with st.container():
            pages_to_do = len([i for i in st.session_state.selected_pages if i not in st.session_state.processed_data])
            st.info(f"📊 หน้าที่ต้องรันเพิ่ม: **{pages_to_do} หน้า**")
            c_start1, c_start2 = st.columns(2)
            if c_start1.button("✅ ยืนยันรันงาน (Auto Mode)", type="primary"):
                st.session_state.current_active_model = get_best_available_model(st.session_state.flash_models_list)
                if st.session_state.phase == 'idle': st.session_state.phase = 'global_scan'
                st.session_state.is_running = True; st.session_state.show_start_popup = False; st.rerun()
            if c_start2.button("❌ ยกเลิก"): st.session_state.show_start_popup = False; st.rerun()
    
    action_placeholder = st.empty() 

    col_run1, col_ctrl2, col_ctrl3 = st.columns([1,1,1])
    if col_run1.button("🚀 Start Auto-Scan", type="primary", disabled=is_locked): st.session_state.show_start_popup = True; st.rerun()
    if col_ctrl2.button("🛑 Stop / Pause", disabled=not st.session_state.is_running): st.session_state.is_running = False; st.session_state.stop_clicked = True; st.rerun()

    # --- 7. Reader View (หน้าจออ่าน) ---
    st.write("---")
    curr = st.session_state.page_idx
    c_nav1, c_nav2, c_nav3 = st.columns([1, 2, 1])
    with c_nav1:
        if st.button("⬅️ ย้อนกลับ") and curr > 0: st.session_state.page_idx -= 1; st.rerun()
    with c_nav2:
        st.session_state.page_idx = st.slider("ไปหน้า:", 1, total_pages, curr + 1, label_visibility="collapsed") - 1
    with c_nav3:
        if st.button("ถัดไป ➡️") and curr < total_pages - 1: st.session_state.page_idx += 1; st.rerun()

    col_left, col_right = st.columns([1, 1.3])
    with col_left:
        st.markdown(f"**📖 หน้า {curr+1} (ต้นฉบับ)**")
        st.image(doc_in[curr].get_pixmap(dpi=100).tobytes("png"), use_container_width=True)

    with col_right:
        if curr in st.session_state.processed_data:
            data = st.session_state.processed_data[curr]
            st.markdown(f"**✨ โครงสร้างใหม่ (เรียงตามลำดับต้นฉบับ)**")
            ai_text = data["ai_text"]
            ext_images = data.get("extracted_images", [])
            
            # โชว์เฉพาะสิ่งที่มีใน Tag
            st.markdown("<div class='reading-box'>", unsafe_allow_html=True)
            img_counter = 0
            
            for key, pref in st.session_state.layout_prefs.items():
                if pref["want"]:
                    # ใช้ Regex ดึงข้อมูลในแท็ก
                    match = re.search(fr"\[{pref['tag']}\](.*?)\[\/{pref['tag']}\]", ai_text, re.DOTALL)
                    if match:
                        content = match.group(1).strip()
                        if content and content != "NON_CONTENT":
                            # ใส่กรอบสีให้หัวข้อ
                            st.markdown(f"<div class='box-topic box-{key}'>{pref['label']}</div>", unsafe_allow_html=True)
                            
                            # แทนที่ [IMAGE_PLACEHOLDER] ด้วยรูป
                            parts = content.split("[IMAGE_PLACEHOLDER]")
                            for i, part in enumerate(parts):
                                st.markdown(markdown.markdown(part, extensions=['tables']), unsafe_allow_html=True)
                                if i < len(parts) - 1:
                                    if img_counter < len(ext_images):
                                        st.image(ext_images[img_counter], use_container_width=True)
                                        img_counter += 1
                                    else: st.info("🖼️ [ภาพประกอบ (ดูจากต้นฉบับ)]")
                            st.markdown("<hr style='margin: 10px 0; border: 0; border-top: 1px dashed #E2E8F0;'>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.info(f"⏳ หน้าที่ {curr+1} รอคิวประมวลผล...")

    # --- 8. Export PDF & Master Review ---
    st.write("---")
    if len(st.session_state.processed_data) > 0:
        if st.button("📦 Export PDF พร้อมหน้าสรุปทบทวน (Master Review)"):
            with st.spinner("กำลังสร้างเอกสาร และประกอบหน้าสรุป... (อาจใช้เวลา 1-2 นาที)"):
                doc_out = fitz.open()
                arch_path = "."
                
                # --- ส่วนที่ 1: สร้างหน้าสไลด์ปกติ (จัด Layout ขวา-ล่าง) ---
                for i in range(total_pages):
                    p_in = doc_in[i]; w, h = p_in.rect.width, p_in.rect.height
                    new_w, new_h = w * (1 + margin_right_pct/100), h * (1 + margin_bottom_pct/100)
                    p_out = doc_out.new_page(width=new_w, height=new_h)
                    p_out.show_pdf_page(fitz.Rect(0, 0, w, h), doc_in, i)
                    
                    bg_color = (0.97, 0.98, 0.99)
                    # พื้นที่ขวา ลากยาวลงมาสุด new_h เลย (L-Shape ตัดกัน)
                    if margin_right_pct > 0: p_out.draw_rect(fitz.Rect(w, 0, new_w, new_h), color=bg_color, fill=bg_color, width=0)
                    # พื้นที่ล่าง วาดเฉพาะใต้สไลด์เดิม (ไม่ทับพื้นที่ขวา)
                    if margin_bottom_pct > 0: p_out.draw_rect(fitz.Rect(0, h, w, new_h), color=bg_color, fill=bg_color, width=0)
                    
                    # กล่องใส่ Text
                    rect_right = fitz.Rect(w + 15, 15, new_w - 15, new_h - 15)
                    rect_bottom = fitz.Rect(15, h + 15, w - 15, new_h - 15)
                    
                    if i in st.session_state.processed_data:
                        data = st.session_state.processed_data[i]
                        ai_text = data["ai_text"]
                        images = data.get("extracted_images", [])
                        
                        if ai_text and "⚠️" not in ai_text:
                            html_right, html_bottom = "", ""
                            img_count = 0
                            
                            for key, pref in st.session_state.layout_prefs.items():
                                if pref["want"]:
                                    match = re.search(fr"\[{pref['tag']}\](.*?)\[\/{pref['tag']}\]", ai_text, re.DOTALL)
                                    if match and match.group(1).strip():
                                        content = match.group(1).strip()
                                        
                                        # จัดเตรียม HTML ของหัวข้อนี้ พร้อมแทรกรูป
                                        section_html = f"<h4 style='color: #2563EB; margin: 5px 0;'>{pref['label']}</h4>"
                                        parts = content.split("[IMAGE_PLACEHOLDER]")
                                        for idx, part in enumerate(parts):
                                            section_html += markdown.markdown(part, extensions=['tables'])
                                            if idx < len(parts) - 1 and img_count < len(images):
                                                tmp_name = f"tmp_{i}_{img_count}.png"
                                                try:
                                                    with open(tmp_name, "wb") as f: f.write(images[img_count])
                                                    section_html += f"<br><img src='{tmp_name}' style='max-width: 100%; border-radius: 5px;'><br>"
                                                    img_count += 1
                                                except: pass
                                        section_html += "<hr style='border: 1px dashed #CBD5E1;'>"
                                        
                                        # แยกใส่ตามกล่อง
                                        if pref["pos"] == "ด้านขวา": html_right += section_html
                                        else: html_bottom += section_html
                            
                            # ยัด HTML ลงกล่องใน PDF
                            f_size = 18 # ฟอนต์ขนาดมาตรฐานอ่านง่าย
                            css = f"@font-face {{ font-family: 'T'; src: url('THSarabunNew.ttf'); }} body {{ font-family: 'T'; font-size: {f_size}px; line-height: 1.4; color: #1E293B; }} b, strong {{ color: #0F172A; background-color: #FEF9C3; }} table {{ border-collapse: collapse; width: 100%; }} th {{ background: #F1F5F9; border: 1px solid #CBD5E1; }} td {{ border: 1px solid #E2E8F0; }}"
                            
                            if html_right: p_out.insert_htmlbox(rect_right, f"<style>{css}</style><body>{html_right}</body>", archive=fitz.Archive(arch_path))
                            if html_bottom: p_out.insert_htmlbox(rect_bottom, f"<style>{css}</style><body>{html_bottom}</body>", archive=fitz.Archive(arch_path))

                # --- ส่วนที่ 2: สร้างหน้า Master Review (สรุปท้ายเล่ม) ---
                review_w, review_h = 595, 842 # A4 Size
                y_cursor = 50
                p_review = doc_out.new_page(width=review_w, height=review_h)
                
                # Header เล่ม
                p_review.insert_textbox(fitz.Rect(40, 20, review_w-40, 50), "⭐ Master Clinical Review (คลิกหัวข้อเพื่อกลับไปหน้าต้นฉบับ)", fontsize=18, color=(0.1, 0.5, 0.8), align=1)
                
                for i in range(total_pages):
                    if i in st.session_state.processed_data and "⚠️" not in st.session_state.processed_data[i]["ai_text"]:
                        # ถ้าพื้นที่เหลือน้อยกว่า 350px ให้ขึ้นหน้า A4 ใหม่
                        if y_cursor > review_h - 350:
                            p_review = doc_out.new_page(width=review_w, height=review_h)
                            y_cursor = 40
                            
                        # 1. เขียนหัวข้อพร้อมสร้าง Hyperlink
                        rect_title = fitz.Rect(40, y_cursor, review_w - 40, y_cursor + 30)
                        p_review.draw_rect(rect_title, color=(0.9,0.9,0.95), fill=(0.9,0.9,0.95), width=0)
                        p_review.insert_textbox(rect_title, f"🔗 ทบทวนเนื้อหาจาก: สไลด์หน้า {i+1}", fontsize=14, color=(0.1, 0.1, 0.6))
                        # สร้างลิงก์วาร์ปกลับไปหน้าสไลด์
                        p_review.insert_link({"kind": fitz.LINK_GOTO, "page": i, "from": rect_title}) 
                        y_cursor += 35
                        
                        # 2. รวบรวม HTML ทุกหัวข้อของหน้านี้
                        data = st.session_state.processed_data[i]
                        ai_text = data["ai_text"]
                        all_html = ""
                        for key, pref in st.session_state.layout_prefs.items():
                            if pref["want"]:
                                match = re.search(fr"\[{pref['tag']}\](.*?)\[\/{pref['tag']}\]", ai_text, re.DOTALL)
                                if match and match.group(1).strip():
                                    all_html += f"<b>{pref['label']}</b><br>" + markdown.markdown(match.group(1).strip().replace("[IMAGE_PLACEHOLDER]", "<i>[ภาพประกอบในหน้าเต็ม]</i>"), extensions=['tables'])
                        
                        # 3. หยอดลง PDF
                        rect_content = fitz.Rect(40, y_cursor, review_w - 40, y_cursor + 300) # ให้โควต้า 300px ต่อสไลด์
                        css_review = "@font-face { font-family: 'T'; src: url('THSarabunNew.ttf'); } body { font-family: 'T'; font-size: 14px; line-height: 1.3; color: #334155; } b { color: #0F172A; } table { width: 100%; border-collapse: collapse; } th, td { border: 1px solid #CBD5E1; padding: 4px; }"
                        p_review.insert_htmlbox(rect_content, f"<style>{css_review}</style><body>{all_html}</body>", archive=fitz.Archive(arch_path))
                        y_cursor += 310

                # ทำความสะอาดไฟล์รูป Temp
                for f in os.listdir("."):
                    if f.startswith("tmp_") and f.endswith(".png"):
                        try: os.remove(f)
                        except: pass

                st.session_state.base_pdf_doc_bytes = doc_out.tobytes(garbage=3, deflate=True)
                st.session_state.show_download_modal = True

        if st.session_state.get('show_download_modal') and st.session_state.get('base_pdf_doc_bytes'):
            st.markdown("""<div style="border: 2px solid #3182CE; border-radius: 12px; padding: 25px; background-color: #F8FAFC; margin-top: 15px;">
                <h3 style="color: #2B6CB0; margin-top: 0;">🗜️ โหลดเอกสาร Clinical Master Note</h3>""", unsafe_allow_html=True)
            
            final_bytes = st.session_state.base_pdf_doc_bytes
            st.markdown(f"📉 ขนาดไฟล์พร้อมหน้าสรุป: <strong style='color: #E53E3E;'>{len(final_bytes) / (1024 * 1024):.2f} MB</strong>", unsafe_allow_html=True)
            st.download_button("💾 ดาวน์โหลดไฟล์ PDF", data=final_bytes, file_name=f"MasterNote_{st.session_state.pdf_name}", mime="application/pdf", type="primary")
            if st.button("❌ ปิด"): st.session_state.show_download_modal = False; st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    # --- 9. Background Worker (ออโต้สแกน 2 Phase) ---
    if st.session_state.is_running and not st.session_state.stop_clicked:
        active_m = st.session_state.current_active_model
        model = genai.GenerativeModel(active_m)
        safety = { HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE }

        if st.session_state.phase == 'global_scan':
            target_global = next((i for i in st.session_state.selected_pages if i not in st.session_state.global_data), None)
            if target_global is None: st.session_state.phase = 'detail_scan'; st.rerun()
            else:
                action_placeholder.markdown(f"<div class='status-purple'><b>🔍 [Phase 1/2] ประเมินโครงสร้างภาพรวม (หน้า {target_global+1}/{total_pages})</b></div>", unsafe_allow_html=True)
                img = Image.open(io.BytesIO(doc_in[target_global].get_pixmap(dpi=50).tobytes("png")))
                prompt_global = "วิเคราะห์สไลด์นี้ด่วน ตอบแค่:\nTOPIC: (ชื่อหัวข้อสั้นๆ)\nSUMMARY: (สรุป 1 ประโยค)\nPRIORITY: (HIGH/MEDIUM/LOW)"
                try:
                    resp = model.generate_content([prompt_global, img], safety_settings=safety, generation_config=GenerationConfig(max_output_tokens=100))
                    text = resp.text.strip()
                    topic = text.split("TOPIC:")[1].split("SUMMARY:")[0].strip() if "TOPIC:" in text else f"หน้า {target_global+1}"
                    summary_raw = text.split("SUMMARY:")[1] if "SUMMARY:" in text else "ข้อมูล"
                    summary = summary_raw.split("PRIORITY:")[0].strip() if "PRIORITY:" in summary_raw else summary_raw.strip()
                    st.session_state.global_data[target_global] = {'topic': topic, 'summary': summary}
                except: st.session_state.global_data[target_global] = {'topic': f"หน้า {target_global+1}", 'summary': ""}
                time.sleep(0.1); st.rerun()

        elif st.session_state.phase == 'detail_scan':
            target = next((i for i in range(total_pages) if i in st.session_state.processed_data and "⚠️" in st.session_state.processed_data[i].get("ai_text", "")), None)
            if target is None: target = next((i for i in range(total_pages) if i not in st.session_state.processed_data and i in st.session_state.selected_pages), None)

            if target is not None:
                action_placeholder.markdown(f"<div class='status-blue'><b>⚡ จัดโครงสร้างข้อมูลหน้า {target+1} / {total_pages}</b><br>🤖 วิเคราะห์ Context อดีต 5 - อนาคต 10</div>", unsafe_allow_html=True)
                
                # Context Window
                start_idx, end_idx = max(0, target - 5), min(total_pages, target + 11)
                context_lines = [f"{'👉' if idx==target else '-'} หน้า {idx+1} ({st.session_state.global_data.get(idx, {}).get('topic','')}): {st.session_state.global_data.get(idx, {}).get('summary','')}" for idx in range(start_idx, end_idx)]
                
                raw_text = doc_in[target].get_text()
                extracted_images = extract_images_from_page(doc_in, target)
                p_img = doc_in[target].get_pixmap(dpi=75)
                img = Image.open(io.BytesIO(p_img.tobytes("png")))

                prompt = st.session_state.custom_prompt_text.replace("{global_context}", "\n".join(context_lines)).replace("{raw_text}", raw_text)
                
                try:
                    resp = model.generate_content([prompt, img], safety_settings=safety, generation_config=GenerationConfig(max_output_tokens=6000))
                    st.session_state.processed_data[target] = {"ai_text": resp.text.strip(), "extracted_images": extracted_images, "raw_text": raw_text}
                except Exception as e:
                    st.session_state.processed_data[target] = {"ai_text": f"⚠️ Error: {str(e)}"}
                time.sleep(0.1); st.rerun()
            else:
                st.session_state.is_running, st.session_state.phase = False, 'idle'
                action_placeholder.markdown(f"<div class='status-blue' style='border-left-color: #38A169; color: #2F855A; background: #F0FFF4;'><b>✅ ประมวลผลเสร็จสิ้น!</b></div>", unsafe_allow_html=True)
