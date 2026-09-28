# 原神 / 云原神剧情对白工具

Windows + Python 3，无需额外库。默认操作：**NPC 交互用 F，选项确认用 F，普通对白用空格，选项位置固定**。

用于原神及云原神对白推进：手动绑定游戏窗口、标定界面图标后，模拟键鼠输入推进对白，并在检测到探索界面恢复时暂停。此项目不需要账号、密码、API Key 或访问令牌，也不读取游戏登录凭据。

## 安装与启动

需要 Windows 和已加入 PATH 的 Python 3。先在终端执行 `python --version` 确认 Python 可用。项目只使用标准库，无需执行 `pip install`。

```powershell
git clone https://github.com/monlight-qq/genshin_story.git
cd genshin_story
python .\auto_story.py --help
python .\auto_story.py --dry-run
```

也可在 GitHub 点击 **Code → Download ZIP**，解压后双击 `启动.cmd`。演练模式仍会注册热键并读取游戏画面，但不发送真实输入。确认绑定与标定正确后，退出演练，再双击启动脚本或运行 `python .\auto_story.py`。

新下载的仓库不包含其他电脑的标定数据，需要按下面的步骤自行标定。

## 操作步骤

1. 按 F9 退出旧脚本，双击 `启动.cmd`，只运行一个实例。
2. 云原神：点击游戏画面，按 **F2** 绑定客户端或浏览器窗口。本地版通常会自动识别。
3. 初次使用先在探索界面暂停，把鼠标放到“探索中固定出现、对白时会消失”的白色 UI 图标上，按 **F4** 标定，再移开鼠标。尺寸和布局不变时，这一步只做一次，不用反复 F5。
4. 可选：出现固定位置的选项时，先 F8 暂停，把鼠标放在目标选项中央，按 **F7** 记录位置。新版默认不再要求选项是白色图标，不做图标边缘校验。位置会保存。
5. 站在 NPC 旁，等游戏显示可按 F 对话的提示后，按 **F8**。脚本先按一次 F，等待进入对白，然后自动连按空格推进、定时按 F 确认选项。若已处于对白中，F8 直接开始推进。
6. 回到探索界面后自动暂停。下一位 NPC 旁再按 F8，无需重新标定。

未记录 F7 时，直接按 F 确认游戏当前选中项；记录后，会先把鼠标移到固定位置再按 F。是否能通过鼠标悬停改变选中项取决于游戏界面。若必须精确点击某一行，可使用 `--option-key mouse`。

## 自动点击 × 关闭按钮

1. 重启新版脚本，云原神先按 F2 绑定。
2. 当**游戏内弹窗的 × 关闭按钮**出现时，保持脚本暂停，将鼠标放在 × 中央，按 **F3** 标定，再移开鼠标。
3. 按 **F8** 开始。以后运行时，会在这个位置附近寻找相同图标，稳定出现后自动点击。检测范围为标定位置附近约 ±32 像素，不会搜索整屏文字中的字母 X。

不同弹窗的 × 如果位置或样式不同，可以暂停后分别 F3 标定；最多保存八个，同位置重新标定会替换旧模板。数据保存在 `story_close.json`，重启或同尺寸 F2 绑定后仍可使用。修改布局/尺寸后需重新标定。

× 的处理优先于 F 和空格：弹窗出现期间不推进对白，点击后留出短暂界面恢复时间。按钮未关闭时最多重试三次，间隔默认 1.5 秒；仍未关闭就暂停并提示检查。手动 F8 暂停、F9 退出或切出游戏都会停止自动关闭。

剧情自动结束后，仍会留 **5 秒**仅检测 ×，处理收尾弹窗；期间不发送 F 或空格。收尾期间按 F8 会立即停止收尾，之后再按 F8 可启动下一段。没有 × 标定或使用 `--no-auto-close` 时不启用收尾检测。自动点击是否能关闭当前云游戏弹窗仍需实测。

默认固定模式是在对白期间每 1.8 秒尝试一次 F 确认，**不识别选项文字或选项是否出现**；普通对白间隔为 0.7 秒。F4 探索检测仍会阻止剧情结束后的持续输入。NPC 交互只按一次 F；8 秒内没观察到探索界面消失并稳定进入对白，就暂停，不会在探索中反复按 F。

## 热键

| 按键 | 功能 |
| --- | --- |
| F2 | 绑定前台云原神窗口并暂停，保留同尺寸标定 |
| F3 | 标定游戏内 × 关闭按钮，可记录多个；需暂停 |
| F4 | 标定探索图标，用于结束检测；需暂停 |
| F5 | 标定对白图标，备用模式使用；需暂停 |
| F6 | 开关自动确认选项 |
| F7 | 默认记录固定选项位置；需暂停 |
| F8 | NPC 旁开始交互 / 对白中开始推进 / 再按暂停 |
| F9 | 退出 |
| F10 | 输出窗口、按键模式、标定匹配及选项目标诊断 |

窗口布局不变时，F4 和可选 F7 只需标定一次。云原神每次重启脚本只需 F2 重新绑定，随后 F8。改变分辨率、全屏状态、浏览器缩放或画面布局后需重新标定；同尺寸但 UI 位置变化也需重标。

这些功能键运行期间会被注册为全局热键，防止浏览器把 F5 当作刷新。退出后恢复。热键冲突时先关闭旧实例；笔记本可能需要 Fn+功能键。

切出游戏会暂停，切回后需 F8。同一个浏览器窗口切标签页或点地址栏不会改变窗口身份，操作前先 F8 暂停。浏览器游戏需先点击画面取得键盘焦点。

## 参数

```powershell
# 默认：固定位置、F 确认、空格推进、NPC 交互 F
python .\auto_story.py

# 演练模式：只显示动作，不发送真实输入
python .\auto_story.py --dry-run

# 固定位置用鼠标点击：先 F7 记录位置
python .\auto_story.py --option-mode fixed --option-key mouse

# 保留旧图标搜索方式：F7 标定重复小图标，点击最上方匹配项
python .\auto_story.py --option-mode detect --option-key mouse

# 关闭 NPC 交互，只在已进入对白后启动
python .\auto_story.py --interact-key none

# 禁用 × 自动点击及收尾检测
python .\auto_story.py --no-auto-close

# 调整 × 匹配阈值和同一按钮重试间隔
python .\auto_story.py --close-threshold 0.92 --close-cooldown 1.5

# 调整对白推进、选项确认间隔和 NPC 等待超时，单位秒
python .\auto_story.py --interval 0.7 --option-interval 1.8 --interaction-timeout 8

# 默认优先使用 F4 探索标记；也可强制该模式
python .\auto_story.py --end-mode gameplay

# 原 F5 白对白图标模式，不稳定的字幕或闪烁图标不适合
python .\auto_story.py --end-mode dialogue --end-delay 3.0
```

`--advance-key` 支持 `space` / `f`，默认 `space`。`--option-key` 支持 `f` / `mouse`，默认 `f`。`--option-mode` 支持 `fixed` / `detect`，默认 `fixed`。从旧图标搜索模式切换到固定模式时会忽略旧选项图标，可以直接 F 确认，也可重新 F7 记录位置。

## 检测与诊断

默认 `--end-mode auto` 有 F4 标定时使用探索 UI 恢复判断结束，因此对白/选项界面变化不再单独导致暂停。仅在探索标记正确匹配时才能识别结束；标记被压缩、遮挡或布局变化时可能漏判，需要稳定图标并先演练。没有 F4 时退回 F5 白对白标记检测，标记消失就停输入，持续消失 2 秒后暂停。固定选项坐标不会被当作对白存在的证据。

按 F10 查看诊断。提示未识别窗口时，云原神先点击画面按 F2。NPC F 后超时，检查是否站在带“对话”交互提示的 NPC 旁；脚本不会走路，也不会识别探索中的交互对象类型。提示未找到白色边缘是 F4/F5 的结束标定问题，默认 F7 固定位置不会要求白色边缘。

日志：`auto_story.log`；结束标定：`story_markers.json`；选项位置或图标：`story_option.json`；关闭按钮：`story_close.json`。旧版本的标定文件仍可读取；退出后删除对应 JSON 可以清除标定。

尚未在当前云游戏画面实测。网络卡顿、截图黑屏、HDR 或悬停高亮可能影响图像检测。脚本不包含跑图、战斗、解谜，也不会跳过游戏不允许跳过的动画。手机不适用。如果目标程序以管理员身份运行，脚本需同等权限。

键鼠模拟使用 Windows [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput) 与 [KEYBDINPUT](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-keybdinput)；空格扫描码为 0x39，F 为 0x21，各保持 80 ms 后释放。画面读取通过 [CreateDIBSection](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createdibsection) 与 [BitBlt](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-bitblt)。

## 开发与测试

在仓库根目录运行回归测试（不发送真实键鼠输入）：

```powershell
python -m unittest discover -s . -p "test_*.py" -v
```

测试使用合成图像、临时标定文件和模拟窗口；Windows 下还验证内存位图的 GDI 截图，不读取桌面。测试通过不代表已完成真实游戏端到端验证。

| 文件 | 职责 |
| --- | --- |
| `auto_story.py` | 命令行入口、Windows 窗口绑定、全局热键、截图和键鼠输入、主循环 |
| `story_guard.py` | 图标匹配、标定数据读写、剧情结束与关闭按钮状态机 |
| `test_story_guard.py` | 图像检测、状态机、绑定与输入保护的回归测试 |
| `启动.cmd` | 切到脚本目录并转发命令行参数的 Windows 启动入口 |

程序启动后默认暂停；F2 绑定窗口，F3/F4/F5/F7 保存相应标定，F8 启动或暂停。主循环先检查窗口和焦点，再处理关闭按钮、剧情结束检测、NPC 交互和对白推进。切出窗口或检测到不适合继续输入的状态时会停止自动输入。

运行日志和 `story_markers.json`、`story_option.json`、`story_close.json` 属于本机数据，已由 `.gitignore` 排除。它们保存在脚本同目录；更新代码时可保留，改变画面布局后应重新标定。
