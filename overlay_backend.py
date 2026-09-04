# -*- coding: utf-8 -*-
"""堆叠组件后端（移植自 com.overlay，作为 QObject 供组件与设置页调用）。

成员组件列表独立持久化（.overlay_members.json）。
成员 = {"key": 唯一键, "typeId": 组件 id}，同一组件 id 可添加多个成员
（各自拥有独立设置，例如多个"倒数日"、多个"每日一言"）。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from loguru import logger
from PySide6.QtCore import Property, QObject, Signal, Slot

_OVERLAY_WIDGET_ID = "com.overlay"  # 堆叠组件自身 widget id（禁止添加自己）


class OverlayBackend(QObject):
    """堆叠组件：成员管理 + 轮播配置 + 上课隐藏切换条。"""

    membersChanged = Signal()
    classHideChanged = Signal()
    _class_hide = {"enabled": False, "days": "1,2,3,4,5", "start": "08:00", "end": "18:00"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._members: list[dict] = []
        self._member_settings: dict = {}
        base = Path(__file__).resolve().parent
        self._members_file = base / ".overlay_members.json"
        self._settings_file = base / ".overlay_member_settings.json"
        self._class_hide_file = base / ".overlay_class_hide.json"
        self._load_members()
        self._load_member_settings()
        self._load_class_hide()

    # ── 上课隐藏切换条 ───────────────────────────────────────

    def _load_class_hide(self) -> None:
        try:
            data = json.loads(self._class_hide_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k in ("enabled", "days", "start", "end"):
                    if k in data:
                        self._class_hide[k] = data[k]
        except Exception:
            pass

    def _save_class_hide(self) -> None:
        try:
            self._class_hide_file.write_text(
                json.dumps(self._class_hide, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"[more_settings] 保存上课时段配置失败: {e}")

    def _get_class_hide_enabled(self) -> bool:
        return bool(self._class_hide.get("enabled"))

    def _get_class_hide_days(self) -> str:
        return str(self._class_hide.get("days") or "")

    def _get_class_hide_start(self) -> str:
        return str(self._class_hide.get("start") or "")

    def _get_class_hide_end(self) -> str:
        return str(self._class_hide.get("end") or "")

    classHideEnabled = Property(bool, _get_class_hide_enabled, notify=classHideChanged)
    classHideDays = Property(str, _get_class_hide_days, notify=classHideChanged)
    classHideStart = Property(str, _get_class_hide_start, notify=classHideChanged)
    classHideEnd = Property(str, _get_class_hide_end, notify=classHideChanged)

    @Slot(bool, str, str, str)
    def setClassHide(self, enabled: bool, days: str, start: str, end: str) -> None:
        self._class_hide.update(enabled=bool(enabled), days=str(days or ""),
                                start=str(start or ""), end=str(end or ""))
        self._save_class_hide()
        self.classHideChanged.emit()

    @Slot()
    def refreshClassHide(self) -> None:
        self.classHideChanged.emit()

    # ── 成员管理 ─────────────────────────────────────────────

    @Slot(result=list)
    def getMembers(self) -> list:
        """返回成员对象列表：[{"key", "typeId"}, ...]（副本）。"""
        return [dict(m) for m in self._members]

    @Slot(result=int)
    def getMemberCount(self) -> int:
        return len(self._members)

    @Slot(str, result=str)
    def addMember(self, widget_id: str) -> str:
        """添加成员（允许同一组件 id 重复添加）。返回新成员 key，失败返回空串。"""
        if not isinstance(widget_id, str):
            return ""
        wid = widget_id.strip()
        if not wid or wid == _OVERLAY_WIDGET_ID:
            return ""
        key = f"{wid}#{int(time.time() * 1000)}"
        self._members.append({"key": key, "typeId": wid})
        self._save_members()
        self.membersChanged.emit()
        logger.info(f"[more_settings] 已添加堆叠成员: {key}")
        return key

    @Slot(str)
    def removeMember(self, key: str) -> None:
        k = str(key).strip()
        for m in self._members:
            if m["key"] == k:
                self._members.remove(m)
                self._member_settings.pop(k, None)
                self._save_members()
                self._save_member_settings()
                self.membersChanged.emit()
                logger.info(f"[more_settings] 已移除堆叠成员: {k}")
                return

    @Slot(str, result=dict)
    def getMemberSettings(self, key: str) -> dict:
        return dict(self._member_settings.get(str(key), {}))

    @Slot(str, dict)
    def saveMemberSettings(self, key: str, settings: dict) -> None:
        k = str(key).strip()
        if not k:
            return
        self._member_settings[k] = dict(settings or {})
        self._save_member_settings()
        logger.info(f"[more_settings] 已保存成员设置: {k}")

    # ── 持久化 ───────────────────────────────────────────────

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def _load_members(self) -> None:
        """加载成员列表，兼容旧格式（字符串 widget_id 列表）。"""
        try:
            if self._members_file.exists():
                data = json.loads(self._members_file.read_text(encoding="utf-8"))
                raw = data.get("members") or []
                members = []
                for x in raw:
                    if isinstance(x, str):
                        wid = x.strip()
                        if wid and wid != _OVERLAY_WIDGET_ID:
                            members.append({"key": wid, "typeId": wid})
                    elif isinstance(x, dict) and str(x.get("typeId", "")).strip():
                        wid = str(x["typeId"]).strip()
                        if wid == _OVERLAY_WIDGET_ID:
                            continue
                        key = str(x.get("key") or "").strip() or f"{wid}#{int(time.time() * 1000)}"
                        members.append({"key": key, "typeId": wid})
                # 去重（按 key）
                seen = set()
                uniq = []
                for m in members:
                    if m["key"] not in seen:
                        seen.add(m["key"])
                        uniq.append(m)
                self._members = uniq
        except Exception:
            self._members = []

    def _save_members(self) -> None:
        try:
            self._atomic_write_json(self._members_file, {"members": self._members})
        except Exception as e:
            logger.warning(f"[more_settings] 保存成员列表失败: {e}")

    def _load_member_settings(self) -> None:
        try:
            if self._settings_file.exists():
                data = json.loads(self._settings_file.read_text(encoding="utf-8"))
                settings = {}
                for k, v in (data.get("settings") or {}).items():
                    if isinstance(v, dict):
                        settings[str(k)] = dict(v)
                self._member_settings = settings
        except Exception:
            self._member_settings = {}

    def _save_member_settings(self) -> None:
        try:
            self._atomic_write_json(self._settings_file, {"settings": self._member_settings})
        except Exception as e:
            logger.warning(f"[more_settings] 保存成员设置失败: {e}")
