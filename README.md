# Qwen-GIS

> 基于 Qwen 大模型的智能地理空间分析桌面应用
> 版本: 2026.09.03 | Windows 10/11 64位

---

## 一、简介

Qwen-GIS 是一款 Electron 桌面应用，内置 Qwen 大模型对话能力，通过自然语言交互完成地理空间数据分析任务。用户只需输入需求（如"帮我分析这片区域的 NDVI 变化"），AI 即可调用相应工具完成分析。

---

## 二、快速开始

### 运行

将整个文件夹解压到任意位置（如 `D:\Qwen-GIS`），双击 `Qwen GIS.exe` 启动。

> **⚠️ 请勿单独移动或重命名 exe 文件，整个文件夹必须保持完整。**

### 首次配置

1. 启动应用后，在界面内选择模型提供商（DeepSeek / 通义千问 / 智谱等）
2. 填写你的 API Key
3. API Key 仅保存在本机应用数据目录，不会写入安装文件夹

### 系统要求

- Windows 10/11 64位
- 无需额外安装 Python 或其他依赖（已内置完整运行时）

---

## 三、目录结构

```
Qwen-GIS/
├── Qwen GIS.exe              # 主程序入口（Electron）
├── resources/                # 应用资源
│   ├── app.asar              # 前端代码（Electron ASAR 打包）
│   ├── app.asar.unpacked/    # 原生模块（esbuild 等）
│   ├── python-runtime/       # 内置 Python 3.12 完整运行时
│   │   ├── python.exe        # Python 解释器
│   │   ├── Lib/              # 标准库 + 第三方包
│   │   └── Scripts/          # pip 及 CLI 工具入口
│   ├── harness/              # Codex 应用服务
│   │   ├── codex-app-server.exe  # Codex 后端服务
│   │   └── codex-revision.json   # 版本信息
│   ├── preview-tools/        # 预览渲染工具
│   │   ├── render_preview.py         # 渲染引擎
│   │   ├── normalize_spatial_image.py # 空间影像标准化
│   │   ├── preview-dependencies.json  # 依赖清单
│   │   └── vendor/                   # 内置 PIL/Pillow 图像库
│   ├── window-tools/         # 窗口管理工具
│   │   ├── capture-window.ps1    # 窗口截图
│   │   ├── focus-window.ps1      # 窗口聚焦
│   │   └── windows_platform.py   # Windows 平台接口
│   └── platform-tools/      # 平台生命周期管理
│       └── platform-lifecycle.ps1
├── locales/                  # 语言包
│   ├── zh-CN.pak             # 简体中文
│   └── en-US.pak             # 英文
├── LICENSE.electron.txt      # Electron 开源许可
└── README.md                 # 本文件
```

### 运行时文件（根目录）

根目录下的 DLL 和二进制文件均为 Electron/Chromium 运行时所需：

| 文件 | 用途 |
|------|------|
| `chrome_100_percent.pak` / `chrome_200_percent.pak` | Chromium 资源文件 |
| `d3dcompiler_47.dll` / `dxcompiler.dll` / `dxil.dll` | DirectX 着色器编译 |
| `ffmpeg.dll` | 媒体编解码 |
| `icudtl.dat` | Unicode 国际化数据 |
| `libEGL.dll` / `libGLESv2.dll` | OpenGL ES 图形接口 |
| `resources.pak` | Chromium 资源包 |
| `snapshot_blob.bin` / `v8_context_snapshot.bin` | V8 JavaScript 引擎快照 |
| `vk_swiftshader.dll` / `vulkan-1.dll` | Vulkan 图形 API |

---

## 四、本版本说明

### 移除后的影响

- **纯对话功能不受影响** — 模型对话、API 调用、界面交互正常
- **QGIS 集成** — 需要额外安装 QGIS MCP 独立包
- **KNIME 集成** — 需要额外安装 KNIME MCP 独立包
- **地理空间 Skill** — 需要额外安装 Skill 独立包

### 后续扩展包

| 扩展包 | 预计内容 | 状态 |
|--------|----------|------|
| `qgis-mcp-pack.zip` | QGIS MCP Server + 插件 + 安装脚本 + 启动器 | 即将发布 |
| `knime-mcp-pack.zip` | KNIME MCP Bridge + p2 插件 + 安装脚本 | 即将发布 |
| `geospatial-skills.zip` | QGIS 模型构建器 Skill + KNIME 工作流 Skill + CRISP-DM Skill | 即将发布 |

---

## 五、常见问题

### Q: 应用无法启动？
- 确认整个文件夹完整（不要单独移动 exe 文件）
- 检查杀毒软件是否拦截，允许运行即可
- 尝试以管理员身份运行
- 确认系统为 Windows 10/11 64位

### Q: 模型 API 报错？
- 确认 API Key 填写正确
- 确认网络能访问对应模型服务商
- 如使用系统代理（Clash、V2Ray 等），本版本已修复代理劫持本地回环请求的问题

### Q: 为什么没有 QGIS/KNIME 集成功能？
- 本版本为核心精简版，仅包含对话功能
- QGIS/KNIME 的 MCP 集成已拆分为独立扩展包
- 安装扩展包后即可恢复完整的空间分析工作流

### Q: 如何获取扩展包？
- 联系包维护者或关注 GamiGIS 组织仓库更新

---

## 六、技术架构

```
┌─────────────────────────────────────────────┐
│              Qwen-GIS (Electron)             │
│  ┌───────────┐  ┌──────────────────────────┐│
│  │ 前端 UI    │  │   Codex App Server       ││
│  │ (app.asar) │  │   (harness/)             ││
│  └─────┬─────┘  └───────────┬──────────────┘│
│        │                    │                │
│  ┌─────┴────────────────────┴──────────────┐│
│  │        Python 3.12 Runtime              ││
│  │  (python-runtime/)                      ││
│  │  · mcp 协议支持                          ││
│  │  · pydantic 数据验证                     ││
│  │  · fastapi/uvicorn HTTP 服务             ││
│  │  · pillow 图像处理                       ││
│  └─────────────────────────────────────────┘│
└─────────────────────────────────────────────┘
         │                    │
    (扩展包)              (扩展包)
    QGIS MCP              KNIME MCP
```

---

## 七、开发与贡献

- 组织: [GamiGIS](https://github.com/GamiGIS)
- 本仓库: [GamiGIS/Qwen-GIS](https://github.com/GamiGIS/Qwen-GIS)
- 问题反馈: 请在 GitHub Issues 提交

---

> 扩展包获取及其他问题，请联系 GamiGIS 维护者。
