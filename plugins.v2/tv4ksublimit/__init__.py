import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.event import eventmanager, Event
from app.db.downloadhistory_oper import DownloadHistoryOper
from app.db.subscribe_oper import SubscribeOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType


# 与订阅规则自动填充（subscribegroup）中 __parse_pix 的 4K 分支一致，便于订阅筛选匹配
RESOLUTION_4K_PATTERN = "4K|2160p|x2160"


class Tv4kSubLimit(_PluginBase):
    plugin_name = "电视剧4K订阅锁"
    plugin_desc = (
        "电视剧在下载到 4K/2160p 种子后，将对应订阅的分辨率锁定为 4K，减少后续匹配到非 4K 资源。"
    )
    plugin_icon = "teamwork.png"
    plugin_version = "1.0.0"
    plugin_author = "EkkoG"
    author_url = "https://github.com/EkkoG/MoviePilot-Plugins"
    plugin_config_prefix = "tv4ksublimit_"
    plugin_order = 27
    auth_level = 2

    _enabled: bool = False
    _only_when_empty: bool = False
    _clear_history: bool = False
    _clear_handle: bool = False
    _subscribeoper = None
    _downloadhistoryoper = None

    def init_plugin(self, config: dict = None):
        self._downloadhistoryoper = DownloadHistoryOper()
        self._subscribeoper = SubscribeOper()
        if not config:
            return
        self._enabled = config.get("enabled")
        self._only_when_empty = config.get("only_when_empty")
        self._clear_history = config.get("clear_history")
        self._clear_handle = config.get("clear_handle")

        if self._clear_handle:
            self.del_data(key="history_handle")
            self._clear_handle = False
            self.__persist_config()
            logger.info("电视剧4K锁定：已清空「已处理下载」记录")

        if self._clear_history:
            self.del_data(key="history")
            self._clear_history = False
            self.__persist_config()
            logger.info("电视剧4K锁定：已清空操作历史")

    def __persist_config(self):
        self.update_config({
            "enabled": self._enabled,
            "only_when_empty": self._only_when_empty,
            "clear_history": self._clear_history,
            "clear_handle": self._clear_handle,
        })

    @staticmethod
    def __is_4k(resource_pix: str) -> bool:
        if not resource_pix:
            return False
        return bool(re.search(r"4K|2160p|x2160", str(resource_pix), re.IGNORECASE))

    @staticmethod
    def __season_arg(download_history) -> Optional[int]:
        seasons = download_history.seasons
        if seasons and str(seasons).count("-") == 0:
            try:
                return int(str(seasons).replace("S", "").replace("s", ""))
            except ValueError:
                return None
        return None

    @eventmanager.register(EventType.DownloadAdded)
    def on_download_added(self, event: Event = None):
        if not self._enabled:
            return
        if not event or not event.event_data:
            return
        event_data = event.event_data
        if not event_data.get("hash") or not event_data.get("context"):
            logger.warning(f"电视剧4K锁定：下载事件数据不完整 {event_data}")
            return

        download_hash = event_data.get("hash")
        history_handle: List[str] = self.get_data("history_handle") or []
        if download_hash in history_handle:
            logger.debug(f"电视剧4K锁定：种子 hash {download_hash} 已处理过，跳过")
            return

        download_history = self._downloadhistoryoper.get_by_hash(download_hash)
        if not download_history:
            logger.warning(f"电视剧4K锁定：hash {download_hash} 无下载历史记录")
            return

        if download_history.type != "电视剧":
            return

        context = event_data.get("context")
        meta = context.meta_info if context else None
        resource_pix = meta.resource_pix if meta else None
        if not self.__is_4k(resource_pix):
            return

        season = self.__season_arg(download_history)
        subscribes = self._subscribeoper.list_by_tmdbid(
            tmdbid=download_history.tmdbid,
            season=season,
        )
        if not subscribes:
            logger.info(
                f"电视剧4K锁定：{download_history.title} tmdb={download_history.tmdbid} "
                f"未找到匹配订阅（季参数 {season}）"
            )
            return

        target_resolution = RESOLUTION_4K_PATTERN
        updated_any = False

        for subscribe in subscribes:
            if subscribe.type != "电视剧":
                continue
            if self._only_when_empty and getattr(subscribe, "resolution", None):
                logger.info(
                    f"电视剧4K锁定：订阅「{subscribe.name}」已设置分辨率，跳过（仅空缺时写入已开启）"
                )
                continue
            current = getattr(subscribe, "resolution", None) or ""
            if current == target_resolution:
                logger.debug(f"电视剧4K锁定：订阅「{subscribe.name}」已是 4K 限制，跳过")
                continue

            update_dict = {"resolution": target_resolution}
            self._subscribeoper.update(subscribe.id, update_dict)
            updated_any = True
            logger.info(f"电视剧4K锁定：已将订阅「{subscribe.name}」分辨率设为 {target_resolution}")

            history = self.get_data("history") or []
            history.append({
                "name": subscribe.name,
                "type": "4K 下载后锁定分辨率",
                "content": json.dumps(update_dict, ensure_ascii=False),
                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
            })
            self.save_data(key="history", value=history)

        if updated_any:
            history_handle.append(download_hash)
            self.save_data("history_handle", history_handle)

    def get_state(self) -> bool:
        return bool(self._enabled)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "only_when_empty",
                                            "label": "仅当订阅未设置分辨率时写入",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "clear_handle",
                                            "label": "清空已处理下载记录",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "clear_history",
                                            "label": "清空操作历史",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "监听「下载添加」事件：仅处理电视剧；根据种子元信息识别 4K/2160p；"
                                            "将匹配到的订阅分辨率设为 4K|2160p|x2160（与订阅规则自动填充插件一致）。"
                                            "默认会覆盖已有分辨率；若开启「仅当订阅未设置分辨率时写入」则与旧订阅规则填充行为类似。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "only_when_empty": False,
            "clear_history": False,
            "clear_handle": False,
        }

    def get_page(self) -> List[dict]:
        rows = self.get_data("history")
        if not rows:
            return [
                {
                    "component": "div",
                    "text": "暂无操作记录",
                    "props": {"class": "text-center"},
                }
            ]
        if not isinstance(rows, list):
            rows = [rows]
        rows = sorted(rows, key=lambda x: x.get("time") or "", reverse=True)

        tbody = [
            {
                "component": "tr",
                "props": {"class": "text-sm"},
                "content": [
                    {"component": "td", "props": {"class": "whitespace-nowrap"}, "text": h.get("time")},
                    {"component": "td", "text": h.get("name")},
                    {"component": "td", "text": h.get("type")},
                    {"component": "td", "text": h.get("content") or ""},
                ],
            }
            for h in rows
        ]

        return [
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VTable",
                                "props": {"hover": True},
                                "content": [
                                    {
                                        "component": "thead",
                                        "content": [
                                            {
                                                "component": "th",
                                                "props": {"class": "text-start ps-4"},
                                                "text": "时间",
                                            },
                                            {
                                                "component": "th",
                                                "props": {"class": "text-start ps-4"},
                                                "text": "订阅",
                                            },
                                            {
                                                "component": "th",
                                                "props": {"class": "text-start ps-4"},
                                                "text": "类型",
                                            },
                                            {
                                                "component": "th",
                                                "props": {"class": "text-start ps-4"},
                                                "text": "内容",
                                            },
                                        ],
                                    },
                                    {"component": "tbody", "content": tbody},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]

    def stop_service(self):
        pass
