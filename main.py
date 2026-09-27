"""Kryon 的扩展设置
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
from PySide6.QtCore import Property, QTimer, Signal, Slot

from integrations import restore_all as _restore_all, find_app_root as _find_app_root
from installer_backend import InstallerBackend
from more_settings_config import MoreSettingsConfig
from payload_host import activate_payload, load_payload

OLD_COUNTDOWN_KEY = "com.event.countdown.anim"
OLD_HIGH_KEY = "com.kryon.widgets-high"
OLD_COM_HIGH_KEY = "com.high"  # 历史版本高度插件 id


_PLUGIN_DIR = Path(__file__).resolve().parent


def _app_root() -> Path:
    # <主程序根>/plugins/com.kryon.more_settings/main.py -> 主程序根
    return _PLUGIN_DIR.parent.parent


def _plugin_id() -> str:
    """本插件的 id。

    对齐主程序自带插件（com.weather / com.daily.quote）的做法：从 __file__ 推导，
    不依赖 SDK 的属性。**这里曾经用 self.pid**，而 __init__ 阶段 SDK 还没给它赋值
    （它是 None），于是 `Path / None` 抛 TypeError，整个安装器后端构造失败 ——
    表现就是界面读不到主程序版本、一个功能也列不出来。
    """
    try:
        mf = _PLUGIN_DIR / "cwplugin.json"
        v = json.loads(mf.read_text(encoding="utf-8")).get("id")
        if v:
            return str(v)
    except Exception:
        pass
    return _PLUGIN_DIR.name


class Plugin(CW2Plugin):
    """Kryon 的扩展设置：统一配置 + 主程序补丁 + 堆叠后端。"""

    configChanged = Signal()
    installerChanged = Signal()
    # 功能装/卸的结果（id, 名称, 是否成功, 说明）。
    # 安装器自己的 staged / uninstalled 只用于内部收尾，没有转发给 QML，
    # 所以界面拿不到「到底成没成」—— 这个信号就是给它用的。
    featureResult = Signal(str, str, bool, str)

    def __init__(self, api: PluginAPI):
        super().__init__(api)
        self._config = MoreSettingsConfig()
        # 功能安装器：数据目录放主程序的插件配置目录下，
        # 这样重装 / 升级本插件不会把已下载的功能一起清掉。
        try:
            self.installer = InstallerBackend(
                self, _app_root() / "configs" / "plugins" / _plugin_id())
            self.installer.stateChanged.connect(self.installerChanged)
        except Exception as e:
            logger.warning("[more_settings] 安装器后端初始化失败: {}", e)
            self.installer = None
        # 已加载的功能 payload：[(host, module)]，卸载时按逆序回调
        self._payloads = []

    # ── 生命周期 ─────────────────────────────────────────────

    # ── 功能安装器（供设置页调用）────────────────────────────
    # 设置页通过 backend.xxx 访问这些；后端可能初始化失败，所以处处判空。

    def _inst(self):
        return getattr(self, "installer", None)

    def _get_installer_version(self):
        i = self._inst()
        return i.installerVersion if i else ""

    def _get_cw2_version(self):
        i = self._inst()
        return i.cw2Version if i else ""

    def _get_installer_state(self):
        i = self._inst()
        return i.state if i else "error"

    def _get_installer_busy(self):
        i = self._inst()
        return bool(i.busy) if i else False

    def _get_installer_log(self):
        i = self._inst()
        return i.logText if i else ""

    def _get_feature_list(self):
        i = self._inst()
        if not i:
            return []
        out = []
        for f in i.features:
            d = dict(f)
            # 每个功能「所需的补丁是否真的进了主程序」。界面据此逐项显示。
            # 单独算而不是塞进安装器后端：补丁清单的单一真相在 integrations.py，
            # 后端不该再复制一份。
            d["patches"] = self._patch_status(str(d.get("id", "")))
            out.append(d)
        return out

    installerVersion = Property(str, _get_installer_version, notify=installerChanged)
    cw2Version = Property(str, _get_cw2_version, notify=installerChanged)
    installerState = Property(str, _get_installer_state, notify=installerChanged)
    installerBusy = Property(bool, _get_installer_busy, notify=installerChanged)
    installerLog = Property(str, _get_installer_log, notify=installerChanged)
    featureList = Property("QVariantList", _get_feature_list, notify=installerChanged)

    @Slot()
    def refreshInstaller(self):
        i = self._inst()
        if i:
            i.refresh()

    @Slot(str, str)
    def installFeature(self, feature_id: str, version: str = ""):
        i = self._inst()
        if i:
            i.install(feature_id, version)

    @Slot(str)
    def uninstallFeature(self, feature_id: str):
        i = self._inst()
        if i:
            i.uninstall(feature_id)

    @Slot(str, bool)
    def setFeatureEnabled(self, feature_id: str, on: bool):
        i = self._inst()
        if i:
            i.setEnabled(feature_id, on)

    @Slot(result=bool)
    def takeInstallerWarning(self):
        """取一次「装了未测试功能」的提示标记，取出即清（只提示一次）。"""
        i = self._inst()
        return bool(i.takePendingWarning()) if i else False

    @Slot(str, result=str)
    def featureSettingsUrl(self, feature_id: str) -> str:
        """功能自己设置页的 file:// 地址；没有就返回空串。"""
        i = self._inst()
        if not i:
            return ""
        try:
            d = i.featureDirOf(feature_id)
            if not d:
                return ""
            p = Path(d) / "settings.qml"
            return p.as_uri() if p.is_file() else ""
        except Exception:
            return ""

    @Slot(str)
    def importPayloadFile(self, source: str):
        """手动导入一个 payload 文件。

        为的是两条现实情况：清单拉不到时还能离线装；
        以及用户拿到了别人分享的包。文件与 https 地址都接受。
        """
        i = self._inst()
        if i:
            i.importPayload(source)

    # ── 功能 payload 的加载 / 卸载 ────────────────────────────

    def _payload_index(self) -> dict:
        """已启用功能的目录与元数据，附带「目录是否真的存在」。

        「谁提供堆叠组件」和「加载哪些 payload」都从这里取，
        避免两处各算一遍、结果还不一致。
        """
        i = self._inst()
        if not i:
            return {}
        out = {}
        try:
            for item in i.enabledPayloads():
                try:
                    out[str(item["id"])] = {
                        "dir": str(item.get("dir") or ""),
                        "exists": bool(item.get("exists")),
                        "meta": item.get("meta") or {},
                    }
                except Exception:
                    continue
        except Exception as e:
            logger.warning("[more_settings] 读取已启用功能失败: {}", e)
        return out

    def _boot_payloads(self):
        """加载所有已启用功能的 payload。

        顺序是「内置补丁先、payload 后」。两者共用同一套补丁锚点与同一个备份
        命名空间，所以重复应用是幂等的 —— payload 的意义是让某个功能能独立
        更新，而不是替掉内置实现。
        """
        self._payloads = []
        for fid, info in self._payload_index().items():
            if not info["exists"]:
                logger.warning("[more_settings] 功能 {} 标记为已启用，但目录不存在，跳过", fid)
                continue
            try:
                host, mod, why = activate_payload(self, fid, info["dir"])
                if host is None:
                    logger.warning("[more_settings] 功能 {} 未激活：{}", fid, why)
                    continue
                self._payloads.append((host, mod))
                logger.info("[more_settings] 功能 payload 已加载: {} {}", fid, host.version)
            except Exception as e:
                logger.warning("[more_settings] 加载功能 {} 失败: {}", fid, e)

    # ── 补丁重建（安装 / 卸载都走这里）────────────────────────

    def _rebuild_patches(self):
        """把主程序文件重建到「官方原版 + 核心补丁 + 已启用功能的补丁」。

        先整体还原成官方原版，再按当前状态重新施加。这样：
          - 卸载某个功能后，它的补丁是真的撤掉了，而不是等下次重启；
          - 其它功能不受影响；
          - 任何一步失败都停在「官方原版 + 核心补丁」这个可用状态，
            不会留下半个补丁让主程序重启后崩溃。
        只重打补丁、不碰组件注册 —— 注册是进程级的，重来一次会冲突。
        """
        try:
            _restore_all(logger)
        except Exception as e:
            logger.warning("[more_settings] 还原主程序文件失败: {}", e)
        for fid, info in self._payload_index().items():
            if not info["exists"]:
                continue
            try:
                host, mod = load_payload(self, fid, info["dir"])
                fn = getattr(mod, "apply_patches", None)
                if not callable(fn):
                    continue
                host.begin()
                try:
                    fn(host)
                except Exception as e:
                    host.rollback()
                    logger.warning("[more_settings] {} 补丁失败已回滚: {}", fid, e)
                    continue
                # 同 activate_payload：payload 会吞异常，必须按声明核对落地情况
                if not self._patches_all_applied(fid):
                    n = host.rollback()
                    logger.warning(
                        "[more_settings] {} 补丁未全部落地，已回滚 {} 个文件", fid, n)
                    continue
                if not host.commit():
                    logger.warning("[more_settings] {} 补丁自检未通过，已回滚", fid)
            except Exception as e:
                logger.warning("[more_settings] 重建 {} 补丁异常: {}", fid, e)

    def _patch_status(self, feature_id: str):
        """某功能所需补丁的落地情况。空列表表示该功能不需要补丁。"""
        try:
            from integrations import find_app_root as _far, patch_status
            root = _far()
            if root is None:
                return []
            return patch_status(root, feature_id)
        except Exception as e:
            logger.warning("[more_settings] 查询 {} 补丁状态失败: {}", feature_id, e)
            return []

    def _patches_all_applied(self, feature_id: str) -> bool:
        st = self._patch_status(feature_id)
        if not st:
            return True          # 不需要补丁的功能，没有「注入失败」一说
        return all(x["applied"] for x in st)

    def _activate_feature(self, fid: str):
        """安装完成后在主线程激活：注册组件。返回 (是否成功, 说明)。

        补丁已由 _rebuild_patches 打好，这里只做「注册」这一步。
        """
        for host, _mod in getattr(self, "_payloads", []):
            if host.feature_id == fid:
                return True, "组件早前已注册"
        info = self._payload_index().get(fid)
        if not info or not info["exists"]:
            return False, "功能目录不存在"
        try:
            host, mod = load_payload(self, fid, info["dir"])
            fn = getattr(mod, "on_load", None)
            if callable(fn):
                fn(host)
        except Exception as e:
            return False, f"激活失败: {e}"
        self._payloads.append((host, mod))
        return True, "已激活"

    def _feature_name(self, fid: str) -> str:
        """功能 id → 显示名（找不到就退回 id）。"""
        i = self._inst()
        try:
            for f in (i.features or []) if i else []:
                if f.get("id") == fid:
                    return str(f.get("name") or fid)
        except Exception:
            pass
        return str(fid)

    def _emit_result(self, fid: str, name: str, ok: bool, msg: str):
        """把结果发给界面。界面据此弹主程序同款的成功提示并显示重启按钮。"""
        try:
            self.featureResult.emit(str(fid), str(name), bool(ok), str(msg))
        except Exception as e:
            logger.warning("[more_settings] 结果信号发送失败: {}", e)

    def _on_feature_staged(self, fid: str, version: str):
        """安装器下载完成后的收尾（主线程）。

        整段兜底：万一注入过程抛异常，也必须走到 finishActivation ——
        否则界面按钮会因为 installerBusy 一直是 True 而永久锁死。
        """
        try:
            self._finish_staged(fid)
        except Exception as e:
            logger.warning("[more_settings] 功能 {} 注入收尾异常: {}", fid, e)
            i = self._inst()
            if i:
                try:
                    i.discardInstalled(fid)
                except Exception:
                    pass
                try:
                    self._rebuild_patches()
                except Exception:
                    pass
                i.finishActivation(fid, False, f"注入过程出错，已撤回，主程序未被改动：{e}")
            self._emit_result(fid, self._feature_name(fid), False,
                              f"注入过程出错，已撤回，主程序未被改动：{e}")

    def _finish_staged(self, fid: str):
        """安装完成后的补丁注入 + 验收，验收不过就撤回。"""
        i = self._inst()
        name = fid
        try:
            if i:
                for f in (i.features or []):
                    if f.get("id") == fid:
                        name = f.get("name") or fid
                        break
        except Exception:
            pass

        logger.info("[more_settings] 功能 {} 下载完成，开始注入补丁", fid)
        self._rebuild_patches()

        if not self._patches_all_applied(fid):
            # 验收不过 ⇒ 撤回：删目录、清记录、再重建一次，回到干净状态
            logger.warning("[more_settings] {} 补丁未落地，撤回安装", fid)
            if i:
                i.discardInstalled(fid)
            self._rebuild_patches()
            if i:
                i.finishActivation(fid, False, f"{name} 补丁注入失败，已撤回，主程序未被改动")
            self._emit_result(
                fid, name, False,
                f"{name} 的补丁没有全部注入，已撤回，主程序未被改动。")
            return

        ok, why = self._activate_feature(fid)
        msg = (f"{name} 安装完成，补丁已注入并生效" if ok
               else f"{name} 补丁已注入，但{why}")
        self._emit_result(fid, name, ok, msg)
        if i:
            i.finishActivation(fid, ok, msg)

    def _on_feature_uninstalled(self, fid: str):
        """卸载后的收尾（主线程）：把补丁真的撤掉。"""
        logger.info("[more_settings] 功能 {} 已卸载，撤除补丁", fid)
        self._payloads = [(h, m) for h, m in getattr(self, "_payloads", [])
                          if h.feature_id != fid]
        self._rebuild_patches()
        self._emit_result(fid, self._feature_name(fid), True,
                          f"{self._feature_name(fid)} 已卸载，补丁已撤除。")

    @Slot(str, result="QVariantList")
    def patchStatusOf(self, feature_id: str) -> list:
        """界面用：某功能所需补丁的安装状态。"""
        return self._patch_status(feature_id)

    def _shutdown_payloads(self):
        """按加载的逆序卸载。主程序文件的回滚由 _restore_all 统一负责。"""
        for host, mod in reversed(getattr(self, "_payloads", [])):
            try:
                fn = getattr(mod, "on_unload", None)
                if callable(fn):
                    fn(host)
            except Exception as e:
                logger.warning("[more_settings] 卸载功能 {} 失败: {}", host.feature_id, e)
        self._payloads = []

    def on_load(self):
        super().on_load()
        try:
            self.api.config.register_plugin_model(_plugin_id(), self._config)
            logger.info("[more_settings] 配置模型注册成功: plugins.configs.{}", _plugin_id())
        except Exception as e:
            logger.warning("[more_settings] 注册配置模型失败: {}", e)

        self._migrate_old_config()

        # 堆叠组件**不在这里注册** —— 它由功能 payload 提供（payload 自带 qml
        # 与后端）。这样卸载堆叠后组件是真的消失，而不是被内置注册又装回来。

        # 主设置页
        try:
            settings_qml = str(Path(__file__).parent / "qml" / "settings.qml")
            self.api.ui.register_settings_page(
                qml_path=settings_qml,
                title="Kryon 的扩展设置",
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

        # 安装器跑在子线程里（下载），但注入会碰组件注册，必须回主线程。
        # 这两个信号默认就是队列连接，槽函数会在主线程执行。
        i = self._inst()
        if i:
            try:
                i.staged.connect(self._on_feature_staged)
                i.uninstalled.connect(self._on_feature_uninstalled)
            except Exception as e:
                logger.warning("[more_settings] 接安装器信号失败: {}", e)

        # 功能 payload 最后加载：此时内置的补丁与注册都已完成，
        # payload 才能正确判断自己该不该接管某个组件。
        self._boot_payloads()

    def on_unload(self):
        super().on_unload()
        self._shutdown_payloads()
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


    def _current_subject_name(self) -> str:
        """取当前课表科目名。
        主程序 runtime 暴露的是 currentSubject（驼峰，对象 {name,color}），
        老代码读的 current_subject 并不存在，于是永远拿到空串 —— 功能表现为「完全没效果」。
        两种写法都兼容，并兼容字符串形式。
        """
        try:
            rt = getattr(self.api, "runtime", None)
            if rt is None:
                return ""
            val = getattr(rt, "currentSubject", None)
            if val is None:
                val = getattr(rt, "current_subject", None)
            if isinstance(val, str):
                return val.strip()
            if hasattr(val, "get"):
                return str(val.get("name") or "").strip()
            return str(getattr(val, "name", "") or "").strip()
        except Exception:
            return ""

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
            subject = self._current_subject_name()
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
                logger.info("[more_settings] 已迁移旧插件配置 -> {}", _plugin_id())
        except Exception as e:
            logger.warning("[more_settings] 迁移旧配置失败: {}", e)
