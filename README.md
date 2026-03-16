# Stream Clipper

面向内容创作者的本地 AI 高光剪辑工具。  
支持导入本地视频或链接源，自动完成转写、打分、候选片段生成，并在 Web 端完成复核与导出。

## 核心能力

- 多源导入：`local` / `bili_vod` / `bili_live` / `web_vod` / `web_live`
- ASR 转写：Whisper（`faster-whisper`）
- 片段打分：弹幕/语义/音频等多信号融合
- 复核工作流：片段列表 + 预览 + 时间轴微调
- 导出能力：批量导出已选片段
- 两种 API 模式：
  - `lite`：本地单机模式（无 Redis/Postgres/S3）
  - `full`：服务化模式（队列、数据库、对象存储）

## 仓库结构（GitHub 建议保留）

- `frontend/`：React 前端
- `services/`：FastAPI 服务层（路由、worker、队列、存储接口）
- `stream_clipper/`：核心算法/管线/剪辑逻辑
- `tools/`：训练/评估/辅助脚本
- `tests/`：测试用例
- `app.py`：本地一键入口（启动前后端）
- `.env.example`：环境变量模板
- `requirements.txt` / `requirements-dev.txt`：Python 依赖
- `docker-compose.yml`、`Dockerfile*`：容器部署文件

## 快速启动（本地开发）

```bash
python app.py
```

默认地址：
- API: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5173`

## 测试

```bash
pip install -r requirements-dev.txt
pytest -q
```

## 说明

这个仓库是“源码运行版”，不包含桌面安装/打包目录（`desktop/`）。

## 反馈训练相关

- 反馈日志默认路径：
  - `output/_api_jobs/_feedback/clip_feedback.jsonl`
- 训练轻量排序模型：

```bash
python tools/train_feedback_ranker.py
```

## 发布到 GitHub 的建议

1. 提交源码与配置模板（不要提交真实密钥）。
2. 不提交运行产物与缓存（`output/`、`release/`、`node_modules/` 等）。
3. 仅提交 `.env.example`，不要提交 `.env`。

---
