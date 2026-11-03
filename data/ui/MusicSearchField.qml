import QtQuick
import QtQuick.Controls

TextField {
    id: field
    implicitHeight: 42
    leftPadding: 12
    rightPadding: 12
    color: "#F2F4F8"
    placeholderTextColor: "#AAB7CA"
    selectionColor: "#1D4E9E"
    selectedTextColor: "#FFFFFF"
    font.pixelSize: 13
    background: Rectangle {
        color: field.enabled ? "#202631" : "#191E27"
        radius: 9
        border.width: field.activeFocus ? 2 : 1
        border.color: field.activeFocus ? "#A5C7FF" : "#394454"
    }
}
