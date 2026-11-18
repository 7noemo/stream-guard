# Stream Guard

直播画面风险自动遮挡工具。后台采集画面 → 视觉风险评分 → 自动切换 OBS 模糊滤镜，画面恢复正常后自动移除遮挡。带图形界面，无需接触代码。

## 功能

- **自动遮挡**：后台持续检测画面，命中风险时自动开启模糊滤镜，画面恢复后自动移除
- **多种画面来源**：OBS 节目场景（推荐）/ OBS 指定源 / 窗口跟踪 / 屏幕区域，界面下拉框切换
- **防闪烁**：连续帧确认 + 滞回阈值 + 最短保持时间，避免遮挡来回开关
- **手动控制**：热键切换 / 一键紧急遮挡 / 恢复自动判定，另有界面按钮
- **OBS 集成**：一键创建模糊滤镜、连接测试、自动列出可用场景与源
- **多输出模式**：OBS 滤镜开关 / OBS 场景切换 / 直播伴侣热键模拟 / 干跑模式
- **直播统计**：遮挡次数、累计遮挡时长、最近触发时间
- **配置管理**：图形化编辑、导入导出、诊断报告（密码自动打码）
- **托盘驻留**（Windows）：关闭窗口缩到系统托盘，右键可紧急遮挡或退出

## 画面来源（重要）

界面「画面来源」下拉框决定检测哪一路画面：

| 来源 | 说明 | 适用场景 |
|------|------|----------|
| `obs_scene`（默认，推荐） | 通过 OBS WebSocket 取当前节目场景的最终合成画面，含所有滤镜与叠加层 | 用 OBS 直播，检测内容 = 观众所见，不受弹窗/切窗口/最小化影响 |
| `obs_source` | 取 OBS 中某个指定源（如游戏捕获）的画面 | 只想检测游戏画面本身 |
| `window` | 按窗口标题跟踪其屏幕矩形抓屏 | 无 OBS、需锁定某个窗口；DX 全屏游戏请用无边框窗口模式 |
| `screen` | 抓整屏或框选区域（mss / dxcam） | 直播伴侣等无 API 的软件 |

为什么推荐 `obs_scene`：它检测的就是推流出去的那一帧，和平台审核看到的内容一致；而且不依赖屏幕可见性——你切出去看弹幕、窗口被挡住、甚至最小化 OBS，检测照常进行。前提是 OBS 已开启 WebSocket 服务。

## 快速开始

### macOS

直接下载 Release 中的 dmg，安装后首次运行按需授权：

1. **辅助功能权限**（全局热键）：系统设置 → 隐私与安全性 → 辅助功能 → 勾选 Stream Guard
2. **屏幕录制权限**（仅当选 `screen` / `window` 画面来源时需要）：同页 → 屏幕录制 → 勾选 Stream Guard
3. 授权后重启应用

使用默认的 `obs_scene` 来源时**不需要**屏幕录制权限，画面直接来自 OBS。

从源码运行：

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

打包 macOS 应用：

```bash
python3 -m pip install pyinstaller
python3 -m PyInstaller stream-guard-mac.spec --noconfirm --clean
# 产物: dist/Stream Guard.app
```

> macOS 版不启用系统托盘，关闭窗口即退出。全局热键依赖辅助功能权限，未授权时请用界面按钮。

### Windows

**方式 A · 本地构建**

1. 安装 Python 3.11 64 位
2. 把整个项目文件夹复制到 Windows
3. 双击 `build.bat`，等待依赖安装和打包完成
4. 产物为 `dist\StreamGuard.exe`，把 `config.json` 放在 exe 同目录

**方式 B · GitHub Actions**

把代码推到仓库，在 Actions 页手动触发 `Build Stream Guard Windows EXE`，完成后从 Artifacts 下载。

**开发模式运行**：双击 `run.bat`。

## OBS 配置

1. OBS → 工具 → WebSocket 服务器设置 → 启用，设置端口（默认 4455）和密码
2. 在界面「输出与热键」区填入地址、端口、密码
3. 填好捕获源名称（可点「测试连接」查看可用源列表）
4. 点「一键创建模糊滤镜」，自动在 OBS 中建好名为 `StreamGuard_Blur` 的模糊滤镜并设为禁用
5. 输出方式保持 `obs_filter`，点「开始监控」

也可以用 `obs_scene` 模式：提前准备一个全屏遮挡场景，在配置里填正常场景和遮挡场景名。

直播伴侣没有开放 API，用 `companion` 模式：在伴侣里把遮挡素材的显示/隐藏绑定到 F9/F10，程序通过模拟按键控制。

## 检测后端

| 后端 | 依赖 | 说明 |
|------|------|------|
| `heuristic` | 无 | 肤色比例启发式，开箱即用，**误报率高**，仅建议演示 |
| `mock` | 无 | 按预设分数循环，仅用于测试流程和状态机 |
| `opennsfw2` | `pip install opennsfw2` | 本地 NSFW 模型，对写实内容较准，对 3D 游戏角色误报偏高 |
| `clip` | `pip install torch transformers` | 零样本分类，可通过提示词适配游戏画面，体积大 |

正式使用前建议用真实游戏画面样本校准阈值：

```bash
# 样本文件名以 pos_ 开头视为风险样本，neg_ 开头为安全样本
python3 tools/calibrate.py ./samples
```

工具会输出分数分布和建议阈值。

## 热键

| 按键 | 功能 |
|------|------|
| F9 | 手动切换遮挡状态 |
| F10 | 紧急强制遮挡 |
| F11 | 恢复自动判定 |

按键可在界面中修改。macOS 上全局热键需要辅助功能权限。

## 主要参数

- **触发阈值 / 解除阈值**：风险分的门限，解除阈值应低于触发阈值（滞回）
- **连续命中 / 解除帧数**：连续多少帧满足条件才切换状态
- **最短保持时间**：遮挡后至少保持多少秒才允许解除
- **检测帧率**：每秒检测次数，越高反应越快、CPU 占用越大
- **抓屏后端**：Windows 全屏独占游戏下优先用 `dxcam`（DXGI），`mss` 作为兜底；建议游戏设为无边框窗口模式

## 项目结构

```
stream-guard/
├── app.py                    # GUI 入口
├── main.py                   # CLI 入口
├── config.json               # 默认配置
├── guard/
│   ├── capture.py            # 画面来源（OBS场景/OBS源/窗口/屏幕）
│   ├── detector.py           # 检测后端
│   ├── engine.py             # 后台检测引擎
│   ├── gui.py                # tkinter 界面
│   ├── hotkeys.py            # 全局热键
│   ├── output.py             # OBS / 直播伴侣输出控制
│   ├── state.py              # 滞回状态机
│   └── stats.py              # 遮挡统计
├── tools/
│   ├── calibrate.py          # 阈值校准
│   └── region_picker.py      # 可视化区域选择
├── build.bat                 # Windows 一键打包
├── run.bat                   # Windows 开发模式运行
├── stream-guard.spec         # Windows PyInstaller 配置
├── stream-guard-mac.spec     # macOS PyInstaller 配置
└── .github/workflows/        # Windows 自动构建
```

## 注意事项

- 这是辅助工具，不是保险。模型误判可能导致该遮的没遮、不该遮的狂遮，关键场景仍需人工值守。
- 技术处理不能解决「平台是否允许直播该游戏」的政策问题，开播前请确认平台规则。
- macOS 打包应用未签名，首次打开可能需要右键 → 打开，或在系统设置中允许。
