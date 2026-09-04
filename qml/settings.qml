import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI
import ClassWidgets.Plugins

/*!
    Kryon 的更多设置 —— 主设置页。

    配置经官方插件配置通道持久化（plugins.configs.com.kryon.more_settings），
    通过 backend 槽读写（改动即保存）；主程序补丁的轮询 Timer 实时应用，无需重启。
*/

PluginPage {
    id: page
    pluginId: "com.kryon.more_settings"
    title: qsTr("更多设置")

    property var info: ({})
    property bool syncingControls: false
    // 时间组件本地配置（改动即整体提交）
    property var timeCfg: ({})
    property bool syncingTime: false

    Component.onCompleted: Qt.callLater(reload)
    onBackendChanged: { if (backend) Qt.callLater(reload) }

    function reload() {
        if (!backend) return
        var newInfo = backend.getConfig()
        if (newInfo) info = newInfo
        timeCfg = {
            time_animation: info.time_animation !== false,
            time_show_seconds: info.time_show_seconds !== false,
            time_show_date: info.time_show_date !== false,
            time_show_year: info.time_show_year !== false,
            time_show_month: info.time_show_month !== false,
            time_show_day: info.time_show_day !== false,
            time_show_weekday: info.time_show_weekday !== false,
            time_title_mode: info.time_title_mode || "side_by_side",
            time_alternate_interval: info.time_alternate_interval || 3000,
            time_alternate_animation: info.time_alternate_animation === true
        }
        syncControls()
    }

    function commitTime(key, value) {
        timeCfg[key] = value
        if (!page.syncingTime && backend) backend.setTimeConfig(timeCfg)
    }

    function syncControls() {
        page.syncingControls = true
        var d = info.display_height
        displaySlider.value = (d !== undefined && d !== null && d >= 0)
            ? d : (Configs.data.preferences.widgets_offset_y || 0)
        var hd = info.hide_depth
        hideSlider.value = (hd !== undefined && hd !== null) ? hd : 24
        page.syncingControls = false
    }

    Connections {
        target: backend
        function onConfigChanged() { page.reload() }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 16

        Text { typography: Typography.BodyStrong; text: qsTr("组件动画") }

        SettingCard {
            Layout.fillWidth: true
            title: qsTr("事件倒计时动画")
            description: qsTr("开启后内置“事件倒计时”组件的分钟/秒数字带滚动动画；关闭后静态显示。")

            Switch {
                checked: backend ? backend.getCountdownAnimation() : true
                onToggled: { if (backend) backend.setCountdownAnimation(checked) }
            }
        }

        Text { typography: Typography.BodyStrong; text: qsTr("时间组件") }

        SettingCard {
            Layout.fillWidth: true
            title: qsTr("时钟动画")
            description: qsTr("官方内置“时间”组件的时分秒数字更新时是否播放滚动动画。")

            Switch {
                checked: timeCfg.time_animation
                onToggled: commitTime("time_animation", checked)
            }
        }

        SettingCard {
            Layout.fillWidth: true
            title: qsTr("显示秒")
            description: qsTr("在官方内置“时间”组件中显示秒数。")

            Switch {
                checked: timeCfg.time_show_seconds
                onToggled: commitTime("time_show_seconds", checked)
            }
        }

        SettingCard {
            Layout.fillWidth: true
            title: qsTr("显示日期")
            description: qsTr("在组件标题栏显示日期。")

            Switch {
                checked: timeCfg.time_show_date
                onToggled: commitTime("time_show_date", checked)
            }
        }

        SettingCard {
            Layout.fillWidth: true
            title: qsTr("日期内容")
            description: qsTr("选择日期需要展示的部分。")

            RowLayout {
                spacing: 8
                Switch { text: qsTr("年"); checked: timeCfg.time_show_year; onToggled: commitTime("time_show_year", checked) }
                Switch { text: qsTr("月"); checked: timeCfg.time_show_month; onToggled: commitTime("time_show_month", checked) }
                Switch { text: qsTr("日"); checked: timeCfg.time_show_day; onToggled: commitTime("time_show_day", checked) }
            }
        }

        SettingCard {
            Layout.fillWidth: true
            title: qsTr("显示星期")
            description: qsTr("在组件标题栏显示星期几。")

            Switch {
                checked: timeCfg.time_show_weekday
                onToggled: commitTime("time_show_weekday", checked)
            }
        }

        SettingCard {
            Layout.fillWidth: true
            title: qsTr("日期与星期布局")
            description: qsTr("并排显示在同一行，或按间隔时间交替展示。")

            Segmented {
                currentIndex: timeCfg.time_title_mode === "alternate" ? 1 : 0
                onCurrentIndexChanged: commitTime("time_title_mode", currentIndex === 1 ? "alternate" : "side_by_side")
                SegmentedItem { text: qsTr("并排") }
                SegmentedItem { text: qsTr("交替") }
            }
        }

        SettingCard {
            Layout.fillWidth: true
            title: qsTr("交替间隔")
            description: qsTr("交替展示时，日期与星期各自停留的时间（毫秒），加减按钮以 100ms 调整。")
            enabled: timeCfg.time_title_mode === "alternate"

            RowLayout {
                spacing: 8
                Button {
                    text: "−"
                    implicitWidth: 36
                    onClicked: commitTime("time_alternate_interval", Math.max(500, (timeCfg.time_alternate_interval || 3000) - 100))
                }
                Text {
                    Layout.preferredWidth: 90
                    horizontalAlignment: Text.AlignHCenter
                    text: (timeCfg.time_alternate_interval || 3000) + " ms"
                }
                Button {
                    text: "+"
                    implicitWidth: 36
                    onClicked: commitTime("time_alternate_interval", Math.min(10000, (timeCfg.time_alternate_interval || 3000) + 100))
                }
            }
        }

        SettingCard {
            Layout.fillWidth: true
            title: qsTr("交替动画")
            description: qsTr("交替展示时，日期与星期切换是否带淡入淡出效果。")
            enabled: timeCfg.time_title_mode === "alternate"

            Switch {
                checked: timeCfg.time_alternate_animation
                onToggled: commitTime("time_alternate_animation", checked)
            }
        }

        Text { typography: Typography.BodyStrong; text: qsTr("小组件高度") }

        SettingCard {
            Layout.fillWidth: true
            icon.name: "ic_fluent_arrow_up_20_regular"
            title: qsTr("展示高度")
            description: qsTr("组件距屏幕顶部的距离（顶部停靠时生效）。")

            ColumnLayout {
                Layout.fillWidth: true
                Slider {
                    id: displaySlider
                    Layout.fillWidth: true
                    from: 0
                    to: 200
                    stepSize: 4
                    tickmarks: true
                    tickFrequency: 50
                    toolTip.text: Math.round(value) + " px"
                    onValueChanged: {
                        if (pressed && !page.syncingControls && backend)
                            backend.setDisplayHeight(value)
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Text { typography: Typography.Caption; text: qsTr("跟随默认偏移") }
                    Item { Layout.fillWidth: true }
                    Text { typography: Typography.Caption; text: Math.round(displaySlider.value) + " px" }
                }
            }
        }

        SettingCard {
            Layout.fillWidth: true
            icon.name: "ic_fluent_arrow_right_20_regular"
            title: qsTr("隐藏深度")
            description: qsTr("隐藏时保留在屏幕边缘的可点击宽度（默认 24 px）。")

            ColumnLayout {
                Layout.fillWidth: true
                Slider {
                    id: hideSlider
                    Layout.fillWidth: true
                    from: 0
                    to: 200
                    stepSize: 4
                    tickmarks: true
                    tickFrequency: 50
                    toolTip.text: Math.round(value) + " px"
                    onValueChanged: {
                        if (pressed && !page.syncingControls && backend)
                            backend.setHideDepth(value)
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Text { typography: Typography.Caption; text: "0 px" }
                    Item { Layout.fillWidth: true }
                    Text { typography: Typography.Caption; text: Math.round(hideSlider.value) + " px" }
                }
            }
        }

        SettingCard {
            Layout.fillWidth: true
            title: qsTr("说明")
            description: qsTr("本插件融合：事件倒计时动画开关、时间组件增强、小组件高度/深度、堆叠组件。\n安装后如未立即生效，请重启 Class Widgets 2；卸载插件后主程序恢复原始样式。")
        }
    }
}
