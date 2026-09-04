// [patched by com.kryon.more_settings v2]
// 内置"事件倒计时"组件增强版：分钟/秒数字支持动画开关。
// 动画开关由插件 com.kryon.more_settings 在主程序设置页中控制，
// 组件通过轮询 Configs.data.plugins.configs 实时生效。
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI
import ClassWidgets.Theme
import Qt5Compat.GraphicalEffects

Widget {
    id: root
    text: {
        AppCentral.translator.language
        return qsTr("Remaining")
    }
    property var countdown: AppCentral.scheduleRuntime.remainingTime || { "minutes": 0, "seconds": 0 }

    // 动画开关（插件 com.kryon.more_settings 在主程序设置页控制，默认开启）
    property bool animEnabled: true
    function refreshAnim() {
        var cfg = null
        try {
            cfg = Configs.data.plugins.configs["com.kryon.more_settings"]
        } catch (e) {
            cfg = null
        }
        animEnabled = cfg ? cfg.countdown_animation !== false : true
    }
    Timer {
        interval: 300
        running: visible  // 组件可见时才轮询
        repeat: true
        onTriggered: root.refreshAnim()
    }

    // 统一布局，用 RowLayout 并根据 miniMode 控制内部排列
    RowLayout {
        anchors.centerIn: parent
        spacing: miniMode ? 12 : 0

        ProgressRing {
            // miniMode 下进度环
            Layout.preferredWidth: 24
            Layout.preferredHeight: 24
            Layout.alignment: Qt.AlignCenter
            value: AppCentral.scheduleRuntime.progress
            visible: miniMode
            strokeWidth: 4
            backgroundColor: Qt.alpha(Colors.proxy.controlStrongColor, 0.2)
            primaryColor: progressBar.primaryColor
        }

        // 左侧：文字 + 时间
        ColumnLayout {
            spacing: 2
            Layout.alignment: Qt.AlignVCenter

            RowLayout {
                spacing: 0
                Layout.topMargin: miniMode ? 0 : -4
                Layout.alignment: Qt.AlignHCenter

                Loader {
                    id: minuteDigits
                    sourceComponent: root.animEnabled ? animatedMinute : staticMinute
                }
                Title {
                    Layout.bottomMargin: font.pixelSize * 0.1
                    text: ":"
                }
                Loader {
                    id: secondDigits
                    sourceComponent: root.animEnabled ? animatedSecond : staticSecond
                }
            }

            // 进度条仅在非 miniMode 下显示在下方
            ProgressBar {
                id: progressBar
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: 82
                Layout.preferredHeight: 4
                value: AppCentral.scheduleRuntime.progress
                visible: !miniMode
                primaryColor: {
                    switch (AppCentral.scheduleRuntime.currentStatus) {
                        case "free": case "break": return Theme.isDark()? "#46CEA3" : "#2eaa76"
                        case "class": return Theme.isDark()? "#e4a274" : "#dd986f"
                        default: return "#605ed2"
                    }
                }
            }
        }
    }

    Component {
        id: animatedMinute
        AnimatedDigits {
            value: root.countdown.minute || "00"
        }
    }
    Component {
        id: animatedSecond
        AnimatedDigits {
            value: (root.countdown.second + "").padStart(2, "0") || "00"
        }
    }
    Component {
        id: staticMinute
        Title {
            text: root.countdown.minute || "00"
        }
    }
    Component {
        id: staticSecond
        Title {
            text: (root.countdown.second + "").padStart(2, "0") || "00"
        }
    }
}
