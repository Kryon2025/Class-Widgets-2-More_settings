import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import RinUI
import ClassWidgets.Plugins
import QtQuick.Effects

/*!
    Kryon 的扩展设置 —— 主设置页。

    配置经官方插件配置通道持久化（plugins.configs.com.kryon.more_settings），
    通过 backend 槽读写（改动即保存）；主程序补丁的轮询 Timer 实时应用，无需重启。
*/

PluginPage {
    id: page
    pluginId: "com.kryon.more_settings"
    title: qsTr("扩展设置")

    // 当前展开了设置页的功能 id（同一时刻只展开一个）
    property string openedFeature: ""
    // 补丁落地情况：点「检查补丁状态」才在专门区域展开，不占列表空间
    property bool showPatchStatus: false

    function toggleFeature(featureId) {
        page.openedFeature = (page.openedFeature === featureId) ? "" : featureId
    }

    Component.onCompleted: Qt.callLater(reload)
    onBackendChanged: { if (backend) Qt.callLater(reload) }

    function reload() {
        if (!backend) return
    }

    // 手动导入 payload：选好文件后交给后端做校验与落盘。
    // 用的是 Qt 自带的 FileDialog（QtQuick.Dialogs），不依赖 RinUI 是否提供。
    FileDialog {
        id: payloadDialog
        title: qsTr("选择要导入的 payload 文件")
        nameFilters: [
            qsTr("Payload 文件 (*.cwpayload *.zip)"),
            qsTr("所有文件 (*)")
        ]
        onAccepted: if (backend) backend.importPayloadFile(selectedFile)
    }

    Connections {
        target: backend
        function onConfigChanged() { page.reload() }

        // 装/卸的结果：用主程序自己的 InfoBar 和重启入口，
        // 交互与主程序装插件一致 —— 都是「已完成，重启后生效」。
        function onFeatureResult(featureId, featureName, ok, message) {
            page.notifyResult(featureName || featureId, ok, message)
        }
    }

    // 装过功能之后需要重启才生效（组件注册是进程级的，重启前新组件不会出现在添加列表里）
    property bool restartNeeded: false

    function notifyResult(featureName, ok, message) {
        if (!ok) {
            page.showInfoBar(qsTr("安装未完成"),
                             message || qsTr("补丁没有全部注入，已回到安装前的状态。"), false)
            return
        }
        page.restartNeeded = true
        // 顺带点亮主程序自己的「需要重启」状态，让重启按钮与主程序各处保持一致。
        // 这一步失败无所谓（可能只读），所以单独兜住。
        try { AppCentral.restartRequired = true } catch (e) {}
        page.showInfoBar(qsTr("安装完成"),
                         qsTr("%1 已安装完成，重启主程序后生效。").arg(featureName), true)
    }

    function showInfoBar(title, text, success) {
        try {
            floatLayer.createInfoBar({
                title: title,
                text: text,
                severity: success ? Severity.Success : Severity.Info,
                timeout: success ? 5000 : 8000
            })
        } catch (e) {
            console.warn("InfoBar 不可用:", e)
        }
    }

    // ── 卸载保护 ──────────────────────────────────────────────
    // 功能可以注册组件（目前只有堆叠组件）。卸载会把它的 QML 一起删掉，
    // 而「摆了哪些组件」记在主程序的 widgets_presets 里 —— 要是用户还把它
    // 摆在桌面上，下次启动时主程序加载不到会弹「主题加载失败」。
    // 所以先查出摆放，让用户选择是否一并移除。
    //
    // 移除走主程序自己的 WidgetsModel.removeInstance()，不是去改配置文件 ——
    // 这样配置和界面由主程序自己保持同步，也不会和它的写入打架。
    readonly property var featureWidgetIds: ({ "kryon.overlay": "com.overlay" })

    property string confirmUninstallId: ""
    property var confirmUninstallInstances: []

    function placedInstances(typeId) {
        var out = []
        if (typeof Configs === "undefined" || !Configs.data || !Configs.data.preferences)
            return out
        var presets = Configs.data.preferences.widgets_presets || {}
        for (var name in presets) {
            var list = presets[name] || []
            for (var i = 0; i < list.length; ++i)
                if (list[i] && list[i].type_id === typeId)
                    out.push(list[i].instance_id)
        }
        return out
    }

    function requestUninstall(featureId) {
        var typeId = page.featureWidgetIds[featureId]
        var ids = typeId ? page.placedInstances(typeId) : []
        if (ids.length > 0) {
            page.confirmUninstallInstances = ids
            page.confirmUninstallId = featureId
            return
        }
        page.doUninstall(featureId, false)
    }

    function doUninstall(featureId, removeInstances) {
        if (removeInstances) {
            for (var i = 0; i < page.confirmUninstallInstances.length; ++i) {
                try {
                    WidgetsModel.removeInstance(page.confirmUninstallInstances[i])
                } catch (e) {
                    console.warn("移除组件摆放失败:", e)
                }
            }
        }
        page.confirmUninstallId = ""
        page.confirmUninstallInstances = []
        if (backend)
            backend.uninstallFeature(featureId)
        if (page.openedFeature === featureId)
            page.openedFeature = ""
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 16

        // ── 功能安装器 ────────────────────────────────────────────
        // 装了什么只由这里决定：清单里的功能默认全是「未安装」，
        // 只有点过安装的才会从远端下载到本机。
        SettingCard {
            Layout.fillWidth: true
            title: qsTr("当前 ClassWidgets 2 版本")
            description: (backend && backend.cw2Version !== "")
                ? backend.cw2Version
                : qsTr("未识别到主程序版本，将只允许安装已测试的版本")
        }

        SettingCard {
            Layout.fillWidth: true
            title: qsTr("当前插件安装器版本")
            description: (backend && backend.installerVersion !== "")
                ? backend.installerVersion : "—"
        }

        // 与主程序的 RestartButton 同一套：同一个图标、同一个入口。
        SettingCard {
            Layout.fillWidth: true
            visible: page.restartNeeded
                     || (typeof AppCentral !== "undefined" && AppCentral.restartRequired)
            title: qsTr("需要重启")
            description: qsTr("功能已安装完成，重启主程序后生效。")

            Button {
                highlighted: true
                icon.name: "ic_fluent_arrow_counterclockwise_20_regular"
                text: qsTr("重启以完成安装")
                onClicked: {
                    if (typeof AppCentral !== "undefined")
                        AppCentral.restart()
                }
            }
        }

        // ── 功能列表 ──────────────────────────────────────────────
        // 样式对齐主程序「设置 → 插件 → 你的插件」页：
        // Clip 行 + 左侧 48×48 圆角图标 + 中间名称/徽章/说明
        // + 右侧兼容性警告图标、启用开关、更多菜单。
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4

            Text {
                typography: Typography.BodyStrong
                text: qsTr("功能")
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 12

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Button {
                        text: qsTr("检查当前功能更新")
                        enabled: backend && !backend.installerBusy
                        onClicked: if (backend) backend.refreshInstaller()
                    }

                    Button {
                        text: qsTr("导入本地文件…")
                        enabled: backend && !backend.installerBusy
                        onClicked: payloadDialog.open()
                    }

                    Item { Layout.fillWidth: true }

                    Text {
                        Layout.maximumWidth: 420
                        visible: text !== ""
                        elide: Text.ElideRight
                        typography: Typography.Caption
                        color: Colors.proxy.textSecondaryColor
                        text: backend ? backend.installerLog : ""
                    }
                }

                InfoBar {
                    Layout.fillWidth: true
                    title: qsTr("说明")
                    text: qsTr("每个功能单独安装，只有你点过安装的才会下载到本机。"
                               + "安装后会即时向主程序注入补丁 —— 「装了」和「真的注入进去了」"
                               + "是两件事，点下方「检查补丁状态」看每个功能的补丁落地情况；"
                               + "只装没注入不算装成功。")
                    severity: Severity.Info
                }

                // 补丁落地情况：点按钮才展开。放在这里而不是每个功能行下面 ——
                // 列表要干净，而「装了没注入」这种问题只有主动去查的时候才关心。
                Button {
                    text: page.showPatchStatus ? qsTr("收起补丁状态") : qsTr("检查补丁状态")
                    onClicked: page.showPatchStatus = !page.showPatchStatus
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    visible: page.showPatchStatus
                    spacing: 10

                    Repeater {
                        model: (page.showPatchStatus && backend) ? backend.featureList : []
                        delegate: ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Text {
                                typography: Typography.BodyStrong
                                text: modelData.name
                            }
                                        // 补丁落地情况。「装了」和「真的注入进去了」是两件事，
                                        // 只装不注入等于没装，所以必须并排显示，缺一项就是红的。
                                        Repeater {
                                            model: (modelData.installed !== "" && modelData.patches)
                                                ? modelData.patches : []

                                            delegate: Text {
                                                required property var modelData
                                                Layout.fillWidth: true
                                                wrapMode: Text.WordWrap
                                                typography: Typography.Caption
                                                color: modelData.applied
                                                       ? "#2E7D32" : Colors.proxy.systemCriticalColor
                                                text: (modelData.applied
                                                       ? (modelData.reason === "已装入主程序"
                                                          ? qsTr("✓ 已装入主程序 ")
                                                          : qsTr("✓ 补丁已注入 "))
                                                       : qsTr("✗ 补丁未注入 "))
                                                      + modelData.file.split("/").pop()
                                                      + (modelData.applied
                                                         ? ""
                                                         : "（" + (modelData.reason || qsTr("未知")) + "）")
                                            }
                                        }
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    visible: !backend || backend.featureList.length === 0
                    wrapMode: Text.WordWrap
                    typography: Typography.Caption
                    color: Colors.proxy.textSecondaryColor
                    text: qsTr("尚无功能列表，点上方「检查当前功能更新」获取适配清单。")
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    Repeater {
                        model: backend ? backend.featureList : []

                        delegate: ColumnLayout {
                            id: featureRow
                            // 面板一旦展开过就保留已加载的设置页，收起时不闪成空白
                            property bool rowEverOpened: false
                            readonly property bool opened:
                                page.openedFeature === modelData.id && rowEverOpened
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 4

                            Clip {
                                id: featureCard
                                Layout.fillWidth: true
                                Layout.minimumHeight: 70

                                // 卡片底色（原来这里是液态玻璃折射特效，已去掉）。
                                // 用 Clip 自带的 background 槽、而不是塞一个子 Rectangle：
                                // 这样会替换掉 Clip 默认的方形底色，圆角下不会再露出尖角。
                                // 配色与主程序广场的 PluginSection 一致（卡片色 + 控件描边）。
                                radius: 12
                                // 展开时下两角收平，与下面的设置面板贴成一体（抽屉感）
                                bottomLeftRadius: featureRow.opened ? 0 : 12
                                bottomRightRadius: featureRow.opened ? 0 : 12
                                background: Rectangle {
                                    anchors.fill: parent
                                    radius: featureCard.radius
                                    color: Colors.proxy.cardColor
                                    border.color: Colors.proxy.controlBorderColor
                                    border.width: 1
                                }

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 12

                                    // 左：图标（与主程序插件行同尺寸、同圆角）
                                    Rectangle {
                                        color: Colors.proxy.backgroundColor
                                        radius: 12
                                        width: 48
                                        height: 48
                                        border.color: Colors.proxy.controlBorderColor
                                        border.width: 1

                                        Icon {
                                            anchors.fill: parent
                                            size: 32
                                            opacity: modelData.installed !== "" ? 1 : 0.5
                                            name: modelData.installed !== ""
                                                  ? "ic_fluent_checkmark_circle_20_filled"
                                                  : "ic_fluent_arrow_download_20_regular"
                                        }
                                    }

                                    // 中：名称 + 徽章 + 版本/说明 + 补丁状态
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2

                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 8

                                            InfoBadge {
                                                visible: modelData.installed === ""
                                                text: qsTr("未安装")
                                                severity: Severity.Info
                                                solid: false
                                            }
                                            InfoBadge {
                                                visible: modelData.installed !== ""
                                                         && !modelData.tested
                                                text: qsTr("未测试")
                                                severity: Severity.Warning
                                                solid: false
                                            }
                                            InfoBadge {
                                                visible: modelData.status === "upgradable"
                                                text: qsTr("可更新")
                                                severity: Severity.Success
                                                solid: false
                                            }

                                            Text {
                                                Layout.fillWidth: true
                                                text: modelData.name
                                                wrapMode: Text.NoWrap
                                                elide: Text.ElideRight
                                            }
                                        }

                                        Text {
                                            Layout.fillWidth: true
                                            wrapMode: Text.NoWrap
                                            elide: Text.ElideRight
                                            typography: Typography.Caption
                                            color: Colors.proxy.textSecondaryColor
                                            text: modelData.installed === ""
                                                ? (modelData.summary || "")
                                                : qsTr("已安装 ") + modelData.installed
                                                  + (modelData.summary ? "　" + modelData.summary : "")
                                        }


                                        Text {
                                            Layout.fillWidth: true
                                            visible: page.confirmUninstallId === modelData.id
                                            color: Colors.proxy.systemCriticalColor
                                            wrapMode: Text.WordWrap
                                            typography: Typography.Caption
                                            text: qsTr("桌面上还摆着 %1 个该组件。卸载会把它的文件一起删掉，"
                                                       + "不移除摆放的话下次启动主程序会加载失败。")
                                                  .arg(page.confirmUninstallInstances.length)
                                        }
                                    }

                                    // 右：兼容性警告 + 启用开关 + 展开按钮
                                    RowLayout {
                                        Layout.alignment: Qt.AlignRight
                                        spacing: 18

                                        Icon {
                                            size: 24
                                            visible: modelData.installed !== "" && !modelData.matched
                                            color: Colors.proxy.systemCriticalColor
                                            name: "ic_fluent_warning_20_filled"

                                            HoverHandler { id: compatHover }
                                            ToolTip.visible: compatHover.hovered
                                            ToolTip.text: qsTr("当前主程序版本不在该功能的适配范围内，"
                                                               + "可能无法正常工作。")
                                        }

                                        Switch {
                                            visible: modelData.installed !== ""
                                                     && page.confirmUninstallId !== modelData.id
                                            text: checked ? qsTr("已启用") : qsTr("已禁用")
                                            checked: modelData.enabled
                                            onToggled: {
                                                if (backend)
                                                    backend.setFeatureEnabled(modelData.id, checked)
                                            }
                                        }

                                        // 展开/收起按钮：图标随状态旋转 180°（与 RinUI 的 Expander 同做法）
                                        ToolButton {
                                            id: expandBtn
                                            flat: true
                                            icon.name: "ic_fluent_chevron_down_20_regular"
                                            rotation: featureRow.opened ? 180 : 0

                                            Behavior on rotation {
                                                NumberAnimation {
                                                    duration: Utils.appearanceSpeed
                                                    easing.type: Easing.OutQuint
                                                }
                                            }

                                            onClicked: {
                                                featureRow.rowEverOpened = true
                                                page.toggleFeature(modelData.id)
                                            }

                                            HoverHandler { id: expandHover }
                                            ToolTip.visible: expandHover.hovered
                                            ToolTip.text: featureRow.opened
                                                ? qsTr("收起设置") : qsTr("展开设置")
                                        }
                                    }
                                }
                            }

                            // ── 设置面板（抽屉）──────────────────────────────────
                            // 点右侧的展开按钮后，这块从 0 高度动画展开：安装/更新、
                            // 功能自己的设置项、底部的红色卸载按钮都在这里面。
                            Item {
                                id: featurePanel
                                z: -1
                                Layout.fillWidth: true
                                // 抵消外层 spacing(4)：面板顶边正好接住卡片底边
                                // 边挨边但不重叠，避免两层半透明底色叠在一起更亮
                                Layout.topMargin: -4
                                clip: true

                                implicitHeight: featureRow.opened ? panelBody.implicitHeight : 0
                                opacity: featureRow.opened ? 1 : 0

                                Behavior on implicitHeight {
                                    NumberAnimation {
                                        duration: Utils.animationSpeedExpander
                                        easing.type: featureRow.opened ? Easing.OutQuint : Easing.InQuint
                                    }
                                }
                                Behavior on opacity {
                                    NumberAnimation { duration: Utils.appearanceSpeed }
                                }

                                Clip {
                                    id: panelBody
                                    width: featurePanel.width
                                    implicitHeight: panelCol.implicitHeight
                                    // 上两角收平贴住卡片，下两角圆角收尾
                                    topLeftRadius: 0
                                    topRightRadius: 0
                                    bottomLeftRadius: 12
                                    bottomRightRadius: 12
                                    color: Colors.proxy.cardColor
                                    border.width: 0

                                    ColumnLayout {
                                        id: panelCol
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.top: parent.top
                                        spacing: 0

                                        // ① 安装 / 更新
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Layout.margins: 12
                                            spacing: 8

                                            Button {
                                                visible: modelData.installed === ""
                                                         || modelData.status === "upgradable"
                                                enabled: backend && !backend.installerBusy
                                                         && modelData.target !== ""
                                                icon.name: modelData.installed === ""
                                                    ? "ic_fluent_arrow_download_20_regular"
                                                    : "ic_fluent_arrow_sync_20_regular"
                                                text: modelData.installed === ""
                                                    ? qsTr("安装")
                                                    : qsTr("更新到 %1").arg(modelData.target)
                                                onClicked: if (backend)
                                                    backend.installFeature(modelData.id, "")
                                            }

                                            Text {
                                                Layout.fillWidth: true
                                                visible: modelData.installed === ""
                                                         && modelData.target === ""
                                                typography: Typography.Caption
                                                color: Colors.proxy.textSecondaryColor
                                                wrapMode: Text.WordWrap
                                                text: qsTr("当前主程序版本还没有适配的功能包，暂时装不了。")
                                            }

                                            Item { Layout.fillWidth: true }
                                        }

                                        // ② 功能自己的设置项：扁平成一整块，不再是一张张独立卡片
                                        Loader {
                                            Layout.fillWidth: true
                                            active: featureRow.rowEverOpened && backend
                                                    && backend.featureSettingsUrl(modelData.id) !== ""
                                            source: active
                                                ? backend.featureSettingsUrl(modelData.id) : ""
                                            // 把插件对象注入进去：功能设置页要读的是插件配置
                                            onLoaded: if (item) item.backend = backend
                                        }

                                        // ③ 底部：卸载（红色）
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Layout.margins: 12
                                            spacing: 8

                                            Item { Layout.fillWidth: true }

                                            Button {
                                                highlighted: true
                                                color: Colors.proxy.systemCriticalColor
                                                visible: page.confirmUninstallId === modelData.id
                                                enabled: backend && !backend.installerBusy
                                                icon.name: "ic_fluent_delete_20_regular"
                                                text: page.confirmUninstallInstances.length > 0
                                                    ? qsTr("卸载并移除摆放") : qsTr("确认卸载")
                                                onClicked: page.doUninstall(modelData.id, true)
                                            }

                                            Button {
                                                visible: page.confirmUninstallId === modelData.id
                                                text: qsTr("取消")
                                                onClicked: {
                                                    page.confirmUninstallId = ""
                                                    page.confirmUninstallInstances = []
                                                }
                                            }

                                            Button {
                                                highlighted: true
                                                color: Colors.proxy.systemCriticalColor
                                                visible: modelData.installed !== ""
                                                         && page.confirmUninstallId !== modelData.id
                                                enabled: backend && !backend.installerBusy
                                                icon.name: "ic_fluent_delete_20_regular"
                                                text: qsTr("卸载")
                                                onClicked: page.requestUninstall(modelData.id)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }




        SettingCard {
            Layout.fillWidth: true
            title: qsTr("说明")
            description: qsTr("本插件融合：事件倒计时动画开关、时间组件增强、小组件高度/深度、堆叠组件。\n各功能按需单独安装，安装时即时向主程序注入补丁，无需重启；卸载会把补丁一并撤除，主程序恢复原始样式。\n每个功能下方会列出它所需补丁的落地情况 —— 只装没注入不算装成功，卸载重装即可重试。")
        }
    }
}
