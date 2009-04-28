import wx, wx.stc

NewWiki="Ctrl-N"
OpenWiki="Ctrl-Alt-O"
OpenWikiNewWindow=""
SearchWiki="Ctrl-Alt-F"
ViewBookmarks="Ctrl-Shift-B"
ShowTreeControl="Ctrl-T"
ShowToolbar="Ctrl-Shift-T"
ShowDocStructure=""
ShowTimeView=""
StayOnTop=""
OpenWikiWord="Ctrl-O"
Save="Ctrl-S"
Print="Ctrl-P"
Rename="Ctrl-Alt-R"
Delete="Ctrl-D"
AddBookmark="Ctrl-Alt-B"
CatchClipboardAtPage=""
CatchClipboardAtCursor=""
CatchClipboardOff=""
ActivateLink="Ctrl-L"
ActivateLinkNewTab="Ctrl-Alt-L"
# ActivateLinkBackground="Ctrl-Shift-L"
ViewParents="Ctrl-Up"
ViewParentless="Ctrl-Shift-Up"
ViewChildren="Ctrl-Down"
ViewHistory="Ctrl-H"
ClipboardCopyUrlToCurrentWikiword=""
SetAsRoot="Ctrl-Shift-Q"
ResetRoot=""
UpHistory="Ctrl-Alt-Up"
DownHistory="Ctrl-Alt-Down"
GoBack="Alt-Left"
GoForward="Alt-Right"
if wx.Platform == "__WXMAC__":
    GoHome="Ctrl-Shift-H"
else:
    GoHome="Ctrl-Q"
Bold="Ctrl-B"
Italic="Ctrl-I"
Heading="Ctrl-Alt-H"
SpellCheck=""
Cut="Ctrl-X"
Copy="Ctrl-C"
CopyToScratchPad="Ctrl-Alt-C"
Paste="Ctrl-V"
SelectAll="Ctrl-A"
Undo="Ctrl-Z"
Redo="Ctrl-Y"
AddFileUrl=""
FindAndReplace="Ctrl-R"
ReplaceTextByWikiword="Ctrl-Shift-R"
RewrapText="Ctrl-W"
Eval="Ctrl-E"
InsertDate="Ctrl-Alt-D"
MakeWikiWord="Ctrl-J"

ShowFolding=""
ToggleCurrentFolding=""
UnfoldAll=""
FoldAll=""

ShowEditor="Ctrl-Shift-A"
ShowPreview="Ctrl-Shift-S"
ShowSwitchEditorPreview="Ctrl-Shift-Space"
ZoomIn=""
ZoomOut=""
CloneWindow=""

ContinueSearch="F3"
BackwardSearch="Shift-F3"
AutoComplete="Ctrl-Space"
ActivateLink2="Ctrl-Return"
SwitchFocus="F6"
StartIncrementalSearch="Ctrl-F"
CloseCurrentTab="Ctrl-F4"
GoNextTab=""
GoPreviousTab=""
FocusFastSearchField=""

Plugin_AutoNew_Numbered = "Shift-Ctrl-N"

Plugin_GraphVizStructure_ShowRelationGraph = ""
Plugin_GraphVizStructure_ShowRelationGraphSource = ""
Plugin_GraphVizStructure_ShowChildGraph = ""
Plugin_GraphVizStructure_ShowChildGraphSource = ""


def makeBold(editor):
    editor.styleSelection(u'*')

def makeItalic(editor):
    editor.styleSelection(u'_')

def addHeading(editor):
    bytePos = editor.PositionAfter(editor.GetCurrentPos())
    editor.CmdKeyExecute(wx.stc.STC_CMD_HOME)
    editor.AddText(u'+')
    editor.GotoPos(bytePos)

def makeWikiWord(editor):
    text = editor.GetSelectedText()
    text = text.replace(u"'", u"")
    text = text[0:1].upper() + text[1:]
    text = u"[" + text + u"]"
    editor.ReplaceSelection(text)
