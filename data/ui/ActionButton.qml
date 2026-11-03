import QtQuick
import QtQuick.Controls

Button {
    id: control
    property bool primary: false
    property bool selected: false
    implicitHeight: 38
    implicitWidth: Math.max(74, contentItem.implicitWidth + 28)
    hoverEnabled: true
    font.pixelSize: 13
    font.weight: Font.DemiBold
    Accessible.name: text
    ToolTip.visible: hovered && contentItem.truncated
    ToolTip.text: text
    contentItem: Text {
        text: control.text
        font: control.font
        color: control.enabled ? "#F2F4F8" : "#8993A3"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: 9
        color: !control.enabled ? "#232832" : control.primary || control.selected ? (control.hovered ? "#265DAA" : "#1D4E9E") : (control.hovered ? "#303948" : "#242B36")
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? "#C4DCFF" : (control.selected ? "#7BA9F4" : "#394454")
    }
}
