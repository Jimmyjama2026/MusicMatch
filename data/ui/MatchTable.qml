import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: table
    property var rows: []
    spacing: 0
    RowLayout {
        Layout.fillWidth: true
        Layout.bottomMargin: 8
        Label { Layout.fillWidth: true; text: "Feature"; color: "#AFCFFF"; font.pixelSize: 11; font.bold: true }
        Label { Layout.preferredWidth: 76; text: "Matched song"; color: "#AFCFFF"; font.pixelSize: 11; font.bold: true; wrapMode: Text.Wrap }
        Label { Layout.preferredWidth: 76; text: "Suggestion"; color: "#AFCFFF"; font.pixelSize: 11; font.bold: true; wrapMode: Text.Wrap }
    }
    Repeater {
        model: table.rows
        delegate: Rectangle {
            required property var modelData
            required property int index
            Layout.fillWidth: true
            implicitHeight: cells.implicitHeight + 18
            color: index % 2 ? "#191D24" : "#202733"
            radius: 5
            ColumnLayout {
                id: cells
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 9 }
                spacing: 4
                RowLayout {
                    Layout.fillWidth: true
                    Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: String(modelData.feature || "Feature"); color: "#D4DDEB"; font.pixelSize: 12; wrapMode: Text.Wrap }
                    Label { Layout.preferredWidth: 76; text: String(modelData.liked || "Unavailable"); color: "#D4DDEB"; font.pixelSize: 12; wrapMode: Text.Wrap }
                    Label { Layout.preferredWidth: 76; text: String(modelData.suggested || "Unavailable"); color: "#F1F5FC"; font.pixelSize: 12; wrapMode: Text.Wrap }
                }
                Label { Layout.fillWidth: true; visible: !!modelData.note; text: String(modelData.note || ""); color: "#AEBBD0"; font.pixelSize: 10; wrapMode: Text.Wrap }
            }
        }
    }
    Label { Layout.fillWidth: true; visible: table.rows.length === 0; text: "A feature comparison was not saved for this match."; color: "#B6C0CF"; wrapMode: Text.Wrap }
}
