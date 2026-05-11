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

# 与 subscribegroup.__parse_effect 同源；HDR 细分为四档，写入订阅时取下载资源中**最高**一档（DV > HDR10+ > HDR10 > HDR）
EFFECT_PATTERN_DV = "Dolby[\\s.]+Vision|DOVI|[\\s.]+DV[\\s.]+"
EFFECT_PATTERN_HDR10PLUS = "HDR10\\+|HDR10Plus|HDR[\\s.]*10[\\s.]*\\+"
EFFECT_PATTERN_HDR10 = "HDR10(?!\\s*\\+)(?!Plus)"
EFFECT_PATTERN_HDR = "[\\s.]+HDR[\\s.]+|\\bHDR\\b"


class Tv4kSubLimit(_PluginBase):
    plugin_name = "电视剧4K订阅锁"
    plugin_desc = (
        "电视剧在下载到 4K/2160p 种子后，将对应订阅的分辨率锁定为 4K，并在识别到 HDR/DV 时"
        "按 DV > HDR10+ > HDR10 > HDR 优先级锁定特效（与订阅规则自动填充的特效正则风格一致）。"
    )
    plugin_icon = "teamwork.png"
    plugin_version = "1.1.0"
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
    def __parse_pix(resource_pix: str) -> Optional[str]:
        """
        与 subscribegroup.__parse_pix 一致：将原始分辨率元信息规范为订阅用正则串。
        """
        if not resource_pix:
            return None
        s = str(resource_pix)
        if re.match(r"1080[pi]|x1080", s, re.IGNORECASE):
            return "1080[pi]|x1080"
        if re.match(r"4K|2160p|x2160", s, re.IGNORECASE):
            return RESOLUTION_4K_PATTERN
        if re.match(r"720[pi]|x720", s, re.IGNORECASE):
            return "720[pi]|x720"
        return s

    @staticmethod
    def __effect_pattern_from_meta(resource_effect: Optional[str]) -> Optional[str]:
        """
        按 DV > HDR10+ > HDR10 > HDR 从元信息中择一；无匹配则不改订阅特效。
        使用 re.search（整条标题/特效串任意位置），避免 subscribegroup 内 re.match 仅从串首匹配的问题。
        """
        if not resource_effect:
            return None
        s = str(resource_effect)
        if re.search(
            r"Dolby[\s.]+Vision|DOVI|[\s.\[\(-]DV[\s.\]\)-]|(?<![A-Za-z0-9])DV(?![A-Za-z0-9])",
            s,
            re.IGNORECASE,
        ):
            return EFFECT_PATTERN_DV
        if re.search(r"HDR10\+|HDR10Plus|HDR[\s.]*10[\s.]*\+", s, re.IGNORECASE):
            return EFFECT_PATTERN_HDR10PLUS
        if re.search(r"HDR10(?!\s*\+)(?!Plus)", s, re.IGNORECASE):
            return EFFECT_PATTERN_HDR10
        if re.search(r"[\s.]+HDR[\s.]+|\bHDR\b", s, re.IGNORECASE):
            return EFFECT_PATTERN_HDR
        return None

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

        resource_effect = meta.resource_effect if meta else None
        target_effect = self.__effect_pattern_from_meta(resource_effect)

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

        parsed_res = self.__parse_pix(resource_pix)
        target_resolution = (
            RESOLUTION_4K_PATTERN
            if parsed_res == RESOLUTION_4K_PATTERN or self.__is_4k(resource_pix)
            else (parsed_res or RESOLUTION_4K_PATTERN)
        )
        updated_any = False

        for subscribe in subscribes:
            if subscribe.type != "电视剧":
                continue
            update_dict: Dict[str, Any] = {}

            if not (self._only_when_empty and getattr(subscribe, "resolution", None)):
                current_res = getattr(subscribe, "resolution", None) or ""
                if current_res != target_resolution:
                    update_dict["resolution"] = target_resolution
            else:
                logger.info(
                    f"电视剧4K锁定：订阅「{subscribe.name}」已设置分辨率，跳过分辨率（仅空缺时写入已开启）"
                )

            if target_effect:
                if not (self._only_when_empty and getattr(subscribe, "effect", None)):
                    current_fx = getattr(subscribe, "effect", None) or ""
                    if current_fx != target_effect:
                        update_dict["effect"] = target_effect
                else:
                    logger.info(
                        f"电视剧4K锁定：订阅「{subscribe.name}」已设置特效，跳过特效（仅空缺时写入已开启）"
                    )

            if not update_dict:
                logger.debug(f"电视剧4K锁定：订阅「{subscribe.name}」无需更新（已与目标一致或受选项跳过）")
                continue

            self._subscribeoper.update(subscribe.id, update_dict)
            updated_any = True
            parts = []
            if "resolution" in update_dict:
                parts.append(f"分辨率={update_dict['resolution']}")
            if "effect" in update_dict:
                parts.append(f"特效={update_dict['effect']}")
            logger.info(f"电视剧4K锁定：已将订阅「{subscribe.name}」更新：{', '.join(parts)}")

            history = self.get_data("history") or []
            history.append({
                "name": subscribe.name,
                "type": "4K 下载后锁定分辨率/特效",
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
                                            "将订阅分辨率规范为与 SubscribeGroup 相同的正则（4K|2160p|x2160）。"
                                            "若元信息含 HDR/DV，则按 DV > HDR10+ > HDR10 > HDR 优先级写入订阅「特效」正则。"
                                            "默认会覆盖已有分辨率/特效；「仅当订阅未设置分辨率时写入」对分辨率与特效分别生效。",
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
