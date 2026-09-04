"""Kryon 的更多设置
融合插件：事件倒计时动画开关 + 小组件高度/深度 + 堆叠组件 + 时间组件动画开关。

- 事件倒计时动画开关：给内置 eventCountdown.qml 打可逆补丁，数字滚动动画可开关；
- 小组件高度/深度：给 WidgetsContainer.qml 打补丁，展示高度与隐藏深度可调；
- 堆叠组件：注册 com.overlay 堆叠组件（灵动岛轮播），并恢复"编辑成员组件"入口；
- 时间组件增强：给内置 Time.qml 打可逆补丁，数字滚动动画可开关，并支持
  显示秒/日期/星期/并排或交替布局等丰富显示选项。
"""

from __future__ import annotations

import json
from pathlib import Path

from ClassWidgets.SDK import CW2Plugin, PluginAPI
from loguru import logger
from PySide6.QtCore import Signal, Slot

from integrations import install_all as _install_all, restore_all as _restore_all
from more_settings_config import MoreSettingsConfig
from overlay_backend import OverlayBackend

OLD_COUNTDOWN_KEY = "com.event.countdown.anim"
OLD_HIGH_KEY = "com.kryon.widgets-high"
OLD_COM_HIGH_KEY = "com.high"  # 历史版本高度插件 id


def _app_root() -> Path:
    # <主程序根>/plugins/com.kryon.more_settings/main.py -> 主程序根
    return Path(__file__).resolve().parent.parent.parent


class Plugin(CW2Plugin):
    """Kryon 的更多设置：统一配置 + 主程序补丁 + 堆叠后端。"""

    configChanged = Signal()

    def __init__(self, api: PluginAPI):
        super().__init__(api)
        self._config = MoreSettingsConfig()
        self.overlay = OverlayBackend(self)

    # ── 生命周期 ─────────────────────────────────────────────

    def on_load(self):
        super().on_load()
        try:
            self.api.config.register_plugin_model(self.pid, self._config)
            logger.info("[more_settings] 配置模型注册成功: plugins.configs.{}", self.pid)
        except Exception as e:
            logger.warning("[more_settings] 注册配置模型失败: {}", e)

        self._migrate_old_config()

        # 主程序集成补丁（小组件高度 + 堆叠入口 + 组件动画开关）
        try:
            _install_all(logger)
        except Exception as e:
            logger.warning("[more_settings] 主程序集成安装异常: {}", e)

        # 堆叠组件
        try:
            self.api.widgets.register(
                widget_id="com.overlay",
                name="堆叠 / Stack",
                qml_path="qml/overlay.qml",
                backend_obj=self.overlay,
                settings_qml="qml/overlay-settings.qml",
                default_settings={"interval_ms": 5000},
            )
            logger.info("[more_settings] 堆叠组件注册成功")
        except Exception as e:
            logger.warning("[more_settings] 注册堆叠组件失败: {}", e)

        # 主设置页
        try:
            settings_qml = str(Path(__file__).parent / "qml" / "settings.qml")
            self.api.ui.register_settings_page(
                qml_path=settings_qml,
                title="更多设置",
                icon="ic_fluent_settings_20_regular",
            )
            logger.info("[more_settings] 设置页注册成功")
        except Exception as e:
            logger.warning("[more_settings] 注册设置页失败: {}", e)

    def on_unload(self):
        super().on_unload()
        try:
            _restore_all(logger)
        except Exception as e:
            logger.warning("[more_settings] 主程序集成还原异常: {}", e)
        logger.info("[more_settings] 插件已卸载")

    # ── 设置页槽：动画开关 ───────────────────────────────────

    @Slot(result=bool)
    def getCountdownAnimation(self) -> bool:
        return self._config.countdown_animation

    @Slot(bool)
    def setCountdownAnimation(self, value: bool) -> None:
        self._config.countdown_animation = bool(value)
        self._save_config()

    @Slot(result=bool)
    def getTimeAnimation(self) -> bool:
        return self._config.time_animation

    @Slot(bool)
    def setTimeAnimation(self, value: bool) -> None:
        self._config.time_animation = bool(value)
        self._save_config()

    @Slot(dict)
    def setTimeConfig(self, cfg: dict) -> None:
        """批量写入时间组件显示选项（设置页整体提交）。"""
        if not isinstance(cfg, dict):
            return
        bool_keys = ("time_animation", "time_show_seconds", "time_show_date",
                     "time_show_year", "time_show_month", "time_show_day",
                     "time_show_weekday", "time_alternate_animation")
        for k in bool_keys:
            if k in cfg:
                setattr(self._config, k, bool(cfg[k]))
        if "time_title_mode" in cfg and cfg["time_title_mode"] in ("side_by_side", "alternate"):
            self._config.time_title_mode = str(cfg["time_title_mode"])
        if "time_alternate_interval" in cfg:
            self._config.time_alternate_interval = int(cfg["time_alternate_interval"])
        self._save_config()
        self.configChanged.emit()

    # ── 设置页槽：小组件高度/深度 ─────────────────────────────

    @Slot(result=dict)
    def getConfig(self) -> dict:
        return self._config.model_dump()

    @Slot(float)
    def setDisplayHeight(self, value: float) -> None:
        self._config.display_height = float(value)
        self._save_config()
        self.configChanged.emit()

    @Slot(float)
    def setHideDepth(self, value: float) -> None:
        self._config.hide_depth = float(value)
        self._save_config()
        self.configChanged.emit()

    def _save_config(self) -> None:
        try:
            self.api.config.save()
        except Exception as e:
            logger.warning("[more_settings] 保存配置失败: {}", e)

    # ── 旧配置迁移 ───────────────────────────────────────────

    def _migrate_old_config(self) -> None:
        try:
            cfg_file = _app_root() / "configs" / "configs.json"
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
            old_cfgs = (data.get("plugins", {}) or {}).get("configs", {}) or {}
            changed = False

            # 事件倒计时动画 -> countdown_animation
            old_cd = old_cfgs.get(OLD_COUNTDOWN_KEY)
            if isinstance(old_cd, dict) and self._config.countdown_animation is True \
                    and "animation" in old_cd:
                self._config.countdown_animation = bool(old_cd["animation"])
                changed = True

            # 小组件高度 -> display_height / hide_depth（优先新 key，其次历史 com.high）
            old_high = old_cfgs.get(OLD_HIGH_KEY) or old_cfgs.get(OLD_COM_HIGH_KEY)
            if isinstance(old_high, dict):
                if self._config.display_height == -1 and "display_height" in old_high:
                    self._config.display_height = float(old_high["display_height"])
                    changed = True
                if self._config.hide_depth == 24 and "hide_depth" in old_high:
                    self._config.hide_depth = float(old_high["hide_depth"])
                    changed = True

            if changed:
                self._save_config()
                logger.info("[more_settings] 已迁移旧插件配置 -> {}", self.pid)
        except Exception as e:
            logger.warning("[more_settings] 迁移旧配置失败: {}", e)
