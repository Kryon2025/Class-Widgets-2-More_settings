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
import re
from pathlib import Path

from ClassWidgets.SDK import CW2Plugin, PluginAPI
from loguru import logger
from PySide6.QtCore import QTimer, Signal, Slot

from integrations import install_all as _install_all, restore_all as _restore_all, find_app_root as _find_app_root
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
                default_settings={"interval_ms": 5000, "lyric_gate": False},
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

        # 官方"在课堂中隐藏"的特定课程不隐藏（参考一代 excluded_lessons）
        try:
            self.api.runtime.statusChanged.connect(self._on_status_changed)
            logger.info("[more_settings] 已连接日程状态信号")
        except Exception as e:
            logger.warning("[more_settings] 连接日程状态信号失败: {}", e)

    def on_unload(self):
        super().on_unload()
        try:
            self.api.runtime.statusChanged.disconnect(self._on_status_changed)
        except Exception:
            pass
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

    # ── 特定课程不隐藏（官方"在课堂中隐藏"的排除）──────────────

    @Slot(result=dict)
    def getExcludedLessonConfig(self) -> dict:
        try:
            subjects = json.loads(self._config.hide_excluded_subjects or "[]")
            if not isinstance(subjects, list):
                subjects = []
        except Exception:
            subjects = []
        return {
            "enabled": self._config.hide_excluded_enabled,
            "subjects": [str(s) for s in subjects],
        }

    @Slot(bool, list)
    def setExcludedLessonConfig(self, enabled: bool, subjects: list) -> None:
        clean = []
        for s in (subjects or []):
            s = str(s).strip()
            if s and s not in clean:
                clean.append(s)
        self._config.hide_excluded_enabled = bool(enabled)
        self._config.hide_excluded_subjects = json.dumps(clean, ensure_ascii=False)
        self._save_config()
        self.configChanged.emit()

    # ── 主程序补丁注入（自动 + 手动重试）──────────────────────

    @Slot(result=bool)
    def reinstallPatches(self) -> bool:
        """手动重新注入全部主程序补丁（幂等）。"""
        try:
            return _install_all(logger)
        except Exception as e:
            logger.warning("[more_settings] 重新注入补丁失败: {}", e)
            return False

    @Slot(result=str)
    def getPatchStatus(self) -> str:
        """返回补丁注入状态（供设置页显示）。"""
        root = _find_app_root()
        if root is None:
            return "未找到主程序目录"
        root = Path(root)
        checks = [
            (root / "src" / "qml" / "ClassWidgets" / "Components" / "WidgetsContainer.qml",
             "overlayEditingId"),
            (root / "src" / "qml" / "ClassWidgets" / "Components" / "WidgetLoader.qml",
             "overlayListMode"),
            (root / "src" / "qml" / "widgets" / "eventCountdown.qml",
             "[patched by com.kryon.more_settings"),
            (root / "src" / "qml" / "widgets" / "Time.qml",
             "[patched by com.kryon.more_settings"),
            (root / "src" / "qml" / "ClassWidgets" / "Components" / "dialogs" / "AddOverlayMemberDialog.qml",
             None),
        ]
        missing = []
        for p, mark in checks:
            if not p.is_file():
                missing.append(p.name)
            elif mark is not None and mark not in p.read_text(encoding="utf-8", errors="ignore"):
                missing.append(p.name)
        return "已注入" if not missing else ("未注入: " + ", ".join(missing))

    def _on_status_changed(self, status: str) -> None:
        """官方 AutoHideTask 会随日程状态隐藏/显示小组件；
        延迟到事件循环下一轮执行，确保在官方处理完之后再纠正。"""
        QTimer.singleShot(0, lambda: self._apply_excluded_lesson(status))

    def _apply_excluded_lesson(self, status: str) -> None:
        """仅在主程序"在课堂中隐藏"时生效：按当前课表科目（而非课程标题）判定。"""
        try:
            if not self._config.hide_excluded_enabled:
                return
            if status not in ("class", "activity"):
                return
            subject = (getattr(self.api.runtime, "current_subject", "") or "").strip()
            if not subject:
                return
            try:
                subjects = json.loads(self._config.hide_excluded_subjects or "[]")
            except Exception:
                subjects = []
            if not isinstance(subjects, list) or subject not in subjects:
                return
            # 仅纠正官方"在课堂中隐藏"（auto hide）的效果
            configs = self.api.globalconfig.configs
            action = str(configs.interactions.hide.action)
            if action == "mini_mode":
                configs.preferences.mini_mode = False
            else:
                configs.interactions.hide.state = False
            logger.info("[more_settings] 特定科目不隐藏已生效: {}", subject)
        except Exception as e:
            logger.warning("[more_settings] 特定科目不隐藏处理失败: {}", e)

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
