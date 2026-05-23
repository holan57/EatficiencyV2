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

@st.cache_data(ttl=300)  # 快取 5 分鐘，避免頻繁讀取 Sheets
def get_expenses():
    """從 Google Sheets 讀取資料"""
    try:
        df = conn.read(ttl=0)
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
    conn.update(data=updated_df)
    st.cache_data.clear()  # 存檔後清除快取，確保下次讀取到最新資料

def analyze_with_gemini(text_content=None, image_content=None):
    """使用 Gemini 分析文字與圖片"""
    today = datetime.now().strftime('%Y-%m-%d')
    base_prompt = f"""
    今天是 {today}。
    你是一個精準的飲食記帳與健康理財助手。
    請分析使用者提供的【圖片】或【文字描述】：
    【核心任務】：
     辨識【食物名稱】、【熱量】、【金額】、【分類】。
     估算【健康度評分】(0-10) 與【建議】。
     格式必須是「純 JSON」，**嚴禁**包含任何 Markdown 標記（如 ```json）、反引號或解釋性文字。
      【JSON 格式需求】：
      {{
        "date": "{today}",
        "foodname": "...",
        "amount": 0,
        "category": "中式",
        "calories": 0,
        "health_score": 0,
        "advice": "..."
      }}

      若無法辨識任何資訊，請在 JSON 對應欄位填入 null，不要回傳錯誤訊息。
      """
    
    try:
        contents = [base_prompt]
        if image_content:
            contents.append(types.Part.from_bytes(data=image_content, mime_type='image/jpeg'))
        if text_content:
            contents.append(f"\n\n額外文字資訊：{text_content}")

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=contents
        )
        
        text = response.text.strip()
        clean_text = text.replace('```json', '').replace('```', '')
        return json.loads(clean_text)
    except Exception as e:
        st.error(f"AI 辨識失敗: {e}")
        return None

# --- AI 建議引擎 (快取版) ---
@st.cache_data(ttl=3600)  # 快取一小時
def get_overall_advice(cache_key, GOOGLE_API_KEY, df_json):
    """
    使用 Gemini 產生全域飲食與理財建議，快取以減少 API 調用。
    """
    try:
        df = pd.read_json(df_json)
    except Exception:
        df = pd.DataFrame()
        
    if df.empty:
        return {
            "summary": "尚未有記帳資料，開始記錄您的第一筆飲食消費吧！",
            "reason": "當您開始輸入記帳資訊後，AI 會自動分析您的飲食偏好、健康度以及預算使用率，為您量身打造飲食與財務省錢建議。"
        }
        
    # 計算預算統計與消費現狀
    total_spent = pd.to_numeric(df['amount'], errors='coerce').fillna(0).astype(int).sum()
    monthly_budget = st.secrets.get("MONTHLY_BUDGET", 15000)
    budget_usage_pct = (total_spent / monthly_budget) * 100 if monthly_budget > 0 else 0
    
    # 處理時間戳與空值以利 JSON 序列化
    df_recent = df.tail(10).copy()
    for col in df_recent.columns:
        df_recent[col] = df_recent[col].apply(lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else x)
    df_recent = df_recent.where(pd.notnull(df_recent), None)
    recent_records = df_recent.to_dict(orient="records")
    
    category_counts = df['category'].value_counts().to_dict()
    avg_health = pd.to_numeric(df['health_score'], errors='coerce').mean() if 'health_score' in df.columns else 0
    avg_calories = pd.to_numeric(df['calories'], errors='coerce').mean() if 'calories' in df.columns else 0
    
    prompt = f"""
    你是一個精準的飲食記帳與健康理財分析師。
    請分析使用者的餐飲記帳數據，給予一小段精準的【預算與健康雙重建議】，並提供【詳細分析理由】。

    【當前財務/飲食狀態】：
    - 本月總預算：{monthly_budget} 元
    - 本月已花費：{total_spent} 元
    - 預算使用率：{budget_usage_pct:.1f}%
    - 近期平均飲食健康度 (0-10)：{avg_health:.1f} 分
    - 近期平均單餐估算熱量：{avg_calories:.1f} kcal
    - 常用食物分類統計：{category_counts}

    【最近 10 筆明細】：
    {json.dumps(recent_records, ensure_ascii=False, indent=2)}

    【核心任務】：
    1. 產出一句簡短的總結建議 (summary)，長度在 30-50 字之間，必須直接點出財務或飲食的關鍵現狀（例如預算百分比、外食頻率等）。
    2. 產出詳細的理由與具體建議 (reason)，長度在 100-200 字之間，分析分類佔比、熱量與省錢方向。
    
    【回傳格式】：
    必須是「純 JSON」格式，**嚴禁**包含任何 Markdown 標記（如 ```json）、反引號或解釋性文字。
    
    【JSON 格式需求】：
    {{
      "summary": "您的總結建議內容...",
      "reason": "您的詳細理由內容..."
    }}
    """
    
    try:
        advice_client = genai.Client(api_key=GOOGLE_API_KEY)
        response = advice_client.models.generate_content(
            model='gemini-2.5-flash-lite',
            contents=[prompt]
        )
        text = response.text.strip()
        clean_text = text.replace('```json', '').replace('```', '')
        return json.loads(clean_text)
    except Exception as e:
        return {
            "summary": "AI 建議生成暫時不可用，但您可以照常記帳。",
            "reason": f"錯誤原因: {e}"
        }

@st.fragment
def render_ai_advice_section(df_all, google_key):
    """AI 建議片段：讓 AI 運算時不影響主介面輸入"""
    st.markdown("### 💡 AI 飲食與財務建議")
    
    df_json = df_all.to_json(orient="records")
    total_amount_sum = pd.to_numeric(df_all['amount'], errors='coerce').fillna(0).astype(int).sum() if not df_all.empty else 0
    cache_key = f"len_{len(df_all)}_sum_{total_amount_sum}_budget_{MONTHLY_BUDGET}"

    with st.spinner("AI 正在分析您的數據..."):
        ai_advice = get_overall_advice(cache_key, google_key, df_json)

    advice_html = f"""
    <div class="custom-card advice-card">
        <div class="card-header">🤖 AI 智慧理財與飲食建議</div>
        <div class="card-body">
            <div class="advice-text">[AI]: {ai_advice.get('summary', '載入中...')}</div>
        </div>
    </div>
    """
    st.markdown(advice_html, unsafe_allow_html=True)

    if st.checkbox("顯示建議理由", key="show_reason_fragment"):
        st.markdown(f"""
        <div class="reasoning-box">
            💡 <b>詳細理由與分析：</b><br/>
            {ai_advice.get('reason', '無詳細理由說明')}
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
    user_name = st.text_input("使用者名稱", value="hogan", key="user_name")

# --- 主程式執行區 ---

# 1. 讀取資料 (有快取)
df_all = get_expenses()

# 3. 側邊欄導覽與設定
with st.sidebar:
    st.header("🧭 導覽選單")
    # 在這裡定義 menu 變數，修復 NameError
    menu = st.radio("選擇功能", ["📝 快速記帳 & AI建議", "📋 歷史消費紀錄"], index=0)
    st.divider()
    # 呼叫統計片段
    render_sidebar_stats(df_all)

# 4. 全域變數偵測 (供主畫面使用)
ua_string = st_javascript("navigator.userAgent")
is_mobile = any(x in (ua_string or "").lower() for x in ["mobi", "android", "iphone"])
user_name = st.session_state.get("user_name", "hogan")

if menu == "📝 快速記帳 & AI建議":
    # 呼叫 AI 建議片段 (獨立載入)
    render_ai_advice_section(df_all, GOOGLE_API_KEY)
    
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
                uploaded_file = st.camera_input("📷 拍照", label_visibility="collapsed", key="quick_cam")
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
                result = analyze_with_gemini(text_content=text_input, image_content=img_bytes)
                if result:
                    st.session_state.result = result
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
                del st.session_state.result
                st.rerun()

else:
    # --- 4. 歷史消費紀錄 ---
    st.subheader("📋 歷史消費紀錄")
    if not df_all.empty:
        cols_to_show = ["user_name", "date", "foodname", "amount", "category", "calories", "health_score", "advice"]
        df_clean_display = df_all[cols_to_show] if all(col in df_all.columns for col in cols_to_show) else df_all
        st.dataframe(df_clean_display.iloc[::-1], use_container_width=True)
    else:
        st.info("尚無消費紀錄。")
