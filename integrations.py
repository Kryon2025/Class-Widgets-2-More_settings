# -*- coding: utf-8 -*-
"""Kryon 的更多设置 —— 主程序集成补丁模块。

融合三类补丁：
1. 小组件高度/深度（原 com.kryon.widgets-high）：
   WidgetsContainer.qml 增加 displayTop / hideDepthOverride 属性与同步 Timer。
2. 堆叠组件（原 com.overlay）：
   WidgetsContainer.qml / WidgetLoader.qml 增加"编辑成员组件"入口，
   并复制 AddOverlayMemberDialog.qml 到主程序。
3. 组件动画开关（原 com.event.countdown.anim + 新增时间组件）：
   eventCountdown.qml / Time.qml 整体替换为带开关的补丁版。

所有补丁幂等、可逆：卸载插件时从 .cwplugin_backups/more_settings/ 还原官方原版。
"""

from __future__ import annotations

import shutil
from pathlib import Path

# 主程序关键文件（相对主程序根目录）
_CONTAINER_REL = Path("src") / "qml" / "ClassWidgets" / "Components" / "WidgetsContainer.qml"
_WLOADER_REL = Path("src") / "qml" / "ClassWidgets" / "Components" / "WidgetLoader.qml"
_DIALOG_REL = Path("src") / "qml" / "ClassWidgets" / "Components" / "dialogs" / "AddOverlayMemberDialog.qml"
_COUNTDOWN_REL = Path("src") / "qml" / "widgets" / "eventCountdown.qml"
_TIME_REL = Path("src") / "qml" / "widgets" / "Time.qml"

_BACKUP_ROOT = ".cwplugin_backups"
_BACKUP_SUB = "more_settings"
_DIALOG_SRC = Path(__file__).resolve().parent / "host_patch" / "AddOverlayMemberDialog.qml"
_COUNTDOWN_PATCH = Path(__file__).resolve().parent / "qml" / "eventCountdown.patch.qml"
_TIME_PATCH = Path(__file__).resolve().parent / "qml" / "time.patch.qml"
_NO_DIALOG_MARK = "NO_DIALOG_ORIG"

_OVERLAY_MARKER = "overlayEditMode"
_COUNTDOWN_MARK = "// [patched by com.kryon.more_settings v2]"
_COUNTDOWN_OLD_MARK = "// [patched by com.event.countdown.anim]"
_TIME_MARK = "// [patched by com.kryon.more_settings v2]"

NEW_CFG_KEY = "com.kryon.more_settings"
OLD_HIGH_KEY = "com.kryon.widgets-high"
NEW_TIMER_ID = "kryonMoreSettingsSyncTimer"
OLD_TIMER_ID = "kryonWidgetsHighSyncTimer"


def find_app_root():
    """定位主程序根目录（含 src/qml/.../WidgetsContainer.qml 的路径）。

    覆盖多种安装形态：
    1. 便携版/解包版：插件位于 <主程序根>/plugins/<id>/，向上遍历命中；
    2. sys.path 中的主程序运行目录；
    3. onedir 发行版：主程序可执行文件所在目录。
    """
    import sys

    candidates = []
    try:
        candidates.append(Path(sys.executable).resolve().parent)
    except Exception:
        pass
    candidates.extend(Path(p) for p in sys.path if isinstance(p, str))
    here = Path(__file__).resolve()
    candidates.extend(here.parents)

    seen = set()
    for cand in candidates:
        try:
            key = cand.resolve()
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        try:
            if (cand / _CONTAINER_REL).is_file():
                return cand
        except OSError:
            continue
    return None


def _read(path):
    raw = path.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8")
    if crlf:
        text = text.replace("\r\n", "\n")
    return text, crlf


def _write(path, text, crlf):
    data = text.encode("utf-8")
    if crlf:
        data = data.replace(b"\n", b"\r\n")
    path.write_bytes(data)


def _apply(text, ops, tag):
    """顺序执行锚点替换（幂等：new 已存在则跳过该 op）。"""
    for old, new in ops:
        if new in text:
            continue
        candidates = old if isinstance(old, (list, tuple)) else [old]
        hit = None
        for cand in candidates:
            n = text.count(cand)
            if n > 1:
                raise RuntimeError(f"{tag}: 锚点重复 ({n}): {cand[:60]!r}")
            if n == 1:
                hit = cand
        if hit is None:
            raise RuntimeError(f"{tag}: 锚点未找到: {candidates[0][:60]!r}（主程序版本不兼容）")
        text = text.replace(hit, new, 1)
    return text


# ── 小组件高度补丁片段 ────────────────────────────────────────

_HIDE_MARGIN_OLD = (
    "    property real hideMargin: {\n"
    "        if (floatingMode) return 0  // 浮窗模式下完全移出窗口\n"
    "        switch (Qt.platform.os) {\n"
    "            case \"osx\":\n"
    "                return 48\n"
    "            default:\n"
    "                return 24\n"
    "        }\n"
    "    } // 隐藏时保留的可点击空间"
)

_HIDE_MARGIN_NEW = (
    "    // patched by com.kryon.more_settings：展示高度 / 隐藏深度（Timer 实时同步）\n"
    "    property real displayTop: -1\n"
    "    property real hideDepthOverride: -1\n"
    "    property real hideMargin: {\n"
    "        if (floatingMode) return 0  // 浮窗模式下完全移出窗口\n"
    "        var comHighDef = Qt.platform.os === \"osx\" ? 48 : 24\n"
    "        return hideDepthOverride >= 0 ? hideDepthOverride : comHighDef\n"
    "    } // 隐藏时保留的可点击空间"
)

_TIMER_BLOCK = (
    "\n    // patched by com.kryon.more_settings：实时同步插件配置（展示高度 / 隐藏深度）\n"
    "    Timer {\n"
    "        id: " + NEW_TIMER_ID + "\n"
    "        interval: 300\n"
    "        repeat: true\n"
    "        running: true\n"
    "        onTriggered: {\n"
    "            var cfg = (typeof Configs !== \"undefined\" && Configs.data.plugins\n"
    "                && Configs.data.plugins.configs)\n"
    "                ? Configs.data.plugins.configs[\"" + NEW_CFG_KEY + "\"] : null\n"
    "            var dt = (cfg && cfg.display_height !== undefined && cfg.display_height !== null)\n"
    "                ? cfg.display_height : -1\n"
    "            var hd = (cfg && cfg.hide_depth !== undefined && cfg.hide_depth !== null)\n"
    "                ? cfg.hide_depth : -1\n"
    "            widgetsContainer.displayTop = dt\n"
    "            widgetsContainer.hideDepthOverride = hd\n"
    "        }\n"
    "    }\n"
)

_CALCY_OLD = "y = preferences.widgets_offset_y"
_CALCY_NEW = "y = (displayTop >= 0 ? displayTop : preferences.widgets_offset_y)"
_SIGNAL_ANCHOR = "    signal contentGeometryChanged()\n"


# ── 堆叠插件补丁定义（原 com.overlay）─────────────────────────

_CONTAINER_OPS = [
    ("import ClassWidgets.Easing",
     "import ClassWidgets.Easing\nimport \"dialogs\""),
    ("    property bool editMode: false",
     """    property bool editMode: false
    // 堆叠插件集成：编辑其内部成员（成员纵向排列 + 下方编辑行）
    property bool overlayEditMode: false"""),
    (["""                MenuItem {
                    icon.name: "ic_fluent_delete_20_regular"
                    text: qsTr("Delete")""",
      """                    MenuItem {
                        icon.name: "ic_fluent_delete_20_regular"
                        text: qsTr("Delete")"""],
     """                MenuItem {
                    // 堆叠插件集成：编辑其内部成员
                    visible: model.typeId === "com.overlay"
                    icon.name: "ic_fluent_layers_20_regular"
                    text: qsTr("编辑成员组件")
                    onTriggered: {
                        widgetMenu.close()
                        widgetsContainer.editMode = true
                        widgetsContainer.overlayEditMode = true
                    }
                }
                MenuItem {
                    icon.name: "ic_fluent_delete_20_regular"
                    text: qsTr("Delete")"""),
    (["""            property real visualScale: scaleFactor
            width: loader.width * visualScale
            height: loader.height * visualScale""",
      """                property real visualScale: scaleFactor
                width: loader.width * visualScale
                height: loader.height * visualScale"""],
     """            // 堆叠插件集成：编辑时独占一行（大组件），下方展开编辑行
            property bool isOverlay: model.typeId === "com.overlay"
            property bool overlayEditing: widgetsContainer.overlayEditMode && isOverlay
            property real visualScale: scaleFactor
            width: overlayEditing
                ? Math.max((widgetsContainer.parent ? widgetsContainer.parent.width - 16 : 0),
                           loader.width * visualScale)
                : loader.width * visualScale
            height: loader.height * visualScale
                + (overlayEditing ? editRow.height + 10 : 0)"""),
    (["""            ToolButton {
                id: deleteBtn""",
      """                ToolButton {
                    id: deleteBtn"""],
     """            // 堆叠插件集成：成员编辑行（Add Member / Done）
            RowLayout {
                id: editRow
                objectName: "editRow"
                visible: widgetContainer.overlayEditing
                anchors.top: loader.bottom
                anchors.topMargin: 10
                anchors.horizontalCenter: parent.horizontalCenter
                width: implicitWidth
                height: implicitHeight
                spacing: 8

                Button {
                    id: addOverlayMemberButton
                    icon.name: "ic_fluent_add_20_regular"
                    text: qsTr("Add Member")
                    onClicked: addOverlayMemberDialog.open()
                }

                Button {
                    id: acceptOverlayButton
                    highlighted: true
                    icon.name: "ic_fluent_checkmark_20_regular"
                    text: qsTr("Done")
                    onClicked: {
                        widgetsContainer.overlayEditMode = false
                    }
                }
            }

            ToolButton {
                id: deleteBtn"""),
    ("            rotation: editMode",
     "            rotation: editMode && !widgetsContainer.overlayEditMode"),
    ("                running: editMode",
     "                running: editMode && !widgetsContainer.overlayEditMode"),
    (["""            // 鼠标右键打开设置
            TapHandler {
                acceptedButtons: Qt.RightButton""",
      """                // 鼠标右键打开设置
                TapHandler {
                    acceptedButtons: Qt.RightButton"""],
     """            // 鼠标右键打开设置（编辑堆叠时禁用，成员右键由 overlay 内部处理）
            TapHandler {
                acceptedButtons: Qt.RightButton
                enabled: !widgetsContainer.overlayEditMode"""),
    ("onClicked: widgetsContainer.editMode = false",
     "onClicked: { widgetsContainer.editMode = false; widgetsContainer.overlayEditMode = false }"),
    ("""    // 小组件设置窗口
    WidgetSettingsDialog {
        id: settingsDialog
    }""",
     """    // 小组件设置窗口
    WidgetSettingsDialog {
        id: settingsDialog
    }

    // 堆叠插件集成：成员选择窗口
    AddOverlayMemberDialog {
        id: addOverlayMemberDialog
    }"""),
    ("""            visible: widgetsContainer.editMode
            id: acceptButton""",
     """            visible: widgetsContainer.editMode && !widgetsContainer.overlayEditMode
            id: acceptButton"""),
    ("""        visible: widgetsContainer.editMode || widgetRepeater.count === 0""",
     """        visible: (widgetsContainer.editMode || widgetRepeater.count === 0)
            && !widgetsContainer.overlayEditMode"""),
    (["""                                settingsDialog.setSource(model.settingsQml, {
                                    "settings": model.settings,
                                    "instanceId": model.instanceId
                                })""",
      """                            settingsDialog.setSource(model.settingsQml, {
                                "settings": model.settings,
                                "instanceId": model.instanceId
                            })"""],
     """                                settingsDialog.setSource(model.settingsQml, {
                                    "settings": model.settings,
                                    "instanceId": model.instanceId,
                                    "backendObj": model.backendObj
                                })"""),
]

_WLOADER_OPS = [
    ("""            if (item && item.hasOwnProperty('editMode')) {
                item.editMode = widgetsContainer.editMode
            }
            anim.start()""",
     """            if (item && item.hasOwnProperty('editMode')) {
                item.editMode = widgetsContainer.editMode
            }
            if (item && item.hasOwnProperty('overlayListMode')) {
                item.overlayListMode = widgetsContainer.overlayEditMode
            }
            anim.start()"""),
    ("""        function onEditModeChanged() {
            if (loader.item && loader.item.hasOwnProperty('editMode')) {
                loader.item.editMode = widgetsContainer.editMode
            }
        }
    }""",
     """        function onEditModeChanged() {
            if (loader.item && loader.item.hasOwnProperty('editMode')) {
                loader.item.editMode = widgetsContainer.editMode
            }
        }
        function onOverlayEditModeChanged() {
            if (loader.item && loader.item.hasOwnProperty('overlayListMode')) {
                loader.item.overlayListMode = widgetsContainer.overlayEditMode
            }
        }
    }"""),
]


# ── 对外接口 ────────────────────────────────────────────────

def install_all(logger, root=None):
    """安装全部主程序补丁（幂等）。返回是否成功。"""
    if root is None:
        root = find_app_root()
    if root is None:
        logger.warning("[more_settings] 未找到主程序目录，跳过集成")
        return False
    root = Path(root)
    container = root / _CONTAINER_REL
    wloader = root / _WLOADER_REL
    dialog = root / _DIALOG_REL
    backup_dir = root / _BACKUP_ROOT / _BACKUP_SUB

    if not container.is_file() or not wloader.is_file():
        logger.error(f"[more_settings] 目录不是有效的 ClassWidgets 主程序: {root}")
        return False

    # 首次安装时统一备份（保留官方原版；已有备份不覆盖）
    first_run = not backup_dir.is_dir()
    if first_run:
        backup_dir.mkdir(parents=True, exist_ok=True)
        _backup_file(container, backup_dir / "WidgetsContainer.qml.orig")
        _backup_file(wloader, backup_dir / "WidgetLoader.qml.orig")
        _record_dialog_backup(backup_dir, dialog, dialog.is_file())

    # 1) 小组件高度补丁（WidgetsContainer.qml）
    # 2) 堆叠补丁（WidgetsContainer.qml + WidgetLoader.qml + dialog）
    try:
        c_text, c_crlf = _read(container)
        c_text = _apply_height(c_text)
        c_text = _apply(c_text, _CONTAINER_OPS, "WidgetsContainer.qml")
        _write(container, c_text, c_crlf)

        w_text, w_crlf = _read(wloader)
        w_text = _apply(w_text, _WLOADER_OPS, "WidgetLoader.qml")
        _write(wloader, w_text, w_crlf)

        # 插件专有文件：始终同步最新版（官方主程序无此文件，覆盖安全）
        if not _DIALOG_SRC.is_file():
            raise RuntimeError("缺少 AddOverlayMemberDialog.qml 资源文件")
        dialog.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_DIALOG_SRC, dialog)
    except Exception as e:
        restore_all(logger)
        logger.error(f"[more_settings] 集成补丁失败，已还原: {e}")
        return False

    # 3) 组件动画开关补丁（整体替换 + .orig 备份）
    _install_qml_replace(logger, root / _COUNTDOWN_REL, _COUNTDOWN_PATCH,
                         _COUNTDOWN_MARK, [_COUNTDOWN_OLD_MARK],
                         backup_dir / "eventCountdown.qml.orig", "事件倒计时")
    _install_qml_replace(logger, root / _TIME_REL, _TIME_PATCH,
                         _TIME_MARK, [],
                         backup_dir / "Time.qml.orig", "时间")

    logger.info("[more_settings] 主程序集成补丁已安装")
    return True


def _apply_height(text):
    """应用小组件高度补丁（幂等，并接管旧 com.kryon.widgets-high 补丁）。"""
    # 接管旧插件的同步 Timer：改读新配置 key + 重命名 id
    if OLD_HIGH_KEY in text:
        text = text.replace('configs["' + OLD_HIGH_KEY + '"]', 'configs["' + NEW_CFG_KEY + '"]')
        text = text.replace(OLD_TIMER_ID, NEW_TIMER_ID)
    # hideMargin 块：已含 hideDepthOverride 则视为已装，否则替换官方块
    if "hideDepthOverride" not in text:
        if _HIDE_MARGIN_OLD not in text:
            # 可能是其它变体（含 floatingMode 注释等），保守跳过，避免破坏文件
            pass
        else:
            text = text.replace(_HIDE_MARGIN_OLD, _HIDE_MARGIN_NEW, 1)
    # 同步 Timer：新 id 已存在则跳过，否则插入
    if NEW_TIMER_ID not in text:
        if _SIGNAL_ANCHOR in text:
            text = text.replace(_SIGNAL_ANCHOR, _TIMER_BLOCK + _SIGNAL_ANCHOR, 1)
        else:
            text = _TIMER_BLOCK + text
    # calcY：接管展示高度
    if "displayTop >= 0" not in text:
        text = text.replace(_CALCY_OLD, _CALCY_NEW)
    return text


def _install_qml_replace(logger, target, patch_src, our_mark, old_marks, backup, tag):
    """整体替换单个内置组件 QML（幂等，可逆）。"""
    if not target.is_file() or not patch_src.is_file():
        return
    try:
        text, crlf = _read(target)
        if our_mark in text:
            return
        # 备份（首次；被旧插件补丁过时备份的是当前文件，仍可还原）
        if not backup.is_file():
            _backup_file(target, backup)
        patch_text, patch_crlf = _read(patch_src)
        _write(target, patch_text, patch_crlf)
        logger.info(f"[more_settings] 已为{tag}组件应用动画开关补丁")
    except OSError as e:
        logger.error(f"[more_settings] 应用{tag}补丁失败: {e}")


def restore_all(logger, root=None):
    """从备份还原主程序（幂等）。无备份时不做任何事。"""
    if root is None:
        root = find_app_root()
    if root is None:
        return False
    root = Path(root)
    backup_dir = root / _BACKUP_ROOT / _BACKUP_SUB
    if not backup_dir.is_dir():
        return False

    for name, rel in (("WidgetsContainer.qml.orig", _CONTAINER_REL),
                      ("WidgetLoader.qml.orig", _WLOADER_REL),
                      ("eventCountdown.qml.orig", _COUNTDOWN_REL),
                      ("Time.qml.orig", _TIME_REL)):
        src = backup_dir / name
        if src.is_file():
            (root / rel).write_bytes(src.read_bytes())

    # 对话框：官方原本有 → 还原；官方原本没有 → 删除注入的
    if (backup_dir / "AddOverlayMemberDialog.qml.orig").is_file():
        (root / _DIALOG_REL).write_bytes(
            (backup_dir / "AddOverlayMemberDialog.qml.orig").read_bytes())
    elif (backup_dir / _NO_DIALOG_MARK).is_file():
        (root / _DIALOG_REL).unlink(missing_ok=True)

    shutil.rmtree(backup_dir, ignore_errors=True)
    logger.info("[more_settings] 主程序已还原")
    return True


def _backup_file(src, dst):
    dst.write_bytes(src.read_bytes())


def _record_dialog_backup(backup_dir, dialog, existed):
    if existed:
        (backup_dir / "AddOverlayMemberDialog.qml.orig").write_bytes(dialog.read_bytes())
    else:
        (backup_dir / _NO_DIALOG_MARK).write_text(
            "official ClassWidgets has no AddOverlayMemberDialog.qml\n", encoding="utf-8")
