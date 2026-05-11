# 电视剧订阅画质锁（`Tv4kSubLimit`）

当**电视剧**任务通过订阅/搜索等方式加入下载，且种子元信息中的分辨率为 **4K / 2160p** 时，自动将对应**电视剧订阅**的「分辨率」设为 `4K|2160p|x2160`（与社区插件「订阅规则自动填充」中 4K 分支一致，便于与主程序筛选规则对齐），减少后续继续匹配到 1080p 等非 4K 资源的情况。若 `context.meta_info.resource_effect` 中能识别 **DV / HDR10+ / HDR10 / HDR**，会按 **DV > HDR10+ > HDR10 > HDR** 优先级写入订阅「特效」正则（与前端/SubscribeGroup 风格可对照；HDR 细档与官方 UI 合并项不完全相同）。

- **事件**：`DownloadAdded`（下载添加）
- **匹配订阅**：按下载历史的 TMDB ID 与季信息调用 `list_by_tmdbid`（季号解析逻辑与「订阅规则自动填充」相同）
- **去重**：同一下载任务 `hash` 只处理一次，避免重复写库

**注意**：是否判定为 4K 依赖 `context.meta_info.resource_pix`。特效依赖 `resource_effect`；若站点解析不到对应字段，插件不会写入该项。

## 安装

1. 在 MoviePilot **设置 → 插件 → 插件市场** 中，将插件仓库地址设为  
   [https://github.com/EkkoG/MoviePilot-Plugins](https://github.com/EkkoG/MoviePilot-Plugins)  
   （需可访问的 Git 地址，具体以 MoviePilot 版本说明为准。）
2. 在市场列表中找到 **电视剧订阅画质锁**（或插件 ID：`Tv4kSubLimit`），安装并启用。
3. 在插件页打开 **启用**；按需调整「仅当订阅未设置分辨率时写入」等选项。

若手动部署：将本目录 `tv4ksublimit` 复制到 MoviePilot 对应 `plugins.v2` 下，并确保仓库根目录 **`package.v2.json`** 中已登记该插件（合并到主市场仓库时需把 `Tv4kSubLimit` 条目并入总 `package.v2.json`）。

## 配置说明

| 选项 | 说明 |
|------|------|
| 启用 | 关闭时不监听下载事件 |
| 仅当订阅未设置分辨率时写入 | 关闭（默认）：分辨率与特效（若有识别结果）均可覆盖写入；开启：仅当订阅**该项**为空时才写入（分辨率与特效分别判断） |
| 清空已处理下载记录 | 保存配置时执行一次，用于让已处理过的 `hash` 可再次触发（一般排错用） |
| 清空操作历史 | 保存配置时清空插件页「操作历史」列表 |

## 与其它插件

与 **订阅规则自动填充（SubscribeGroup）** 同属下载后改订阅逻辑；本插件 `plugin_order = 27`，默认在常见 `subscribegroup`（26）之后执行。若同时启用多个改订阅插件，请结合实际效果调整顺序或选项。

## 文件

- `__init__.py`：插件入口
