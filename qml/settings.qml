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
    // 排除科目（按课表所选科目判定，与课程标题无关）
    property bool excludedEnabled: false
    property var excludedSubjects: []
    property var subjectChoices: []

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
        reloadExcluded()
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

    function saveExcluded() {
        if (backend) backend.setExcludedLessonConfig(
            excludedEnabledSwitch.checked, page.excludedSubjects)
    }

    function reloadExcluded() {
        if (!backend) return
        var cfg = backend.getExcludedLessonConfig()
        page.excludedEnabled = cfg ? (cfg.enabled === true) : false
        page.excludedSubjects = (cfg && cfg.subjects) ? cfg.subjects.slice() : []
    }

    function allSubjectNames() {
        var out = []
        try {
            var s = AppCentral.scheduleRuntime.subjects || []
            for (var i = 0; i < s.length; i++) out.push(s[i].name)
        } catch (e) {}
        return out
    }

    function refreshSubjectMenu() {
        var picked = page.excludedSubjects
        page.subjectChoices = page.allSubjectNames().filter(function (n) {
            return picked.indexOf(n) < 0
        })
    }

    function addExcludedSubject(name) {
        if (!name || page.excludedSubjects.indexOf(name) >= 0) return
        if (page.excludedSubjects.length >= 20) return
        var arr = page.excludedSubjects.slice()
        arr.push(name)
        page.excludedSubjects = arr
        saveExcluded()
    }

    function removeExcludedSubject(name) {
        page.excludedSubjects = page.excludedSubjects.filter(function (n) {
            return n !== name
        })
        saveExcluded()
    }

    function subjectColor(name) {
        try {
            var s = AppCentral.scheduleRuntime.subjects || []
            for (var i = 0; i < s.length; i++) {
                if (s[i].name === name) return s[i].color || "#888888"
            }
        } catch (e) {}
        return "#888888"
    }

    Connections {
        target: backend
        function onConfigChanged() { page.reload() }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 16

        SettingExpander {
            Layout.fillWidth: true
            icon.name: "ic_fluent_timer_20_regular"
            title: qsTr("组件动画")
            description: qsTr("内置「事件倒计时」组件的数字滚动动画开关。")
            expanded: false

        SettingCard {
            Layout.fillWidth: true
            title: qsTr("事件倒计时动画")
            description: qsTr("开启后内置“事件倒计时”组件的分钟/秒数字带滚动动画；关闭后静态显示。")

            Switch {
                checked: backend ? backend.getCountdownAnimation() : true
                onToggled: { if (backend) backend.setCountdownAnimation(checked) }
            }
        }

        }

        SettingExpander {
            Layout.fillWidth: true
            icon.name: "ic_fluent_clock_20_regular"
            title: qsTr("时间组件")
            description: qsTr("增强官方内置「时间」组件：数字滚动动画、显示秒/日期/星期、并排或交替布局。")
            expanded: false

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

        }

        SettingExpander {
            Layout.fillWidth: true
            icon.name: "ic_fluent_resize_20_regular"
            title: qsTr("小组件高度 / 深度")
            description: qsTr("调节桌面组件的展示高度，以及隐藏时保留在屏幕边缘的可点击宽度。")
            expanded: false

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

        }

        SettingExpander {
            Layout.fillWidth: true
            icon.name: "ic_fluent_eye_off_20_regular"
            title: qsTr("特定课程不隐藏")
            description: qsTr("当前课表科目在下方列表中时，主程序「在课堂中隐藏」不触发。")
            expanded: false

        SettingCard {
            Layout.fillWidth: true
            title: qsTr("排除科目")
            description: qsTr("开启后，当前课表科目在下方列表中时，主程序“在课堂中隐藏”不触发。按课程表编辑时该时间段所选科目判定，与课程标题无关。最多添加 20 个。")

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8
                Switch {
                    id: excludedEnabledSwitch
                    text: qsTr("启用")
                    checked: page.excludedEnabled
                    onToggled: saveExcluded()
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4

                        Text {
                            visible: page.excludedSubjects.length === 0
                            typography: Typography.Caption
                            text: qsTr("尚未添加科目")
                        }

                        Repeater {
                            model: page.excludedSubjects
                            delegate: RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                Rectangle {
                                    width: 6
                                    height: 20
                                    radius: 3
                                    color: page.subjectColor(modelData)
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData
                                    elide: Text.ElideRight
                                }
                                ToolButton {
                                    icon.name: "ic_fluent_delete_20_regular"
                                    onClicked: page.removeExcludedSubject(modelData)
                                }
                            }
                        }
                    }

                    ToolButton {
                        Layout.alignment: Qt.AlignTop
                        icon.name: "ic_fluent_add_20_regular"
                        enabled: page.excludedSubjects.length < 20
                        onClicked: subjectMenu.open()
                    }
                }

                Menu {
                    id: subjectMenu
                    height: implicitHeight
                    onAboutToShow: page.refreshSubjectMenu()
                    // 预置固定数量项、用 visible 控制显隐：不动态增删 items。
                    // RinUI 的 Menu 在动态插入项的布局/生命周期上不稳，固定项最稳（同官方 FilterToolbar）。
                    // 上限 20 个科目，与加号按钮的 enabled 一致。
                    Repeater {
                        model: 20
                        MenuItem {
                            required property int index
                            visible: index < page.subjectChoices.length
                            text: index < page.subjectChoices.length ? page.subjectChoices[index] : ""
                            onTriggered: {
                                if (index < page.subjectChoices.length) {
                                    page.addExcludedSubject(page.subjectChoices[index])
                                    subjectMenu.close()
                                }
                            }
                        }
                    }
                }
            }
        }

        }

        SettingExpander {
            Layout.fillWidth: true
            icon.name: "ic_fluent_arrow_sync_20_regular"
            title: qsTr("补丁注入")
            description: qsTr("向主程序注入补丁的状态；异常时可手动重新注入。")
            expanded: false

        SettingCard {
            Layout.fillWidth: true
            title: qsTr("补丁注入状态")
            description: qsTr("安装插件时会自动向主程序注入所需补丁（组件动画开关、时间组件增强、堆叠组件、小组件高度）。注入后需重启主程序生效；状态异常时可手动重新注入。")

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8
                Text {
                    id: patchStatusText
                    text: backend ? backend.getPatchStatus() : qsTr("未知")
                }
                Button {
                    text: qsTr("重新注入补丁")
                    onClicked: {
                        if (backend) {
                            backend.reinstallPatches()
                            patchStatusText.text = backend.getPatchStatus()
                        }
                    }
                }
            }
        }

        }

        SettingCard {
            Layout.fillWidth: true
            title: qsTr("说明")
            description: qsTr("本插件融合：事件倒计时动画开关、时间组件增强、小组件高度/深度、堆叠组件。\n安装后如未立即生效，请重启 Class Widgets 2；卸载插件后主程序恢复原始样式。\n若补丁未注入成功，请卸载此插件，并反馈给开发者。")
        }
    }
}
