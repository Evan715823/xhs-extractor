# XHS Extractor ✦ 小红书内容提取器

一键提取小红书笔记的原始像素图片和完整文字内容，支持 Grok AI 智能总结。

---

## 一键云端部署（推荐，免费）

用 **Render** 从 GitHub 直接部署，不用买服务器。

### Step 1: 推送到 GitHub

在本项目目录下：
```bash
git init
git add .
git commit -m "init xhs extractor"
```
然后在 GitHub 上创建一个新仓库，按提示推送：
```bash
git remote add origin https://github.com/你的用户名/xhs-extractor.git
git branch -M main
git push -u origin main
```

### Step 2: 部署到 Render

1. 打开 https://render.com 注册（可以直接用 GitHub 账号登录）
2. 点击 **New → Web Service**
3. 连接你的 GitHub 仓库 `xhs-extractor`
4. Render 会自动识别 `render.yaml` 配置
5. 在 **Environment** 里添加环境变量：
   - `LLM_API_KEY` = 你的 Grok API Key（从 https://console.x.ai 获取）
   - `XHS_COOKIE` = （可选）小红书 Cookie
6. 点击 **Deploy**
7. 等待构建完成，Render 会给你一个 `https://xxx.onrender.com` 的地址

**完成！** 浏览器打开那个地址就能用了。

---

## 本地运行

```bash
pip install -r requirements.txt
cp .env.example .env     # 编辑 .env 填入 API Key
python app.py             # 访问 http://localhost:5000
```

## Docker 部署

```bash
cp .env.example .env     # 编辑 .env 填入配置
docker compose up -d
```

---

## 配置说明

| 变量 | 必填 | 说明 |
|------|------|------|
| `LLM_API_KEY` | 是 | Grok API Key，从 https://console.x.ai 获取 |
| `LLM_PROVIDER` | 否 | 默认 `grok`，也支持 `openai` / `anthropic` |
| `LLM_MODEL` | 否 | 默认 `grok-3` |
| `XHS_COOKIE` | 否 | 小红书 Cookie，用于提取需要登录的笔记 |

## 获取小红书 Cookie（可选）

1. 浏览器打开 xiaohongshu.com 并登录
2. F12 → Application → Cookies → xiaohongshu.com
3. 复制所有 Cookie 值填入 `XHS_COOKIE`
