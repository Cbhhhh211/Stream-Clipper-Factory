# Stream Clipper 上线指南

## 推荐方案

现在这套项目最适合走 `单容器官网 + API + 桌面版下载` 的路线。

原因：

- 官网和 API 已经合并到同一个 FastAPI 服务里。
- 根路径会显示营销官网。
- `/studio` 会进入原来的工作台。
- 你只需要部署一个 Docker 服务，就能先开始收线索和接单。

## 生产部署

### 1. 构建镜像

```bash
docker build -t stream-clipper .
```

### 2. 启动服务

```bash
docker run -p 8000:8000 --env-file .env stream-clipper
```

说明：

- 容器启动时会运行 `uvicorn services.api.main:app`
- 前端静态文件已经在 Docker 构建阶段打包进镜像
- 访问 `http://localhost:8000/` 就是官网
- 访问 `http://localhost:8000/studio` 就是工作台

## 建议部署平台

适合支持 Docker Web Service 的平台，例如：

- Render
- Railway
- Fly.io

这些平台都可以直接吃根目录的 `Dockerfile`。
如果你打算用 Render，仓库里已经补了一个基础版 `render.yaml`。

## 必填环境变量

至少建议配置：

- `CORS_ORIGINS=https://你的域名`
- `PUBLIC_LEADS_PATH=./output/_public/leads.jsonl`
- `PUBLIC_SITE_BRAND=Stream Clipper`
- `PUBLIC_CONTACT_EMAIL=你的联系邮箱`
- `PUBLIC_BOOKING_URL=你的演示预约链接`
- `PUBLIC_DOWNLOAD_URL=你的桌面版下载链接`
- `PUBLIC_DEMO_URL=/studio`
- `PUBLIC_PRICE_CREATOR_URL=你的基础版支付链接`
- `PUBLIC_PRICE_STUDIO_URL=你的工作室版支付链接`
- `PUBLIC_PRICE_TEAM_URL=你的企业咨询链接`

可选：

- `PUBLIC_HERO_BADGE`
- `PUBLIC_HERO_HEADLINE`
- `PUBLIC_HERO_SUBHEADLINE`
- `PUBLIC_PRICE_CREATOR_BULLETS`
- `PUBLIC_PRICE_STUDIO_BULLETS`
- `PUBLIC_PRICE_TEAM_BULLETS`

说明：

- 官网内容现在由 API 在运行时返回。
- 以后改价格、改下载地址、改预约链接，不需要重新打前端包。

## 安装包发布

建议优先发这个文件：

- `desktop/release/Stream-Clipper-Desktop-Portable-Standalone.zip`

建议上传到：

- GitHub Releases
- 阿里云 OSS / 腾讯云 COS
- Cloudflare R2
- 你自己的下载页

上传后，把链接填到：

- `PUBLIC_DOWNLOAD_URL`

## 支付接法

页面里的购买按钮是通用跳转，不绑定某一家支付平台。

你可以接：

- Stripe Payment Links
- Creem
- Gumroad
- 爱发电
- 自己的微信收款/预约页

对应变量：

- `PUBLIC_PRICE_CREATOR_URL`
- `PUBLIC_PRICE_STUDIO_URL`
- `PUBLIC_PRICE_TEAM_URL`

## 线索数据

官网表单提交后默认写到：

- `output/_public/leads.jsonl`

每条线索会带上：

- 姓名
- 邮箱
- 身份
- 平台
- 目标
- 预算
- 备注
- 来源
- IP / User-Agent / Referer

## 上线当天检查

- 官网首页可访问
- `/studio` 可访问
- 线索表单能提交
- 支付按钮能跳转
- 下载按钮能跳转
- 联系邮箱正确
- 预约链接正确
- 至少准备 3 条演示内容和 1 条真实案例
