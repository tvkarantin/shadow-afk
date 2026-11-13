import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: screen
    color: "#0b1119"
    property var account: telegram.status
    property real scaleUnit: Math.min(1.2, width / 1250)

    gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0; color: "#0b1622" }
        GradientStop { position: 0.5; color: "#0b1119" }
        GradientStop { position: 1; color: "#0a1c2d" }
    }

    component TextLine: Label {
        color: "#f6f8fc"
        textFormat: Text.PlainText
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
    }
    component TelegramButton: Button {
        id: control
        property bool accent: false
        Layout.fillWidth: true
        implicitHeight: 59 * screen.scaleUnit
        enabled: screen.account.configured && !screen.account.busy
        contentItem: TextLine {
            text: control.text
            font.pixelSize: 22 * screen.scaleUnit
            font.bold: true
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 17 * screen.scaleUnit
            color: control.accent ? (control.hovered ? "#079aee" : "#0089de") : "#111923"
            border.color: control.accent ? "#19adf4" : "#526274"
            border.width: 1.5
            opacity: control.enabled ? 1 : 0.55
        }
    }

    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true
        ColumnLayout {
            width: screen.width
            spacing: 17 * screen.scaleUnit

            Item { Layout.preferredHeight: 25 * screen.scaleUnit }
            Canvas {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: 80 * screen.scaleUnit
                Layout.preferredHeight: 50 * screen.scaleUnit
                onPaint: {
                    const ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    ctx.strokeStyle = "#08a9fb"
                    ctx.lineWidth = 5 * screen.scaleUnit
                    ctx.lineJoin = "round"
                    ctx.beginPath()
                    ctx.moveTo(width * .06, height * .26)
                    ctx.lineTo(width * .32, height * .53)
                    ctx.lineTo(width * .5, height * .07)
                    ctx.lineTo(width * .68, height * .53)
                    ctx.lineTo(width * .94, height * .26)
                    ctx.lineTo(width * .84, height * .92)
                    ctx.lineTo(width * .16, height * .92)
                    ctx.closePath()
                    ctx.stroke()
                }
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
            }
            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                TextLine { text: "Shadow"; font.pixelSize: 38 * screen.scaleUnit; font.bold: true }
                TextLine { text: "AFK"; color: "#08a9fb"; font.pixelSize: 38 * screen.scaleUnit; font.bold: true; font.italic: true }
            }
            TextLine {
                Layout.fillWidth: true
                Layout.topMargin: 15 * screen.scaleUnit
                text: "Добро пожаловать"
                font.pixelSize: 57 * screen.scaleUnit
                font.bold: true
            }
            TextLine {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: Math.min(screen.width - 70, 690 * screen.scaleUnit)
                color: "#b7c3d1"
                font.pixelSize: 22 * screen.scaleUnit
                text: account.state === "pending" ? "Нажмите Start в открывшемся боте"
                    : "Войдите в аккаунт или зарегистрируйтесь через Telegram, чтобы пользоваться всеми возможностями Shadow AFK."
            }
            ColumnLayout {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: Math.min(screen.width - 70, 515 * screen.scaleUnit)
                Layout.topMargin: 16 * screen.scaleUnit
                spacing: 16 * screen.scaleUnit
                TelegramButton {
                    accent: true
                    text: account.state === "pending" ? "Открыть Telegram" : "➤   Регистрация через Telegram"
                    onClicked: account.state === "pending" ? telegram.openTelegram() : telegram.startAccount("register")
                }
                TelegramButton {
                    text: account.state === "pending" ? "Отменить" : "Войти через Telegram"
                    onClicked: account.state === "pending" ? telegram.cancel() : telegram.startAccount("login")
                }
                TextLine {
                    Layout.fillWidth: true
                    visible: text.length > 0
                    text: account.error || (account.configured ? "" : "Сервис Telegram пока не настроен")
                    color: "#b7c3d1"
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.margins: 26 * screen.scaleUnit
                spacing: 15 * screen.scaleUnit
                Repeater {
                    model: [
                        ["♧", "Отслеживание матчей", "Автоматический контроль за игрой"],
                        ["▥", "Статистика", "Матчи, победы и прогресс"],
                        ["♧", "Уведомления", "О событиях в Telegram"],
                        ["◇", "Настройки", "Гибкая настройка работы"]
                    ]
                    Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        implicitHeight: 145 * screen.scaleUnit
                        color: "#101923"
                        border.color: "#213041"
                        radius: 18 * screen.scaleUnit
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 10 * screen.scaleUnit
                            spacing: 4
                            TextLine { Layout.fillWidth: true; text: modelData[0]; color: "#10a2f5"; font.pixelSize: 34 * screen.scaleUnit }
                            TextLine { Layout.fillWidth: true; text: modelData[1]; font.pixelSize: 17 * screen.scaleUnit; font.bold: true }
                            TextLine { Layout.fillWidth: true; text: modelData[2]; color: "#b7c3d1"; font.pixelSize: 14 * screen.scaleUnit }
                        }
                    }
                }
            }
        }
    }
}
