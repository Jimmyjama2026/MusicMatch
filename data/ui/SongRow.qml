import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: row
    required property var song
    property string actionText: "Add"
    property bool actionEnabled: true
    signal action()
    color: "#191D24"
    radius: 10
    implicitHeight: 82
    RowLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 12
        Rectangle {
            Layout.preferredWidth: 42
            Layout.preferredHeight: 42
            radius: 9
            color: "#123A74"
            Text { anchors.centerIn: parent; text: String(row.song.artists || "M").slice(0, 1).toUpperCase(); color: "#E8EEFA"; font.pixelSize: 20; font.bold: true }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 5
            Label { Layout.fillWidth: true; text: row.song.display_title || row.song.track_name || "Untitled"; color: "#F2F4F8"; font.pixelSize: 14; font.bold: true; elide: Text.ElideRight; ToolTip.visible: titleHover.hovered; ToolTip.text: text; HoverHandler { id: titleHover } }
            Label { Layout.fillWidth: true; text: row.song.artists || "Unknown artist"; color: "#B6C0CF"; font.pixelSize: 12; elide: Text.ElideRight }
        }
        ActionButton { text: row.actionText; enabled: row.actionEnabled; onClicked: row.action() }
    }
}
