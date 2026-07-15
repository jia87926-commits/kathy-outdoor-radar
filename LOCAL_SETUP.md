# Kathy Outdoor Radar 本機更新設定

Kathy Outdoor Radar 只在 Kathy 的 Mac 更新，不使用 GitHub Actions 或 GitHub Pages。

## 每日更新條件

- Mac 需要開機，Codex 本機自動化需要可執行。
- Chrome 需要開啟並保持 Instagram 登入狀態。
- 不讀取或輸出 cookie、token、密碼與其他登入資訊。

## 更新流程

1. Codex 使用已登入 Chrome 逐一讀取 IG 帳號頁。
2. 等待貼文格載入，排除帶有「置頂貼文圖示」的項目。
3. 打開最新非置頂照片或 Reel，確認精確日期、原貼文網址與同篇 `og:image`。
4. 產生 `/tmp/Kathy_Outdoor_Radar_candidate.html` 與 `/tmp/Kathy_Outdoor_Radar_candidate.md`。
5. 執行：

   ```bash
   python3 scripts/update_radar_local.py
   ```

6. 腳本通過 IG 圖片修復與驗證後，才覆蓋固定 HTML 與 Markdown。

## 失敗保護

- Chrome 未登入、貼文日期無法確認或候選頁驗證失敗時，不覆蓋正式檔案。
- 失敗的候選頁保留在 `/tmp` 供檢查；成功後自動刪除。
- 腳本偵測到 GitHub Actions 時會直接停止，避免再次產生公開版本。
