// [patched by com.kryon.more_settings v2]
// 内置"时间"组件增强版：数字滚动动画、秒、日期、星期、布局均可开关/配置。
// 选项由插件 com.kryon.more_settings 在主程序设置页中控制，
// 组件通过轮询 Configs.data.plugins.configs 实时生效。
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI
import ClassWidgets.Theme

Widget {
    id: root
    // 时间数据，由主程序内置 backend.getDateTime() 返回
    property var dateTime: {
        "year": 1900,
        "month": 1,
        "day": 1,
        "weekday": 0,
        "hour": 0,
        "minute": 0,
        "second": 0
    }

    // 配置（轮询 Configs 实时生效）
    property bool animEnabled: true
    property bool showSeconds: true
    property bool showDate: true
    property bool showYear: true
    property bool showMonth: true
    property bool showDay: true
    property bool showWeekday: true
    property string titleMode: "side_by_side"
    property int alternateInterval: 3000
    property bool alternateAnimation: false
    // 交替模式下当前是否显示星期
    property bool showWeekdayLine: false
    // 交替淡入淡出时长（关闭动画时为 0）
    property int fadeDuration: alternateAnimation ? 300 : 0

    function refreshCfg() {
        var cfg = null
        try {
            cfg = Configs.data.plugins.configs["com.kryon.more_settings"]
        } catch (e) {
            cfg = null
        }
        animEnabled = cfg ? cfg.time_animation !== false : true
        showSeconds = cfg ? cfg.time_show_seconds !== false : true
        showDate = cfg ? cfg.time_show_date !== false : true
        showYear = cfg ? cfg.time_show_year !== false : true
        showMonth = cfg ? cfg.time_show_month !== false : true
        showDay = cfg ? cfg.time_show_day !== false : true
        showWeekday = cfg ? cfg.time_show_weekday !== false : true
        titleMode = cfg ? (cfg.time_title_mode || "side_by_side") : "side_by_side"
        alternateInterval = cfg ? (cfg.time_alternate_interval || 3000) : 3000
        alternateAnimation = cfg ? cfg.time_alternate_animation === true : false
        fadeDuration = alternateAnimation ? 300 : 0
    }
    Timer {
        interval: 300
        running: visible  // 组件可见时才轮询
        repeat: true
        onTriggered: root.refreshCfg()
    }

    // 按设置筛选年月日后拼接日期字符串
    function dateString() {
        var parts = []
        if (showYear) parts.push(dateTime.year + "年")
        if (showMonth) parts.push(dateTime.month + "月")
        if (showDay) parts.push(dateTime.day + "日")
        return parts.join("")
    }

    function weekdayString() {
        return Qt.locale().dayName(dateTime.weekday, Locale.LongFormat)
    }

    // 日期总开关开启且至少展示一个日期部分
    function hasDate() {
        return showDate && root.dateString() !== ""
    }

    // 自定义标题区：并排模式单行展示；交替模式锁定宽度（取两者较宽），居中轮流切换
    subtitle: [
        Subtitle {
            id: combinedText
            visible: titleMode === "side_by_side"
            text: {
                if (root.hasDate() && showWeekday)
                    return root.dateString() + "  " + root.weekdayString()
                if (root.hasDate()) return root.dateString()
                if (showWeekday) return root.weekdayString()
                return ""
            }
        },
        Item {
            visible: titleMode === "alternate"
            implicitWidth: Math.max(dateText.implicitWidth, weekText.implicitWidth)
            implicitHeight: Math.max(dateText.implicitHeight, weekText.implicitHeight)

            Subtitle {
                id: dateText
                anchors.centerIn: parent
                text: root.dateString()
                visible: root.hasDate()
                opacity: (!root.hasDate() || !showWeekday)
                         ? 1
                         : (root.showWeekdayLine ? 0 : 1)
                Behavior on opacity {
                    NumberAnimation { duration: root.fadeDuration; easing.type: Easing.OutQuad }
                }
            }
            Subtitle {
                id: weekText
                anchors.centerIn: parent
                text: root.weekdayString()
                visible: showWeekday
                opacity: (!root.hasDate() || !showWeekday)
                         ? 1
                         : (root.showWeekdayLine ? 1 : 0)
                Behavior on opacity {
                    NumberAnimation { duration: root.fadeDuration; easing.type: Easing.OutQuad }
                }
            }
        }
    ]

    // 交替展示定时器
    Timer {
        id: alternateTimer
        interval: Math.max(500, alternateInterval)
        running: root.hasDate() && showWeekday && titleMode === "alternate"
        repeat: true
        onTriggered: root.showWeekdayLine = !root.showWeekdayLine
    }

    RowLayout {
        anchors.centerIn: parent
        spacing: 0
        Loader {
            id: hourDigits
            sourceComponent: root.animEnabled ? animatedHour : staticHour
        }
        Title {
            Layout.bottomMargin: font.pixelSize * 0.1
            text: ":"
        }
        Loader {
            id: minuteDigits
            sourceComponent: root.animEnabled ? animatedMinute : staticMinute
        }
        Title {
            Layout.bottomMargin: font.pixelSize * 0.1
            text: ":"
            visible: root.showSeconds
        }
        Loader {
            id: secondDigits
            sourceComponent: root.animEnabled ? animatedSecond : staticSecond
            visible: root.showSeconds
        }

        Timer {
            interval: 500
            running: true
            repeat: true
            onTriggered: {
                dateTime = backend.getDateTime()
            }
        }
    }

    Component {
        id: animatedHour
        AnimatedDigits {
            value: dateTime.hour || "00"
        }
    }
    Component {
        id: animatedMinute
        AnimatedDigits {
            value: dateTime.minute || "00"
        }
    }
    Component {
        id: animatedSecond
        AnimatedDigits {
            value: dateTime.second || "00"
        }
    }
    Component {
        id: staticHour
        Title {
            text: dateTime.hour || "00"
        }
    }
    Component {
        id: staticMinute
        Title {
            text: dateTime.minute || "00"
        }
    }
    Component {
        id: staticSecond
        Title {
            text: dateTime.second || "00"
        }
    }

    Component.onCompleted: {
        Qt.callLater(function() {
            dateTime = backend.getDateTime()
        })
    }
}
