# -*- coding: utf-8 -*-
"""Kryon 的扩展设置 —— 主程序集成补丁模块。

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
# 新版主程序（2.0.0.dev20260928 起）把「每个组件」的界面代码拆到了这两个文件：
# 布局在 WidgetsLayout.qml，单个组件的代理项（右键菜单、删除按钮、设置页调用）在 Delegate 里。
_LAYOUT_REL = Path("src") / "qml" / "ClassWidgets" / "Components" / "WidgetsLayout.qml"
_DELEGATE_REL = Path("src") / "qml" / "ClassWidgets" / "Components" / "WidgetsLayoutDelegate.qml"


_BACKUP_ROOT = ".cwplugin_backups"
_BACKUP_SUB = "more_settings"
# 注意：那三个功能的补丁资源（host_patch/、qml/*.patch.qml）已经不随插件分发，
# 它们由功能 payload 自带。这里只留主程序内的目标路径常量（见上）。
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

# v1（旧主程序）：hideMargin 用 switch 写法
_HIDE_MARGIN_V1 = (
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

_HIDE_MARGIN_V1_NEW = (
    "    // patched by com.kryon.more_settings：展示高度 / 隐藏深度（Timer 实时同步）\n"
    "    property real displayTop: -1\n"
    "    property real hideDepthOverride: -1\n"
    "    property real hideMargin: {\n"
    "        if (floatingMode) return 0  // 浮窗模式下完全移出窗口\n"
    "        var comHighDef = Qt.platform.os === \"osx\" ? 48 : 24\n"
    "        return hideDepthOverride >= 0 ? hideDepthOverride : comHighDef\n"
    "    } // 隐藏时保留的可点击空间"
)

# v2（2.0.0.dev20260928 起）：主程序把它改成了一行三元表达式
_HIDE_MARGIN_V2 = (
    "    property real hideMargin: {\n"
    "        if (floatingMode) return 0\n"
    "        return Qt.platform.os === \"osx\" ? 48 : 24\n"
    "    }"
)

_HIDE_MARGIN_V2_NEW = (
    "    // patched by com.kryon.more_settings：展示高度 / 隐藏深度（Timer 实时同步）\n"
    "    property real displayTop: -1\n"
    "    property real hideDepthOverride: -1\n"
    "    property real hideMargin: {\n"
    "        if (floatingMode) return 0\n"
    "        var comHighDef = Qt.platform.os === \"osx\" ? 48 : 24\n"
    "        return hideDepthOverride >= 0 ? hideDepthOverride : comHighDef\n"
    "    }"
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

# 展示高度：顶部三种停靠都要认 displayTop。锚点必须唯一 ——
# _apply 遇到「锚点出现多次」会整条跳过；旧写法 "y = preferences.widgets_offset_y"
# 在容器文件里出现两次，所以这条补丁从没生效过（displayTop 从没被用上）。
# _read() 会把宿主文件归一化成 LF，所以锚点里只能用 \n（别写 CRLF）。
_CALCY_TOP_LR_OLD = "                y = preferences.widgets_offset_y\n                // 左/右不受 hide 影响"
_CALCY_TOP_LR_NEW = "                y = (displayTop >= 0 ? displayTop : preferences.widgets_offset_y)\n                // 左/右不受 hide 影响"
_CALCY_TOP_CENTER_OLD = "                y = preferences.widgets_offset_y\n                if (hide) y = -height + hideMargin  // 仅 center 生效"
_CALCY_TOP_CENTER_NEW = "                y = (displayTop >= 0 ? displayTop : preferences.widgets_offset_y)\n                if (hide) y = -height + hideMargin  // 仅 center 生效"
# （旧的 _CALCY_NEW 已并入上面两条唯一锚点）
_SIGNAL_ANCHOR = "    signal contentGeometryChanged()\n"

# v2 结构：位置改由 shownX / shownY / hiddenY / editY 这几个只读属性算出。
# 顶部三种停靠要认 displayTop，就改 shownY 里顶部分支的返回值。
# 锚点带上 case 行：单看 "return preferences.widgets_offset_y" 就有别的分支会撞车。
_CALCY_TOP_V2_OLD = (
    '        case "top_center":\n'
    '            return preferences.widgets_offset_y'
)
_CALCY_TOP_V2_NEW = (
    '        case "top_center":\n'
    '            return (displayTop >= 0 ? displayTop : preferences.widgets_offset_y)'
)


# ── 堆叠插件补丁定义（原 com.overlay）─────────────────────────

# v3：把正在编辑的堆叠组件实例传给成员选择对话框（按实例隔离）

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

# ── 新版主程序（2.0.0.dev20260928 起）的堆叠组件补丁组 ──────────────
#
# 新版把「每个组件」的界面代码拆成了两个文件：
#   布局 WidgetsLayout.qml（根 id layoutRoot，实例化代理项）
#   代理项 WidgetsLayoutDelegate.qml（根 id widgetContainer，右键菜单/删除按钮/摇晃）
# 所以补丁也分两处落。跨组件文件不能用 id 直引对象，
# 成员选择窗口改为按属性注入 —— 这正是主程序自己传 settingsDialog 的方式。
#
# 顺序要求：layout 组必须先生效，代理项才会引用到 host.overlayEditingId。



# 容器文件里与堆叠编辑互斥的两处可见性（用容器自己的 widgetsLayout 实例引用）

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

# v2：组件设置页的 setSource 调用搬到了代理项文件（WidgetsLayoutDelegate.qml），
# 缩进也变了（20/24 空格），所以和 v1 那条不能共用锚点。
_DELEGATE_MISC_OPS = [
    ("""                    settingsDialog.setSource(model.settingsQml, {
                        "settings": model.settings,
                        "instanceId": model.instanceId,
                        "widget_id": model.widget_id
                    })""",
     """                    settingsDialog.setSource(model.settingsQml, {
                        "settings": model.settings,
                        "instanceId": model.instanceId,
                        "widget_id": model.widget_id,
                        "backendObj": model.backendObj
                    })"""),
]




# ── 「组件增强」功能用的锚点组 ──────────────────────────────
# 小组件高度/深度 + 特定课程不隐藏 + 组件设置页的 backendObj 注入。
# 这几项原本由插件本体无条件打进主程序（看起来像"自带功能"），现在归到可安装的
# 功能 kryon.extended_settings 名下 —— 卸载后是真的从主程序里消失。
# v1（旧主程序）整组。新版这些锚点已经不存在，由 payload 按「文件里有没有 shownY」
# 判断要不要调，避免在 v2 上每次启动都白报一串「锚点未找到」。
_EXTENDED_CONTAINER_V1_OPS = [
    (_HIDE_MARGIN_V1, _HIDE_MARGIN_V1_NEW),
    (_SIGNAL_ANCHOR, _TIMER_BLOCK + _SIGNAL_ANCHOR),
    (_CALCY_TOP_LR_OLD, _CALCY_TOP_LR_NEW),
    (_CALCY_TOP_CENTER_OLD, _CALCY_TOP_CENTER_NEW),
] + _CONTAINER_MISC_OPS

# v2（2.0.0.dev20260928 起）整组：容器文件里的展示高度 / 隐藏深度。
# 「组件设置页 backendObj 注入」已不在这个文件里，见 _DELEGATE_MISC_OPS。
_EXTENDED_CONTAINER_OPS = [
    (_HIDE_MARGIN_V2, _HIDE_MARGIN_V2_NEW),
    (_SIGNAL_ANCHOR, _TIMER_BLOCK + _SIGNAL_ANCHOR),
    (_CALCY_TOP_V2_OLD, _CALCY_TOP_V2_NEW),
]

# 旧「小组件高度」插件（com.kryon.widgets-high）遗留的配置 key 与 Timer id 改名。
# 单独一组：只有那个老插件打过补丁的文件里才有这些锚点，别的情况下不该去试，
# 否则每次安装都会白报一条「锚点未找到」。
_EXTENDED_LEGACY_OPS = [
    ('configs["' + OLD_HIGH_KEY + '"]', 'configs["' + NEW_CFG_KEY + '"]'),
    (OLD_TIMER_ID, NEW_TIMER_ID),
]

# 高度补丁的落地标记（_HIDE_MARGIN_NEW 里注入的字段名）
_HEIGHT_MARKER = "hideDepthOverride"


# 供功能 payload 复用的补丁锚点组。
# 单一真相留在这里：payload 只声明要用哪一组，不再自己复制一遍 QML 字符串，
# 否则主程序改版时两边会各改各的、逐渐不一致。
PUBLIC_GROUPS = {
    "container_misc": _CONTAINER_MISC_OPS,
    "extended_container": _EXTENDED_CONTAINER_OPS,
    "extended_container_v1": _EXTENDED_CONTAINER_V1_OPS,
    "extended_delegate": _DELEGATE_MISC_OPS,
    "extended_legacy": _EXTENDED_LEGACY_OPS,
}


# ── 对外接口 ────────────────────────────────────────────────

# ── 补丁落地情况 ────────────────────────────────────────────
# 判定「某个功能需要的补丁到底有没有进主程序」。每项 (主程序内相对路径, 判据)：
#     字符串              该文件里应出现的标记
#     None                只要该文件存在就算已装入
#     _DIFF_FROM_BACKUP   与官方原版备份不同（用于插件自己的核心补丁 ——
#                         它们没有统一标记，比对原版最可靠）
_DIFF_FROM_BACKUP = "<differs-from-official-backup>"

FEATURE_PATCH_SPECS = {
    # 插件本体的核心补丁：小组件高度/深度 + 组件设置页 backendObj 注入
    "kryon.extended_settings": [
        (_CONTAINER_REL, _HEIGHT_MARKER),
        (_DELEGATE_REL, '"backendObj": model.backendObj'),
    ],
    "kryon.overlay": [
        (_CONTAINER_REL, _OVERLAY_MARKER),
        (_DIALOG_REL, None),
        (_LAYOUT_REL, "overlayEditingId"),
        (_DELEGATE_REL, "overlayMemberDialog"),
    ],
    "kryon.time_enhance": [(_TIME_REL, _TIME_MARK)],
    "kryon.countdown_anim": [(_COUNTDOWN_REL, _COUNTDOWN_MARK)],
}


def patch_status(root, feature_id):
    """某功能所需补丁的落地情况。

    返回 [{"file": 相对路径, "applied": bool, "reason": 说明}]。
    界面「组件安装后显示所需补丁的安装状态」靠它；安装算不算成功也以它为准
    （全 True 才算），这样「装了但没注入」不会被当成成功。
    """
    root = Path(root)
    backup_dir = root / _BACKUP_ROOT / _BACKUP_SUB
    out = []
    for rel, check in FEATURE_PATCH_SPECS.get(str(feature_id), []):
        p = root / rel
        item = {"file": rel.as_posix(), "applied": False, "reason": ""}
        if not p.is_file():
            # 判据里可能列了只在某个主程序版本存在的文件（新版把界面拆成了
            # WidgetsLayout / WidgetsLayoutDelegate）。缺文件按「该版本无此文件」
            # 计，不算未注入 —— 否则升级主程序后，老功能的验收会永远不过。
            item["applied"] = True
            item["reason"] = "该主程序版本无此文件"
        elif check is None:
            item["applied"] = True
            item["reason"] = "已装入主程序"
        elif check is _DIFF_FROM_BACKUP:
            orig = backup_dir / f"{p.name}.orig"
            if not orig.is_file():
                item["reason"] = "没有官方原版备份，无法判定"
            else:
                item["applied"] = orig.read_bytes() != p.read_bytes()
                item["reason"] = "已注入" if item["applied"] else "未注入"
        else:
            try:
                text, _ = _read(p)
                item["applied"] = check in text
                item["reason"] = "已注入" if item["applied"] else "未注入"
            except Exception as e:
                item["reason"] = f"读取失败: {e}"
        out.append(item)
    return out


# 本体的核心补丁已并入「组件增强」功能（kryon.extended_settings）：
# 高度/深度、排除科目、组件设置页 backendObj 注入都由那个 payload 提供
# （见 More_Settings-Features/features_src/kryon.extended_settings/ 与 PUBLIC_GROUPS，
#   锚点常量仍在本文件，payload 通过 host.ops(...) 取用，不复制）。
# 这样卸载该功能时补丁是真的撤掉，而不是留在主程序里。


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