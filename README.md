# MoviePilot-Plugins

本仓库为 [MoviePilot](https://github.com/jxxghp/MoviePilot) 第三方插件集合（v2 插件目录结构）。

**仓库地址：** [https://github.com/EkkoG/MoviePilot-Plugins](https://github.com/EkkoG/MoviePilot-Plugins)

## 插件列表

| 插件 ID | 说明 |
|---------|------|
| [Tv4kSubLimit](plugins.v2/tv4ksublimit/README.md) | 电视剧订阅画质锁：4K 分辨率 + HDR/DV 特效写入订阅规则 |

各插件的详细说明、安装与配置请查看对应目录内的 `README.md`。

## 仓库结构

```
LICENSE
package.v2.json              # v2 插件市场清单（插件 ID → 版本、说明等）
plugins.v2/
  tv4ksublimit/
    README.md                  # 本插件说明
    __init__.py                # 插件入口
```

## 许可证

本仓库代码以 [MIT License](LICENSE) 授权。MoviePilot 主程序、站点资源与媒体内容仍适用其各自许可与法律法规；使用本仓库插件时请遵守所在站点与版权规定。
