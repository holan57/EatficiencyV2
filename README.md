# 💰 Eatficiency - 飲食記錄家 V2

Eatficiency 是一個基於 **Streamlit** 開發的智慧型飲食記帳與財務管理系統。它結合了 **Google Gemini AI** 的強大辨識能力與 **Google Sheets** 的雲端存儲便利性，旨在幫助使用者同時追蹤日常飲食營養與個人財務支出。

## 🌟 核心功能

### 1. 多使用者管理系統
- 支援多帳號登入與註冊。
- 使用者資料存儲於 `User_Data` 工作表，實現個性化的數據隔離。

### 2. 智慧型快速記帳 (AI OCR & NLP)
- **文字辨識**：使用者可直接輸入「早餐 65 元」等文字，由 AI 解析。
- **影像辨識**：支援上傳收據或食物照片，利用 Gemini 進行影像分析。
- **參考資料對齊**：整合 `Ref_data` 工作表，讓 AI 優先比對常用食物或商家清單，提升辨識精準度。

### 3. 營養與財務分析
- **自動計算**：自動估算食物熱量（Calories）並提供 1-10 分的健康度評分。
- **即時回饋**：提供該次消費的專屬健康建議。

### 4. 個人化 AI 智慧建議
- 根據該使用者的歷史紀錄（`History_record`）進行大數據分析。
- 產出綜合性的「理財建議」與「營養改善方案」，並解釋詳細理由。

### 5. 視覺化預算統計
- **即時統計**：自動計算當月已花費金額。
- **預算追蹤**：視覺化進度條顯示預算剩餘百分比，並在超過 80% 時發出警示。

---

## 🏗️ 系統架構

本程式採用輕量化但功能完整的雲端整合架構：

```text
[ 前端介面 ] (Streamlit)
      |
      +-- [ 佈局與樣式 ] (Custom CSS / Material Icons)
      +-- [ 狀態管理 ] (Session State / Fragments)
      |
[ 邏輯處理 ] (Python)
      |
      +-- [ AI 引擎 ] (Google Gemini 1.5 Flash API)
      |      |-- 消費內容辨識 (JSON Output)
      |      +-- 趨勢分析與建議
      |
[ 資料庫層 ] (Google Sheets via GSheetsConnection)
      |-- User_Data (使用者清單)
      |-- History_record (歷史消費與健康數據)
      +-- Ref_data (辨識參考基準)
```

---

## 🛠️ 技術規格

- **開發語言**：Python 3.10+
- **前端框架**：Streamlit
- **AI 模型**：Google Gemini 1.5 Flash (支援 JSON Mode)
- **資料庫**：Google Sheets (雲端同步)
- **安全性**：使用 `st.secrets` 管理 API Key 與預算門檻。

---

## 📂 檔案結構

- `streamlit_appV2.py`: 主程式邏輯，包含 AI 串接與 Sheets 操作。
- `style.css`: 自定義 UI 樣式，提供簡潔現代的卡片式設計。
- `.streamlit/secrets.toml`: (私密) 儲存 Google API Key 與 Sheets 連線憑證。

---

## 🚀 快速啟動

1. 安裝必要套件：
   ```bash
   pip install streamlit streamlit-gsheets google-genai pandas streamlit-javascript
   ```
2. 設定 `.streamlit/secrets.toml`。
3. 執行程式：
   ```bash
   streamlit run streamlit_appV2.py
   ```