import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI
import ClassWidgets.Plugins

// 重叠组件设置页：轮播间隔 + 成员组件管理
// 成员组件主要入口：桌面组件编辑界面右键 → “编辑重叠组件”

SettingsLayout {
    property int intervalValue: 5000
    property int secValue: 5
    onSecValueChanged: settings.interval_ms = secValue * 1000
    Component.onCompleted: {
        secValue = (settings.interval_ms || 5000) / 1000
    }

    // 插件后端：优先用主程序补丁注入的 backendObj（WidgetsContainer 打开设置时注入），
    // 兜底再从组件定义列表中查找
    property var backendObj: null
    property var overlayBackend: {
        if (backendObj) return backendObj
        if (typeof WidgetsModel !== "undefined" && WidgetsModel.definitionsList) {
            var defs = WidgetsModel.definitionsList
            for (var i = 0; i < defs.length; i++) {
                if (defs[i].typeId === "com.overlay") return defs[i].backendObj || defs[i].backend_obj
                if (defs[i].id === "com.overlay") return defs[i].backendObj || defs[i].backend_obj
            }
        }
        return null
    }

    // 成员 typeId -> 显示名
    function nameOf(typeId) {
        if (typeof WidgetsModel !== "undefined" && WidgetsModel.definitionsList) {
            var defs = WidgetsModel.definitionsList
            for (var i = 0; i < defs.length; i++) {
                if (defs[i].id === typeId || defs[i].typeId === typeId)
                    return defs[i].name || typeId
            }
        }
        return typeId
    }

    SettingCard {
        Layout.fillWidth: true
        title: "轮播间隔"
        description: "每个组件停留后切换到下一个的时间（秒），加减按钮以 1 秒调整。"

        RowLayout {
            spacing: 8
            Button {
                text: "−"
                implicitWidth: 36
                onClicked: secValue = Math.max(1, secValue - 1)
            }
            Text {
                Layout.preferredWidth: 70
                horizontalAlignment: Text.AlignHCenter
                text: secValue + " 秒"
                font.bold: true
            }
            Button {
                text: "+"
                implicitWidth: 36
                onClicked: secValue = Math.min(60, secValue + 1)
            }
        }
    }

    SettingCard {
        Layout.fillWidth: true
        title: "显示切换条"
        description: "在组件右侧显示“切换”按钮，点击可手动切换到下一个成员组件。"

        Switch {
            checked: settings.show_switch_bar !== false
            onCheckedChanged: settings.show_switch_bar = checked
        }
    }

    SettingCard {
        Layout.fillWidth: true
        title: "成员组件"
        description: "已叠加到本组件内的成员，可在桌面组件编辑界面中右键“编辑重叠组件”添加/移除。"

        ColumnLayout {
            spacing: 4
            Repeater {
                model: overlayBackend ? overlayBackend.getMembers() : []
                delegate: RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Text {
                        Layout.fillWidth: true
                        text: (index + 1) + ". " + nameOf(modelData.typeId)
                        elide: Text.ElideMiddle
                    }
                    Button {
                        text: "移除"
                        implicitWidth: 52
                        implicitHeight: 26
                        onClicked: {
                            if (overlayBackend) overlayBackend.removeMember(modelData.key)
                        }
                    }
                }
            }
        }
    }
}
