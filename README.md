# Stream Guard

直播画面风险自动遮挡工具。后台截屏 → 视觉风险评分 → 自动切换 OBS 模糊滤镜，画面恢复正常后自动移除遮挡。带图形界面，无需接触代码。

## 功能

- **自动遮挡**：后台持续检测画面，命中风险时自动开启模糊滤镜，画面恢复后自动移除
- **防闪烁**：连续帧确认 + 滞回阈值 + 最短保持时间，避免遮挡来回开关
- **手动控制**：热度切换 / 一键紧急遮挡 / 恢复自动判定，另有界面按钮
- **可视化框选**：拖拽框选游戏画面区域，避免弹幕、网页等干扰检测
- **OBS 集成**：一键创建模糊滤镜、连接测试、自动列出可用捕获源
- **多输出模式**：OBS 滤镜开关 / OBS 场景切换 / 直播伴侣热键模拟 / 干跑模式
- **直播统计**：遮挡次数、累计遮挡时长、最近触发时间
- **配置管理**：图形化编辑、导入导出、诊断报告（密码自动打码）
- **托盘驻留**（Windows）：关闭窗口缩到系统托盘，右键可紧急遮挡或退出

## 快速开始

### macOS

直接下载 Release 中的 `Stream Guard.app`，首次运行需要授权：

1. **屏幕录制权限**：系统设置 → 隐私与安全性 → 屏幕录制 → 勾选 Stream Guard
2. **辅助功能权限**（全局热键）：系统设置 → 隐私与安全性 → 辅助功能 → 勾选 Stream Guard
3. 授权后重启应用

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
│   ├── capture.py            # 截屏（mss / dxcam）
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
