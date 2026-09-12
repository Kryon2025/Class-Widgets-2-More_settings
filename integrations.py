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
_EDITDLG_REL = Path("src") / "qml" / "ClassWidgets" / "Components" / "dialogs" / "EditOverlayDialog.qml"
_COUNTDOWN_REL = Path("src") / "qml" / "widgets" / "eventCountdown.qml"
_TIME_REL = Path("src") / "qml" / "widgets" / "Time.qml"

_BACKUP_ROOT = ".cwplugin_backups"
_BACKUP_SUB = "more_settings"
_DIALOG_SRC = Path(__file__).resolve().parent / "host_patch" / "AddOverlayMemberDialog.qml"
_EDITDLG_SRC = Path(__file__).resolve().parent / "host_patch" / "EditOverlayDialog.qml"
_COUNTDOWN_PATCH = Path(__file__).resolve().parent / "qml" / "eventCountdown.patch.qml"
_TIME_PATCH = Path(__file__).resolve().parent / "qml" / "time.patch.qml"
_NO_DIALOG_MARK = "NO_DIALOG_ORIG"

_OVERLAY_MARKER = "overlayEditingId"
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


def _apply(text, ops, tag, logger=None):
    """顺序执行锚点替换（幂等：new 已存在则跳过该 op）。

    容错：某个锚点未找到 / 重复时跳过该 op 并记录警告，不中断其余补丁，
    以兼容不同主程序版本的差异（避免单点失配导致整批补丁失效）。
    """
    for old, new in ops:
        if new in text:
            continue
        candidates = old if isinstance(old, (list, tuple)) else [old]
        hit = None
        dup = False
        for cand in candidates:
            n = text.count(cand)
            if n > 1:
                if logger:
                    logger.warning(f"[more_settings] {tag}: 锚点重复({n})，跳过: {cand[:50]!r}")
                dup = True
                break
            if n == 1:
                hit = cand
        if dup:
            continue
        if hit is None:
            if logger:
                logger.warning(
                    f"[more_settings] {tag}: 锚点未找到，跳过（版本差异）: {candidates[0][:50]!r}")
            continue
        text = text.replace(hit, new, 1)
    return text


def _apply_group(text, ops, tag, logger=None):
    """一组强相关的补丁：逐个应用，任一 op 的锚点找不到就整组放弃。

    用于 overlay 这类"引用与定义必须成套"的补丁——先应用到临时副本，某个锚点
    缺失就返回原文，避免部分注入造成主程序 QML 加载失败（崩溃）。
    按顺序应用，后面的 op 可以依赖前面 op 刚产生的内容。
    """
    original = text
    for old, new in ops:
        if new in text:
            continue
        candidates = old if isinstance(old, (list, tuple)) else [old]
        hit = None
        for cand in candidates:
            if text.count(cand) == 1:
                hit = cand
                break
        if hit is None:
            if logger:
                logger.warning(
                    f"[more_settings] {tag}: 关键锚点缺失（主程序版本差异），已整组跳过以保证安全")
            return original
        text = text.replace(hit, new, 1)
    return text


def _assert_qml_consistent(text, tag):
    """写入前自检：任一不一致都抛错（由调用方回滚）。

    宁可该补丁不生效，也不能让主程序因 QML 加载失败而崩溃。
    """
    if "AddOverlayMemberDialog" in text and 'import "dialogs"' not in text:
        raise RuntimeError(f"{tag}: 引用了 AddOverlayMemberDialog 却缺少 import \"dialogs\"")
    if text.count("{") != text.count("}"):
        raise RuntimeError(
            f"{tag}: 花括号不平衡（{text.count('{')} vs {text.count('}')}），疑似锚点半匹配")


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

# v3：把正在编辑的堆叠组件实例传给成员选择对话框（按实例隔离）
_ADD_MEMBER_OLD = """                    text: qsTr("Add Member")
                    onClicked: addOverlayMemberDialog.open()"""
_ADD_MEMBER_NEW = """                    text: qsTr("Add Member")
                    onClicked: {
                        // 正在编辑的堆叠组件实例 → 成员加到该实例下
                        addOverlayMemberDialog.overlayInstanceId = model.instanceId
                        addOverlayMemberDialog.open()
                    }"""

# v3：编辑行 Done 按钮之后追加"自定义组件框宽/高 + 自适应"按钮组
_EDITROW_TAIL_ANCHOR = """                    text: qsTr("Done")
                    onClicked: {
                        widgetsContainer.overlayEditMode = false
                    }
                }"""
_EDITROW_TAIL_NEW = _EDITROW_TAIL_ANCHOR + """

                // 堆叠插件集成：自定义组件框宽高（0 = 自适应；按实例保存）
                Text {
                    Layout.alignment: Qt.AlignVCenter
                    font.pixelSize: 13
                    color: Theme.isDark() ? Qt.rgba(1, 1, 1, 0.65) : Qt.rgba(0, 0, 0, 0.6)
                    text: {
                        var ow = loader.item
                        var w = ow ? ow.frameW : 0
                        var h = ow ? ow.frameH : 0
                        if (w > 0 && h > 0) return w + "×" + h
                        if (w > 0) return w + "×自动"
                        if (h > 0) return "自动×" + h
                        return qsTr("自适应")
                    }
                }
                Button {
                    text: qsTr("宽−")
                    onClicked: if (loader.item) loader.item.stepFrame(-10, 0)
                }
                Button {
                    text: qsTr("宽+")
                    onClicked: if (loader.item) loader.item.stepFrame(10, 0)
                }
                Button {
                    text: qsTr("高−")
                    onClicked: if (loader.item) loader.item.stepFrame(0, -10)
                }
                Button {
                    text: qsTr("高+")
                    onClicked: if (loader.item) loader.item.stepFrame(0, 10)
                }
                Button {
                    text: qsTr("自适应")
                    onClicked: if (loader.item) loader.item.resetFrame()
                }"""

# overlay 相关补丁（原子组：任一关键锚点缺失则整组跳过，
# 避免"引用了 AddOverlayMemberDialog 却缺 import / 组件文件"导致主程序 QML 加载失败）
_CONTAINER_OVERLAY_OPS = [
    ("import ClassWidgets.Easing",
     "import ClassWidgets.Easing\nimport \"dialogs\""),
    ("    property bool editMode: false",
     """    property bool editMode: false
    // 堆叠插件集成：正在编辑的堆叠组件实例 id（按实例隔离，就地展开）
    property string overlayEditingId: ''"""),
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
                        widgetsContainer.overlayEditingId = model.instanceId
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
            property bool overlayEditing: widgetsContainer.overlayEditingId === model.instanceId && isOverlay
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
                    onClicked: {
                        // 正在编辑的堆叠组件实例 → 成员加到该实例下
                        addOverlayMemberDialog.overlayInstanceId = model.instanceId
                        addOverlayMemberDialog.open()
                    }
                }

                Button {
                    id: acceptOverlayButton
                    highlighted: true
                    icon.name: "ic_fluent_checkmark_20_regular"
                    text: qsTr("Done")
                    onClicked: {
                        widgetsContainer.overlayEditingId = ''
                    }
                }
            }

            ToolButton {
                id: deleteBtn"""),
    ("            rotation: editMode",
     "            rotation: editMode && !widgetContainer.overlayEditing"),
    ("                running: editMode",
     "                running: editMode && !widgetContainer.overlayEditing"),
    (["""            // 鼠标右键打开设置
            TapHandler {
                acceptedButtons: Qt.RightButton""",
      """                // 鼠标右键打开设置
                TapHandler {
                    acceptedButtons: Qt.RightButton"""],
     """            // 鼠标右键打开设置（编辑堆叠时禁用，成员右键由 overlay 内部处理）
            TapHandler {
                acceptedButtons: Qt.RightButton
                enabled: !widgetContainer.overlayEditing"""),
    ("onClicked: widgetsContainer.editMode = false",
     "onClicked: { widgetsContainer.editMode = false; widgetsContainer.overlayEditingId = '' }"),
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
     """            visible: widgetsContainer.editMode && widgetsContainer.overlayEditingId === ''
            id: acceptButton"""),
    ("""        visible: widgetsContainer.editMode || widgetRepeater.count === 0""",
     """        visible: (widgetsContainer.editMode || widgetRepeater.count === 0)
            && widgetsContainer.overlayEditingId === ''"""),
    (_ADD_MEMBER_OLD, _ADD_MEMBER_NEW),
]

# 与 overlay 无关的修正：给组件设置页注入 backendObj（独立应用，不受 overlay 锚点影响）
_CONTAINER_MISC_OPS = [
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
    # 新版主程序：setSource 增加 widget_id 字段（单独一 op，兼容两种版本）
    ("""                                settingsDialog.setSource(model.settingsQml, {
                                    "settings": model.settings,
                                    "instanceId": model.instanceId,
                                    "widget_id": model.widget_id
                                })""",
     """                                settingsDialog.setSource(model.settingsQml, {
                                    "settings": model.settings,
                                    "instanceId": model.instanceId,
                                    "widget_id": model.widget_id,
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
                item.overlayListMode = widgetsContainer.overlayEditingId === model.instanceId
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
        function onOverlayEditingIdChanged() {
            if (loader.item && loader.item.hasOwnProperty('overlayListMode')) {
                loader.item.overlayListMode = widgetsContainer.overlayEditingId === model.instanceId
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
    # 3) 组件动画开关补丁
    # 全部先改内存、自检通过后再落盘；任一步失败立即回滚，保证主程序始终可用。
    try:
        c_text, c_crlf = _read(container)
        c_text = _apply_height(c_text)
        c_text = _apply(c_text, _CONTAINER_MISC_OPS, "WidgetsContainer.qml", logger)
        c_text = _apply_group(c_text, _CONTAINER_OVERLAY_OPS, "WidgetsContainer.qml", logger)

        # overlay 引用了对话框就必须保证组件文件存在，否则回滚
        if "AddOverlayMemberDialog" in c_text and not _DIALOG_SRC.is_file():
            raise RuntimeError("缺少 AddOverlayMemberDialog.qml 资源文件")
        _assert_qml_consistent(c_text, "WidgetsContainer.qml")

        w_text, w_crlf = _read(wloader)
        w_text = _apply(w_text, _WLOADER_OPS, "WidgetLoader.qml", logger)
        _assert_qml_consistent(w_text, "WidgetLoader.qml")

        _write(container, c_text, c_crlf)
        _write(wloader, w_text, w_crlf)

        # 插件专有对话框：官方原本没有才注入（官方已有则保留官方版本，避免破坏）
        if "AddOverlayMemberDialog" in c_text:
            dialog.parent.mkdir(parents=True, exist_ok=True)
            if not dialog.is_file():
                shutil.copy2(_DIALOG_SRC, dialog)
            else:
                logger.info("[more_settings] 官方已有 AddOverlayMemberDialog.qml，保留官方版本")

        # 组件动画开关补丁（整体替换；失败同样回滚）
        _install_qml_replace(logger, root / _COUNTDOWN_REL, _COUNTDOWN_PATCH,
                             _COUNTDOWN_MARK, [_COUNTDOWN_OLD_MARK],
                             backup_dir / "eventCountdown.qml.orig", "事件倒计时")
        _install_qml_replace(logger, root / _TIME_REL, _TIME_PATCH,
                             _TIME_MARK, [],
                             backup_dir / "Time.qml.orig", "时间")
    except Exception as e:
        restore_all(logger)
        logger.error(f"[more_settings] 集成补丁失败，已还原: {e}")
        return False

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
        patch_text, patch_crlf = _read(patch_src)
        # 替换前自检补丁本身完整，避免把坏文件写进主程序（失败会向上抛，触发整体回滚）
        _assert_qml_consistent(patch_text, f"{tag}补丁")
        # 备份（首次；被旧插件补丁过时备份的是当前文件，仍可还原）
        if not backup.is_file():
            _backup_file(target, backup)
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
    (root / _EDITDLG_REL).unlink(missing_ok=True)

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
