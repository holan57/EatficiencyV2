import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from google import genai
from google.genai import types
import json
import os
from datetime import datetime
from streamlit_javascript import st_javascript
import traceback

# --- 頁面設定 ---
st.set_page_config(page_title="Eatficiency-飲食記錄家 V2", page_icon="💰", layout="centered")

# 載入自訂 CSS
current_dir = os.path.dirname(__file__)
css_path = os.path.join(current_dir, "style.css")
if os.path.exists(css_path):
    with open(css_path, "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# 修正側邊欄單選按鈕可能出現的 "keyboard" 字樣或快捷鍵提示
st.markdown("""
    <style>
    /* 隱藏單選按鈕 (radio) 旁邊產生的鍵盤快捷鍵數字或提示文字 */
    [data-testid="stSidebar"] div[role="radiogroup"] [data-testid="stMarkdownContainer"] + span {
        display: none !important;
    }
    
    /* 確保 Material Icons 不會被自訂字體覆蓋而變成文字 */
    .material-icons, .material-symbols-outlined {
        font-family: 'Material Symbols Outlined' !important;
    }
    </style>
""", unsafe_allow_html=True)

# (側邊欄與標題的定義已移至讀取記帳資料之後載入)

# --- 讀取設定 ---
try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    MONTHLY_BUDGET = st.secrets.get("MONTHLY_BUDGET", 15000)
except Exception as e:
    st.error("安全性設定錯誤: 找不到 GOOGLE_API_KEY。請檢查 .streamlit/secrets.toml。")
    st.stop()

MODEL_NAME = 'gemini-2.5-flash-lite'

# 初始化 Gemini
client = genai.Client(api_key=GOOGLE_API_KEY)

@st.dialog("健康與理財建議")
def show_advice_modal(advice_text):
    st.write(advice_text)
    if st.button("關閉"):
        st.rerun()

# --- Google Sheets 連線 ---
conn = st.connection("gsheets", type=GSheetsConnection)

def get_users():
    """讀取使用者資料"""
    try:
        return conn.read(worksheet="User_Data", ttl=0)
    except Exception:
        return pd.DataFrame(columns=["user_name"])

def add_user(name):
    """新增使用者"""
    df = get_users()
    if name not in df['user_name'].values:
        new_row = pd.DataFrame([{"user_name": name}])
        updated_df = pd.concat([df, new_row], ignore_index=True)
        conn.update(worksheet="User_Data", data=updated_df)
        st.cache_data.clear()

def get_ref_data():
    """讀取參考資料以提升辨識率"""
    try:
        return conn.read(worksheet="Ref_data", ttl=3600)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=300)  # 快取 5 分鐘，避免頻繁讀取 Sheets
def get_expenses():
    """從 Google Sheets 讀取資料"""
    try:
        df = conn.read(worksheet="History_record", ttl=0)
        if df is None or df.empty:
            return pd.DataFrame(columns=["user_name", "date", "foodname", "amount", "category", "calories", "health_score", "advice"])
        return df
    except Exception as e:
        st.error(f"無法讀取試算表資料，請檢查連線設定。錯誤訊息: {e}")
        return pd.DataFrame(columns=["user_name", "date", "foodname", "amount", "category", "calories", "health_score", "advice"])

def save_to_sheets(new_data):
    """將新資料存入 Google Sheets"""
    df = get_expenses()
    new_row = pd.DataFrame([new_data])
    updated_df = pd.concat([df, new_row], ignore_index=True)
    conn.update(worksheet="History_record", data=updated_df)
    st.cache_data.clear()  # 存檔後清除快取，確保下次讀取到最新資料

def analyze_with_gemini(text_content=None, image_content=None, ref_data=None):
    """
    單筆消費辨識：將文字或圖片轉換為記帳格式
    """
    ref_str = ref_data.to_string(index=False) if ref_data is not None and not ref_data.empty else "無"
    
    prompt = f"""
    分析以下食物資料：{text_content or "請分析圖片"}
    參考清單：{ref_str}
    """
    
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[prompt] + ([types.Part.from_bytes(data=image_content, mime_type='image/jpeg')] if image_content else []),
        config={
            "response_mime_type": "application/json",
            "system_instruction": "你是一個飲食記帳專家。請分析資料並回傳 JSON 格式：{\"date\":\"YYYY-MM-DD\", \"foodname\":\"品名\", \"amount\":金額, \"category\":\"中式/西式/日式/其他\", \"calories\":熱量, \"health_score\":1-10, \"advice\":\"健康建議\"}"
        }
    )
    return json.loads(response.text)

@st.cache_data(ttl=3600)
def get_overall_advice(cache_key, google_key, df_json):
    """
    整體建議分析：根據歷史紀錄提供理財與飲食建議
    """
    prompt = f"請分析以下使用者的歷史飲食與消費紀錄，並提供專業的理財與健康建議：{df_json}"
    
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[prompt],
        config={
            "response_mime_type": "application/json",
            "system_instruction": """
            你是一個結合營養學與財務管理的專家。
            請針對數據分析趨勢，回傳 JSON：
            {
              "analysis": {
                "summary": "一句話總結建議",
                "reason": "詳細的分析理由與改善方向"
              }
            }"""
        }
    )
    return json.loads(response.text)

@st.fragment
def render_ai_advice_section(df_all, google_key):
    """AI 建議片段：讓 AI 運算時不影響主介面輸入"""
    st.markdown("### 💡 AI 飲食與財務建議")
    
    df_json = df_all.to_json(orient="records")
    total_amount_sum = pd.to_numeric(df_all['amount'], errors='coerce').fillna(0).astype(int).sum() if not df_all.empty else 0
    cache_key = f"len_{len(df_all)}_sum_{total_amount_sum}_budget_{MONTHLY_BUDGET}"

    with st.spinner("AI 正在分析您的數據..."):
        ai_advice = get_overall_advice(cache_key, google_key, df_json)

    # 修正：從字典中正確提取 summary (原本嵌套在 analysis 內)
    display_summary = ai_advice.get('analysis', {}).get('summary') if 'analysis' in ai_advice else ai_advice.get('summary', '無法取得建議')

    advice_html = f"""
    <div class="custom-card advice-card">
        <div class="card-header">🤖 AI 智慧理財與飲食建議</div>
        <div class="card-body">
            <div class="advice-text">{display_summary}</div>
        </div>
    </div>
    """
    st.markdown(advice_html, unsafe_allow_html=True)

    if st.checkbox("顯示建議理由", key="show_reason_fragment"):
        display_reason = ai_advice.get('analysis', {}).get('reason') if 'analysis' in ai_advice else ai_advice.get('reason', '無詳細理由')
        st.markdown(f"""
        <div class="reasoning-box">
            💡 <b>詳細理由與分析：</b><br/>
            {display_reason}
        </div>
        """, unsafe_allow_html=True)

@st.fragment
def render_sidebar_stats(df_all):
    """側邊欄統計資訊片段，可獨立更新"""
    st.header("📊 本月預算統計")
    current_month = datetime.now().strftime('%Y-%m')
    
    if not df_all.empty and 'date' in df_all.columns:
        df_all_for_calc = df_all.copy()
        df_all_for_calc['date_parsed'] = pd.to_datetime(df_all_for_calc['date'], errors='coerce')
        month_mask = df_all_for_calc['date_parsed'].dt.strftime('%Y-%m') == current_month
        df_month = df_all_for_calc[month_mask]
        total_spent = pd.to_numeric(df_month['amount'], errors='coerce').fillna(0).astype(int).sum()
    else:
        total_spent = 0

    remaining = MONTHLY_BUDGET - total_spent
    progress = min(total_spent / MONTHLY_BUDGET, 1.0) if MONTHLY_BUDGET > 0 else 0
    progress_pct = progress * 100

    card_class = "budget-card-warning" if progress > 0.8 else "budget-card"
    budget_status_html = f"""
    <div class="custom-card {card_class}" style="padding: 15px !important; margin-bottom: 10px !important;">
        <div style="font-weight: 700; margin-bottom: 8px; font-size: 1rem; color: #f8fafc;">{current_month} 預算</div>
        <div style="font-size: 0.9rem; line-height: 1.5; color: #cbd5e1;">
            <div style="display: flex; justify-content: space-between;">
                <span>已花費:</span>
                <span><b>${total_spent:,}</b></span>
            </div>
            <div style="display: flex; justify-content: space-between;">
                <span>總預算:</span>
                <span><b>${MONTHLY_BUDGET:,}</b></span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-top: 4px;">
                <span>剩餘:</span>
                <span style="color: {'#ef4444' if remaining < 0 else '#10b981'};"><b>${remaining:,}</b></span>
            </div>
        </div>
        <div style="background-color: rgba(255, 255, 255, 0.1); border-radius: 10px; height: 6px; width: 100%; overflow: hidden; margin-top: 8px;">
            <div style="background-color: {'#ef4444' if progress > 0.8 else '#10b981'}; width: {progress_pct}%; height: 100%; border-radius: 10px;"></div>
        </div>
    </div>
    """
    st.markdown(budget_status_html, unsafe_allow_html=True)
    st.divider()
    
    st.header("👤 使用者設定")
    st.write(f"當前使用者: **{st.session_state.get('user_name', '未登入')}**")
    if st.button("切換使用者"):
        del st.session_state.user_name
        st.rerun()

# --- 主程式執行區 ---

# 0. 使用者登入邏輯
if "user_name" not in st.session_state:
    st.title("💰 Eatficiency 歡迎您")
    users_df = get_users()
    user_list = users_df['user_name'].tolist() if not users_df.empty else []
    
    with st.container(border=True):
        selected_user = st.selectbox("選擇既有帳號", ["請選擇..."] + user_list)
        new_user = st.text_input("或建立新帳號")
        if st.button("開始使用", type="primary", use_container_width=True):
            if new_user:
                add_user(new_user)
                st.session_state.user_name = new_user
                st.rerun()
            elif selected_user != "請選擇...":
                st.session_state.user_name = selected_user
                st.rerun()
    st.stop()

# 1. 讀取資料 (有快取)
df_all = get_expenses()

# 3. 側邊欄導覽與設定
with st.sidebar:
    st.header("🧭 導覽選單")
    # 在這裡定義 menu 變數，修復 NameError
    menu = st.radio("選擇功能", ["📝 快速記帳 & AI建議", "📋 歷史消費紀錄"], index=0)
    st.divider()
    # 呼叫統計片段
    # 僅傳送該使用者的資料給側邊欄統計
    df_user_only = df_all[df_all['user_name'] == st.session_state.user_name] if not df_all.empty else df_all
    render_sidebar_stats(df_user_only)

# 4. 全域變數偵測 (供主畫面使用)
ua_string = st_javascript("navigator.userAgent")
is_mobile = any(x in (ua_string or "").lower() for x in ["mobi", "android", "iphone"])
user_name = st.session_state.user_name

if menu == "📝 快速記帳 & AI建議":
    # 根據 user 名稱篩選歷史紀錄傳遞給 AI 建議引擎
    df_user_only = df_all[df_all['user_name'] == user_name] if not df_all.empty else df_all
    render_ai_advice_section(df_user_only, GOOGLE_API_KEY)
    
    st.divider()

    is_confirming = 'result' in st.session_state

    # --- 3. 快速記帳 ---
    st.markdown("### 📝 快速記帳")
    with st.container(border=True):
        text_input = st.text_area(
            "描述消費內容",
            placeholder="例如：早餐 65 元，或是點擊下方按鈕上傳收據...",
            label_visibility="collapsed",
            height=80,
            key="quick_text"
        )

        col_upload, col_recognize = st.columns([4, 1])

        with col_upload:
            if is_mobile:
                # 行動端：預設只顯示相機圖示按鈕
                if not st.session_state.get("show_camera", False):
                    if st.button("📷", use_container_width=True, help="點擊拍照或上傳"):
                        st.session_state.show_camera = True
                        st.rerun()
                    uploaded_file = st.session_state.get("temp_img_bytes", None)
                else:
                    # 點擊後顯示上傳組件（手機上會彈出拍照/相簿選單）
                    mobile_file = st.file_uploader("選取動作", type=['jpg', 'jpeg', 'png'], key="mob_up")
                    if mobile_file:
                        st.session_state.temp_img_bytes = mobile_file.getvalue()
                        st.session_state.show_camera = False
                        st.rerun()
                    if st.button("取消", key="cancel_cam"):
                        st.session_state.show_camera = False
                        st.rerun()
                    uploaded_file = None
            else:
                uploaded_file = st.file_uploader(
                    "📷 上傳收據 (選填)",
                    type=['jpg', 'jpeg', 'png'],
                    label_visibility="collapsed",
                    key="quick_file"
                )

        with col_recognize:
            st.write("")
            recognize_btn = st.button("🔍 辨識", type="primary", use_container_width=True, key="quick_btn")

    if uploaded_file:
        st.image(uploaded_file, caption="已上傳收據", width=180)

    # 執行辨識
    if recognize_btn:
        if text_input or uploaded_file:
            with st.spinner("AI 辨識中..."):
                img_bytes = uploaded_file.getvalue() if uploaded_file else None
                ref_data = get_ref_data()
                result = analyze_with_gemini(text_content=text_input, image_content=img_bytes, ref_data=ref_data)
                if result:
                    st.session_state.result = result
                    # 辨識成功後自動關閉相機畫面
                    st.session_state.show_camera = False
                else:
                    st.warning("辨識結果為空，請稍後再試。")
        else:
            st.warning("請輸入文字描述或上傳收據照片")

    # 顯示辨識結果並進行確認存檔
    if 'result' in st.session_state:
        st.markdown("---")
        st.subheader("確認辨識結果")
        res = st.session_state.result
        
        with st.form("confirm_form"):
            c1, c2, c3, c4 = st.columns(4)
            date = c1.text_input("日期", value=res.get('date'))
            foodname = c2.text_input("品名", value=res.get('foodname'))
            
            amount_val = res.get('amount')
            if amount_val is None:
                amount_val = 0
            try:
                amount = c3.number_input("金額", value=int(amount_val), step=1)
            except (ValueError, TypeError):
                amount = c3.number_input("金額", value=0, step=1)
            
            categories = ["中式", "西式", "日式", "其他"]
            category = c4.selectbox("類別", categories, index=categories.index(res.get('category')) if res.get('category') in categories else 3)
            
            col_action1, col_action2 = st.columns(2)
            with col_action1:
                # 在彈出式對話框中顯示健康度評分與該餐建議
                advice_btn = st.form_submit_button("查看該餐健康建議", use_container_width=True)
            with col_action2:
                save_btn = st.form_submit_button("✅ 確認存檔", type="primary", use_container_width=True)
                
            if advice_btn:
                show_advice_modal(f"健康度評分：{res.get('health_score', 0)} / 10\n\n建議：{res.get('advice', '無')}")
                
            if save_btn:
                final_data = {
                    "user_name": user_name,
                    "date": date,
                    "foodname": foodname, 
                    "amount": amount,
                    "category": category,
                    "calories": res.get('calories', 0),
                    "health_score": res.get('health_score', 0),
                    "advice": res.get('advice', '')
                }
                save_to_sheets(final_data)
                st.success("已存入 Google Sheets！")
                st.session_state.show_camera = False
                st.session_state.temp_img_bytes = None # 清除暫存圖片
                del st.session_state.result
                st.rerun()

else:
    # --- 4. 歷史消費紀錄 ---
    st.subheader("📋 歷史消費紀錄")
    # 僅顯示當前使用者的紀錄
    df_user_history = df_all[df_all['user_name'] == user_name] if not df_all.empty else pd.DataFrame()
    if not df_user_history.empty:
        cols_to_show = ["user_name", "date", "foodname", "amount", "category", "calories", "health_score", "advice"]
        df_clean_display = df_user_history[cols_to_show] if all(col in df_user_history.columns for col in cols_to_show) else df_user_history
        st.dataframe(df_clean_display.iloc[::-1], use_container_width=True)
    else:
        st.info("尚無消費紀錄。")
