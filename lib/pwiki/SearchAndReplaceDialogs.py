import sys, traceback, re

import wx, wx.html, wx.xrc

from MiscEvent import MiscEventSourceMixin, KeyFunctionSink
import Consts
from wxHelper import *

from StringOps import uniToGui, guiToUni, escapeHtml

from WindowLayout import setWindowPos, setWindowSize, \
        getRelativePositionTupleToAncestor, LayeredControlPanel

from Configuration import MIDDLE_MOUSE_CONFIG_TO_TABMODE, isLinux

from SearchAndReplace import SearchReplaceOperation, ListWikiPagesOperation


class SearchWikiOptionsDialog(wx.Dialog):
    def __init__(self, parent, pWiki, ID=-1, title="Search Wiki",
                 pos=wx.DefaultPosition, size=wx.DefaultSize,
                 style=wx.NO_3D|wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER):
        d = wx.PreDialog()
        self.PostCreate(d)

        self.pWiki = pWiki

        res = wx.xrc.XmlResource.Get()
        res.LoadOnDialog(self, parent, "SearchWikiOptionsDialog")

        self.ctrls = XrcControls(self)
        
        config = self.pWiki.getConfig()
        
        before = unicode(config.getint("main", "search_wiki_context_before"))
        after = unicode(config.getint("main", "search_wiki_context_after"))
                
        self.ctrls.tfWwSearchContextBefore.SetValue(uniToGui(before))
        self.ctrls.tfWwSearchContextAfter.SetValue(uniToGui(after))
        self.ctrls.cbWwSearchCountOccurrences.SetValue(
                config.getboolean("main", "search_wiki_count_occurrences"))
        
        self.ctrls.rboxFastSearchSearchType.SetSelection(
                config.getint("main", "fastSearch_searchType"))
        self.ctrls.cbFastSearchCaseSensitive.SetValue(
                config.getboolean("main", "fastSearch_caseSensitive"))
        self.ctrls.cbFastSearchWholeWord.SetValue(
                config.getboolean("main", "fastSearch_wholeWord"))

        self.ctrls.btnOk.SetId(wx.ID_OK)
        self.ctrls.btnCancel.SetId(wx.ID_CANCEL)
        
        # Fixes focus bug under Linux
        self.SetFocus()

        wx.EVT_BUTTON(self, wx.ID_OK, self.OnOk)


    def OnOk(self, evt):
        config = self.pWiki.getConfig()
        # If a text field contains an invalid value, its background becomes red
        try:
            self.ctrls.tfWwSearchContextBefore.SetBackgroundColour(wx.RED)
            before = int(self.ctrls.tfWwSearchContextBefore.GetValue())
            if before < 0: raise Exception
            self.ctrls.tfWwSearchContextBefore.SetBackgroundColour(wx.WHITE)

            self.ctrls.tfWwSearchContextAfter.SetBackgroundColour(wx.RED)
            after = int(self.ctrls.tfWwSearchContextAfter.GetValue())
            if after < 0: raise Exception
            self.ctrls.tfWwSearchContextAfter.SetBackgroundColour(wx.WHITE)

            config.set("main", "search_wiki_context_before", before)
            config.set("main", "search_wiki_context_after", after)
            config.set("main", "search_wiki_count_occurrences",
                    self.ctrls.cbWwSearchCountOccurrences.GetValue())

            config.set("main", "fastSearch_searchType", 
                    self.ctrls.rboxFastSearchSearchType.GetSelection())
            config.set("main", "fastSearch_caseSensitive", 
                    self.ctrls.cbFastSearchCaseSensitive.GetValue())
            config.set("main", "fastSearch_wholeWord", 
                    self.ctrls.cbFastSearchWholeWord.GetValue())

        except:
            self.Refresh()
            return

        self.EndModal(wx.ID_OK)



class _SearchResultItemInfo(object):
    __slots__ = ("__weakref__", "wikiWord", "occCount", "occNumber", "occHtml",
            "occPos", "html")
    
    def __init__(self, wikiWord, occPos = (-1, -1), occCount = -1):
        self.wikiWord = wikiWord
        if occPos[0] != -1:
            self.occNumber = 1
        else:
            self.occNumber = -1  # -1: No specific occurrence

        self.occHtml = u""  # HTML presentation of the occurrence
        self.occPos = occPos  # Tuple (start, end) with position of occurrence in characters
        self.occCount = occCount # -1: Undefined
        self.html = None
        
        
    def buildOccurrence(self, text, before, after, pos, occNumber):
        self.html = None
        basum = before + after
        self.occNumber = -1
        self.occPos = pos
        if basum == 0:
            # No context
            self.occHtml = u""
            return self
            
        if pos[0] == -1:
            # No position -> use beginning of text
            self.occHtml = escapeHtml(text[0:basum])
            return self
        
        s = max(0, pos[0] - before)
        e = min(len(text), pos[1] + after)
        self.occHtml = u"".join([escapeHtml(text[s:pos[0]]), 
            "<b>", escapeHtml(text[pos[0]:pos[1]]), "</b>",
            escapeHtml(text[pos[1]:e])])
            
        self.occNumber = occNumber
        return self


    def getHtml(self):
        if self.html is None:
            result = [u'<table><tr><td bgcolor="#0000ff" width="6"></td>'
                    u'<td><font color="BLUE"><b>%s</b></font>' % \
                    escapeHtml(self.wikiWord)]
            
            if self.occNumber != -1:
                stroc = [unicode(self.occNumber), u"/"]
            else:
                stroc = []
                
            if self.occCount != -1:
                stroc.append(unicode(self.occCount))
            elif len(stroc) > 0:
                stroc.append(u"?")
                
            stroc = u"".join(stroc)
            
            if stroc != u"":
                result.append(u' <b>(%s)</b>' % stroc)
                
            if self.occHtml != u"":
                result.append(u'<br>\n')
                result.append(self.occHtml)
                
            result.append('</td></tr></table>')
            self.html = u"".join(result)
            
        return self.html



class SearchResultListBox(wx.HtmlListBox):
    def __init__(self, parent, pWiki, ID):
        wx.HtmlListBox.__init__(self, parent, ID, style = wx.SUNKEN_BORDER)

        self.pWiki = pWiki
        self.searchWikiDialog = parent
        self.found = []
        self.foundinfo = []
        self.searchOp = None # last search operation set by showFound
        self.SetItemCount(0)
        self.isShowingSearching = False  # Show a visual feedback only while searching
        self.contextMenuSelection = -2

        wx.EVT_LEFT_DOWN(self, self.OnLeftDown)
        wx.EVT_LEFT_DCLICK(self, self.OnLeftDown)
        wx.EVT_MIDDLE_DOWN(self, self.OnMiddleButtonDown)
        wx.EVT_KEY_DOWN(self, self.OnKeyDown)
        wx.EVT_LISTBOX_DCLICK(self, ID, self.OnDClick)
        wx.EVT_CONTEXT_MENU(self, self.OnContextMenu)


        wx.EVT_MENU(self, GUI_ID.CMD_ACTIVATE_THIS, self.OnActivateThis)
        wx.EVT_MENU(self, GUI_ID.CMD_ACTIVATE_NEW_TAB_THIS,
                self.OnActivateNewTabThis)
        wx.EVT_MENU(self, GUI_ID.CMD_ACTIVATE_NEW_TAB_BACKGROUND_THIS,
                self.OnActivateNewTabBackgroundThis)


    def OnGetItem(self, i):
        if self.isShowingSearching:
            return u"<b>" + _(u"Searching...") + u"</b>"
        elif self.GetCount() == 0:
            return u"<b>" + _(u"Not found") + u"</b>"

        try:
            return self.foundinfo[i].getHtml()
        except IndexError:
            return u""

    def showSearching(self):
        """
        Shows a "Searching..." as visual feedback while search runs
        """
        self.isShowingSearching = True
        self.SetItemCount(1)
        self.Refresh()
        self.Update()
        
    def ensureNotShowSearching(self):
        """
        This function is called after a search operation and a call to
        showFound may have happened. If it did not happen,
        the list is cleared.
        """
        if self.isShowingSearching:
            # This can only happend if showFound wasn't called
            self.showFound(None, None, None)


    def showFound(self, sarOp, found, wikiDocument):
        """
        Shows the results of search operation sarOp
        found -- list of matching wiki words
        wikiDocument -- WikiDocument(=WikiDataManager) object
        """
        self.isShowingSearching = False
        if found is None or len(found) == 0:
            self.found = []
            self.foundinfo = []
            self.SetItemCount(1)   # For the "Not found" entry
            self.searchOp = None
        else:
            # Store and prepare clone of search operation
            self.searchOp = sarOp.clone()
            self.searchOp.replaceOp = False
            self.searchOp.cycleToStart = True

            self.found = found
            self.foundinfo = []
            # Load context settings
            before = self.pWiki.configuration.getint("main",
                    "search_wiki_context_before")
            after = self.pWiki.configuration.getint("main",
                    "search_wiki_context_after")
                    
            countOccurrences = self.pWiki.configuration.getboolean("main",
                    "search_wiki_count_occurrences")
                    
            if sarOp.booleanOp:
                # No specific position to show as context, so show beginning of page
                # Also, no occurrence counting possible
                context = before + after
                if context == 0:
                    self.foundinfo = [_SearchResultItemInfo(w) for w in found]
                else:                    
                    for w in found:
                        text = wikiDocument.getWikiPageNoError(w).\
                                getLiveTextNoTemplate()
                        if text is None:
                            continue
                        self.foundinfo.append(
                                _SearchResultItemInfo(w).buildOccurrence(
                                text, before, after, (-1, -1), -1))
            else:
                if before + after == 0 and not countOccurrences:
                    # No context, no occurrence counting
                    self.foundinfo = [_SearchResultItemInfo(w) for w in found]
                else:
                    for w in found:
                        text = wikiDocument.getWikiPageNoError(w).\
                                getLiveTextNoTemplate()
                        if text is None:
                            continue
                        pos = sarOp.searchText(text)
                        firstpos = pos
                        
                        info = _SearchResultItemInfo(w, occPos=pos)
                        
                        if countOccurrences:
                            occ = 1
                            while True:
                                pos = sarOp.searchText(text, pos[1])
                                if pos[0] is None or pos[0] == pos[1]:
                                    break
                                occ += 1

                            info.occCount = occ

                        self.foundinfo.append(info.buildOccurrence(
                                text, before, after, firstpos, 1))
                            
            self.SetItemCount(len(self.foundinfo))

        self.Refresh()
        

    def GetSelectedWord(self):
        sel = self.GetSelection()
        if sel == -1 or self.GetCount() == 0:
            return None
        else:
            return self.foundinfo[sel].wikiWord
            
    def GetCount(self):
        return len(self.found)

    def IsEmpty(self):
        return self.GetCount() == 0


    def _pageListFindNext(self):
        """
        After pressing F3 or clicking blue bar of an entry, position of
        next found element should be shown
        """
        sel = self.GetSelection()
        if sel == -1:
            return
        
        info = self.foundinfo[sel]
        if info.occPos[0] == -1:
            return
        if info.occNumber == -1:
            return
            
        before = self.pWiki.configuration.getint("main",
                "search_wiki_context_before")
        after = self.pWiki.configuration.getint("main",
                "search_wiki_context_after")
        
        wikiDocument = self.pWiki.getWikiDocument()
        text = wikiDocument.getWikiPageNoError(info.wikiWord).\
                getLiveTextNoTemplate()
        if text is not None:
            pos = self.searchOp.searchText(text, info.occPos[1])
        else:
            pos = (-1, -1)

        if pos[0] == -1:
            # Page was changed after last search and doen't contain any occurrence anymore
            info.occCount = 0
            info.buildOccurrence(text, 0, 0, pos, -1)
        elif pos[0] < info.occPos[1]:
            # Search went back to beginning, number of last occ. ist also occ.count
            info.occCount = info.occNumber
            info.buildOccurrence(text, before, after, pos, 1)
        elif pos[0] == info.occPos[1]:
            # Match is empty
            info.occCount = info.occNumber
            info.buildOccurrence(text, before, after, pos, 1)            
        else:
            info.buildOccurrence(text, before, after, pos, info.occNumber + 1)

        # TODO nicer refresh
        self.SetSelection(-1)
        self.SetSelection(sel)
        self.Refresh()
        

    def OnDClick(self, evt):
        sel = self.GetSelection()
        if sel == -1 or self.GetCount() == 0:
            return

        info = self.foundinfo[sel]

        self.pWiki.openWikiPage(info.wikiWord)
        
        editor = self.pWiki.getActiveEditor()
        if editor is not None:
            if info.occPos[0] != -1:
                self.pWiki.getActiveEditor().SetSelectionByCharPos(info.occPos[0],
                        info.occPos[1])


            # Works in fast search popup only if called twice
            editor.SetFocus()
            editor.SetFocus()


    def OnLeftDown(self, evt):
        if self.GetCount() == 0:
            return  # no evt.Skip()?

        pos = evt.GetPosition()
        hitsel = self.HitTest(pos)
        
        if hitsel == wx.NOT_FOUND:
            evt.Skip()
            return
        
        if pos.x < (5 + 6):
            # Click inside the blue bar
            self.SetSelection(hitsel)
            self._pageListFindNext()
            return
        
        evt.Skip()


    def OnMiddleButtonDown(self, evt):
        if self.GetCount() == 0:
            return  # no evt.Skip()?

        pos = evt.GetPosition()
        if pos == wx.DefaultPosition:
            hitsel = self.GetSelection()

        hitsel = self.HitTest(pos)

        if hitsel == wx.NOT_FOUND:
            evt.Skip()
            return

        if pos.x < (5 + 6):
            # Click inside the blue bar
            self.SetSelection(hitsel)
            self._pageListFindNext()
            return
        
        info = self.foundinfo[hitsel]

        if evt.ControlDown():
            configCode = self.pWiki.getConfig().getint("main",
                    "mouse_middleButton_withCtrl")
        else:
            configCode = self.pWiki.getConfig().getint("main",
                    "mouse_middleButton_withoutCtrl")
                    
        tabMode = MIDDLE_MOUSE_CONFIG_TO_TABMODE[configCode]

        presenter = self.pWiki.activatePageByUnifiedName(
                u"wikipage/" + info.wikiWord, tabMode)

        if info.occPos[0] != -1:
            presenter.getSubControl("textedit").SetSelectionByCharPos(
                    info.occPos[0], info.occPos[1])

        if configCode != 1:
            # If not new tab opened in background -> focus editor

            # Works in fast search popup only if called twice
            self.pWiki.getActiveEditor().SetFocus()
            self.pWiki.getActiveEditor().SetFocus()

        
    def OnKeyDown(self, evt):
        if self.GetCount() == 0:
            return  # no evt.Skip()?

        accP = getAccelPairFromKeyDown(evt)
        matchesAccelPair = self.pWiki.keyBindings.matchesAccelPair
        
        if matchesAccelPair("ContinueSearch", accP):
            # ContinueSearch is normally F3
            self._pageListFindNext()
        elif accP == (wx.ACCEL_NORMAL, wx.WXK_RETURN) or \
                accP == (wx.ACCEL_NORMAL, wx.WXK_NUMPAD_ENTER):
            self.OnDClick(evt)
        else:
            evt.Skip()


    def OnContextMenu(self, evt):
        if self.GetCount() == 0:
            return  # no evt.Skip()?

        pos = evt.GetPosition()
        if pos == wx.DefaultPosition:
            hitsel = self.GetSelection()
        else:
            hitsel = self.HitTest(self.ScreenToClient(pos))

        if hitsel == wx.NOT_FOUND:
            evt.Skip()
            return

        self.contextMenuSelection = hitsel
        try:
            menu = wx.Menu()
            appendToMenuByMenuDesc(menu, _CONTEXT_MENU_ACTIVATE)
            self.PopupMenu(menu)
            menu.Destroy()
        finally:
            self.contextMenuSelection = -2



    def OnActivateThis(self, evt):
        if self.contextMenuSelection > -1:
            info = self.foundinfo[self.contextMenuSelection]

#             presenter = self.pWiki.activateWikiWord(info.wikiWord, 0)
            presenter = self.pWiki.activatePageByUnifiedName(
                    u"wikipage/" + info.wikiWord, 0)
            if info.occPos[0] != -1:
                presenter.getSubControl("textedit").SetSelectionByCharPos(
                        info.occPos[0], info.occPos[1])
    
            # Works in fast search popup only if called twice
            self.pWiki.getActiveEditor().SetFocus()
            self.pWiki.getActiveEditor().SetFocus()


    def OnActivateNewTabThis(self, evt):
        if self.contextMenuSelection > -1:
            info = self.foundinfo[self.contextMenuSelection]

#             presenter = self.pWiki.activateWikiWord(info.wikiWord, 2)
            presenter = self.pWiki.activatePageByUnifiedName(
                    u"wikipage/" + info.wikiWord, 2)
            if info.occPos[0] != -1:
                presenter.getSubControl("textedit").SetSelectionByCharPos(
                        info.occPos[0], info.occPos[1])
    
            # Works in fast search popup only if called twice
            self.pWiki.getActiveEditor().SetFocus()
            self.pWiki.getActiveEditor().SetFocus()


    def OnActivateNewTabBackgroundThis(self, evt):
        if self.contextMenuSelection > -1:
            info = self.foundinfo[self.contextMenuSelection]

#             presenter = self.pWiki.activateWikiWord(info.wikiWord, 3)
            presenter = self.pWiki.activatePageByUnifiedName(
                    u"wikipage/" + info.wikiWord, 3)
            if info.occPos[0] != -1:
                presenter.getSubControl("textedit").SetSelectionByCharPos(
                        info.occPos[0], info.occPos[1])
            
            # Don't change focus when activating new tab in background
#             # Works in fast search popup only if called twice
#             self.pWiki.getActiveEditor().SetFocus()
#             self.pWiki.getActiveEditor().SetFocus()




class SearchWikiDialog(wx.Dialog):   # TODO
    def __init__(self, parent, ID, srListBox=None, title="Search Wiki",
                 pos=wx.DefaultPosition, size=wx.DefaultSize,
                 style=wx.NO_3D|wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER):
        d = wx.PreDialog()
        self.PostCreate(d)
        
        self.mainControl = parent

        res = wx.xrc.XmlResource.Get()
        res.LoadOnDialog(self, parent, "SearchWikiDialog")
        if srListBox is None:
            srListBox = SearchResultListBox(self, self.mainControl,
                    GUI_ID.htmllbPages)
        else:
            srListBox.Reparent(self)

        res.AttachUnknownControl("htmllbPages", srListBox, self)
        self.ctrls = XrcControls(self)

#         searchContentPage = res.LoadPanel(self.ctrls.nbFilters,
#                 "SearchWikiContentPage")
#         
#         self.ctrls.nbFilters.AddPage(searchContentPage, u"Content", True)
#         
#         self.Fit()
        
        self.ctrls.btnClose.SetId(wx.ID_CANCEL)
        
        self.ctrls.cbSearch.SetWindowStyle(self.ctrls.cbSearch.GetWindowStyle()
                | wx.TE_PROCESS_ENTER)
        
        self.listNeedsRefresh = True  # Reflects listbox content current
                                      # search criteria?

        self.savedSearches = None
        self.foundPages = []
        
        self.listPagesOperation = ListWikiPagesOperation()
        self._refreshSavedSearchesList()
        self._refreshSearchHistoryCombo()
        
        # Fixes focus bug under Linux
        self.SetFocus()

        wx.EVT_BUTTON(self, GUI_ID.btnFindPages, self.OnSearchWiki)
        wx.EVT_BUTTON(self, GUI_ID.btnSetPageList, self.OnSetPageList)
        wx.EVT_BUTTON(self, GUI_ID.btnFindNext, self.OnFindNext)        
        wx.EVT_BUTTON(self, GUI_ID.btnReplace, self.OnReplace)
        wx.EVT_BUTTON(self, GUI_ID.btnReplaceAll, self.OnReplaceAll)
        wx.EVT_BUTTON(self, GUI_ID.btnSaveSearch, self.OnSaveSearch)
        wx.EVT_BUTTON(self, GUI_ID.btnDeleteSearches, self.OnDeleteSearches)
        wx.EVT_BUTTON(self, GUI_ID.btnLoadSearch, self.OnLoadSearch)
        wx.EVT_BUTTON(self, GUI_ID.btnLoadAndRunSearch, self.OnLoadAndRunSearch)
        wx.EVT_BUTTON(self, GUI_ID.btnOptions, self.OnOptions)
        wx.EVT_BUTTON(self, GUI_ID.btnCopyPageNamesToClipboard,
                self.OnCopyPageNamesToClipboard)
        wx.EVT_BUTTON(self, GUI_ID.btnAsResultlist, self.OnCmdAsResultlist)
        wx.EVT_BUTTON(self, GUI_ID.btnAsTab, self.OnCmdAsTab)

        wx.EVT_CHAR(self.ctrls.cbSearch, self.OnCharToFind)
        wx.EVT_CHAR(self.ctrls.rboxSearchType, self.OnCharToFind)
        wx.EVT_CHAR(self.ctrls.cbCaseSensitive, self.OnCharToFind)
        wx.EVT_CHAR(self.ctrls.cbWholeWord, self.OnCharToFind)

        wx.EVT_COMBOBOX(self, GUI_ID.cbSearch, self.OnSearchComboSelected) 
        wx.EVT_LISTBOX_DCLICK(self, GUI_ID.lbSavedSearches, self.OnLoadAndRunSearch)
        wx.EVT_RADIOBOX(self, GUI_ID.rboxSearchType, self.OnRadioBox)
        wx.EVT_BUTTON(self, wx.ID_CANCEL, self.OnClose)        
        wx.EVT_CLOSE(self, self.OnClose)
        
        wx.EVT_TEXT(self, GUI_ID.cbSearch, self.OnListRefreshNeeded)
        wx.EVT_CHECKBOX(self, GUI_ID.cbCaseSensitive, self.OnListRefreshNeeded)
        wx.EVT_CHECKBOX(self, GUI_ID.cbWholeWord, self.OnListRefreshNeeded)


    def displayErrorMessage(self, errorStr, e=u""):
        """
        Pops up an error dialog box
        """
        wx.MessageBox(uniToGui(u"%s. %s." % (errorStr, e)), _(u"Error!"),
            wx.OK, self)


    def buildSearchReplaceOperation(self):
        searchType = self.ctrls.rboxSearchType.GetSelection()
        
        sarOp = SearchReplaceOperation()
        sarOp.searchStr = guiToUni(self.ctrls.cbSearch.GetValue())
        sarOp.booleanOp = searchType == Consts.SEARCHTYPE_BOOLEANREGEX
        sarOp.caseSensitive = self.ctrls.cbCaseSensitive.GetValue()
        sarOp.wholeWord = self.ctrls.cbWholeWord.GetValue()
        sarOp.cycleToStart = False
        sarOp.wildCard = 'regex' if searchType != Consts.SEARCHTYPE_ASIS else 'no'
        sarOp.wikiWide = True
        sarOp.listWikiPagesOp = self.listPagesOperation

        if not sarOp.booleanOp:
            sarOp.replaceStr = guiToUni(self.ctrls.txtReplace.GetValue())
            
        return sarOp


    def showSearchReplaceOperation(self, sarOp):
        self.ctrls.cbSearch.SetValue(uniToGui(sarOp.searchStr))
        if sarOp.booleanOp:
            self.ctrls.rboxSearchType.SetSelection(Consts.SEARCHTYPE_BOOLEANREGEX)
        else:
            if sarOp.wildCard == 'regex':
                self.ctrls.rboxSearchType.SetSelection(Consts.SEARCHTYPE_REGEX)
            else:
                self.ctrls.rboxSearchType.SetSelection(Consts.SEARCHTYPE_ASIS)

        self.ctrls.cbCaseSensitive.SetValue(sarOp.caseSensitive)
        self.ctrls.cbWholeWord.SetValue(sarOp.wholeWord)

        if not sarOp.booleanOp and sarOp.replaceOp:
            self.ctrls.txtReplace.SetValue(uniToGui(sarOp.replaceStr))

        self.listPagesOperation = sarOp.listWikiPagesOp

        self.OnRadioBox(None)  # Refresh settings


    def _refreshPageList(self):
        self.ctrls.htmllbPages.showSearching()
        self.SetCursor(wx.HOURGLASS_CURSOR)
        self.Freeze()
        try:
            sarOp = self.buildSearchReplaceOperation()

            if len(sarOp.searchStr) > 0:
                self.foundPages = self.mainControl.getWikiDocument().searchWiki(sarOp)
                self.mainControl.getCollator().sort(self.foundPages)
                self.ctrls.htmllbPages.showFound(sarOp, self.foundPages,
                        self.mainControl.getWikiDocument())
            else:
                self.foundPages = []
                self.ctrls.htmllbPages.showFound(None, None, None)

            self.listNeedsRefresh = False

        finally:
            self.Thaw()
            self.SetCursor(wx.NullCursor)
            self.ctrls.htmllbPages.ensureNotShowSearching()


    def OnSearchWiki(self, evt):
        try:
            self._refreshPageList()
            self.addCurrentToHistory()
            if not self.ctrls.htmllbPages.IsEmpty():
                self.ctrls.htmllbPages.SetFocus()
                self.ctrls.htmllbPages.SetSelection(0)
        except re.error, e:
            self.displayErrorMessage(_(u'Error in regular expression'),
                    _(unicode(e)))

            
    def OnSetPageList(self, evt):
        """
        Show the Page List dialog
        """
        dlg = WikiPageListConstructionDialog(self, self.GetParent(), -1,
                value=self.listPagesOperation, allowOrdering=False)

#         result = dlg.ShowModal()
#         dlg.Destroy()
#         if result == wxID_OK:
#             self.listPagesOperation = dlg.getValue()
#             pass

        dlg.getMiscEvent().addListener(KeyFunctionSink((
                ("nonmodal closed", self.onNonmodalClosedPageList),
        )), False)

        self.Show(False)
        dlg.Show(True)

    def onNonmodalClosedPageList(self, miscevt):
        plop = miscevt.get("listWikiPagesOp")
        if plop is not None:
            self.listPagesOperation = plop

        self.Show(True)


    def OnListRefreshNeeded(self, evt):
        self.listNeedsRefresh = True

    def OnFindNext(self, evt):
        self._findNext()

    def _findNext(self):
        if self.listNeedsRefresh:
            try:
                # Refresh list and start from beginning
                self._refreshPageList()
            except re.error, e:
                self.displayErrorMessage(_(u'Error in regular expression'),
                        _(unicode(e)))
                return

        self.addCurrentToHistory()
        if self.ctrls.htmllbPages.GetCount() == 0:
            return
        
        try:
            while True:            
                    
                #########self.ctrls.lb.SetSelection(self.listPosNext)
                
                wikiWord = guiToUni(self.ctrls.htmllbPages.GetSelectedWord())
                
                if not wikiWord:
                    self.ctrls.htmllbPages.SetSelection(0)
                    wikiWord = guiToUni(self.ctrls.htmllbPages.GetSelectedWord())
    
                if self.mainControl.getCurrentWikiWord() != wikiWord:
                    self.mainControl.openWikiPage(wikiWord)
                    nextOnPage = False
                else:
                    nextOnPage = True
    
                searchOp = self.buildSearchReplaceOperation()
                searchOp.replaceOp = False
                if nextOnPage:
                    pagePosNext = self.mainControl.getActiveEditor().executeSearch(searchOp,
                            -2)[1]
                else:
                    pagePosNext = self.mainControl.getActiveEditor().executeSearch(searchOp,
                            0)[1]
                    
                if pagePosNext != -1:
                    return  # Found
                    
                if self.ctrls.htmllbPages.GetSelection() == \
                        self.ctrls.htmllbPages.GetCount() - 1:
                    # Nothing more found on the last page in list, so back to
                    # begin of list and stop
                    self.ctrls.htmllbPages.SetSelection(0)
                    return
                    
                # Otherwise: Go to next page in list            
                self.ctrls.htmllbPages.SetSelection(
                        self.ctrls.htmllbPages.GetSelection() + 1)
        except re.error, e:
            self.displayErrorMessage(_(u'Error in regular expression'),
                    _(unicode(e)))



    def OnReplace(self, evt):
        sarOp = self.buildSearchReplaceOperation()
        sarOp.replaceOp = True
        try:
            self.mainControl.getActiveEditor().executeReplace(sarOp)
        except re.error, e:
            self.displayErrorMessage(_(u'Error in regular expression'),
                    _(unicode(e)))
            return

        self._findNext()


    def OnReplaceAll(self, evt):
        answer = wx.MessageBox(_(u"Replace all occurrences?"), _(u"Replace All"),
                wx.YES_NO | wx.NO_DEFAULT, self)
        
        if answer == wx.NO:
            return

        try:
            self._refreshPageList()
            
            if self.ctrls.htmllbPages.GetCount() == 0:
                return
                
            # self.pWiki.saveCurrentDocPage()
            
            sarOp = self.buildSearchReplaceOperation()
            sarOp.replaceOp = True
            
            # wikiData = self.pWiki.getWikiData()
            wikiDocument = self.mainControl.getWikiDocument()
            self.addCurrentToHistory()
            
            replaceCount = 0
    
            for i in xrange(self.ctrls.htmllbPages.GetCount()):
                self.ctrls.htmllbPages.SetSelection(i)
                wikiWord = guiToUni(self.ctrls.htmllbPages.GetSelectedWord())
                wikiPage = wikiDocument.getWikiPageNoError(wikiWord)
                text = wikiPage.getLiveTextNoTemplate()
                if text is None:
                    continue
    
                charStartPos = 0
    
                while True:
                    try:
                        found = sarOp.searchText(text, charStartPos)
                        start, end = found[:2]
                    except:
                        # Regex error -> Stop searching
                        return
                        
                    if start is None: break
                    
                    repl = sarOp.replace(text, found)
                    text = text[:start] + repl + text[end:]  # TODO Faster?
                    charStartPos = start + len(repl)
                    replaceCount += 1
                    if start == end:
                        # Otherwise replacing would go infinitely
                        break

                wikiPage.replaceLiveText(text)
                    
            self._refreshPageList()
            
            wx.MessageBox(_(u"%i replacements done") % replaceCount,
                    _(u"Replace All"),
                wx.OK, self)        

        except re.error, e:
            self.displayErrorMessage(_(u'Error in regular expression'),
                    _(unicode(e)))


    def addCurrentToHistory(self):
        sarOp = self.buildSearchReplaceOperation()
        try:
            sarOp.rebuildSearchOpTree()
        except re.error:
            # Ignore silently
            return
        data = sarOp.getPackedSettings()
        tpl = (sarOp.searchStr, sarOp.getPackedSettings())
        hist = wx.GetApp().getWikiSearchHistory()
        try:
            pos = hist.index(tpl)
            del hist[pos]
            hist.insert(0, tpl)
        except ValueError:
            # tpl not in hist
            hist.insert(0, tpl)
            if len(hist) > 10:
                hist = hist[:10]
            
        wx.GetApp().setWikiSearchHistory(hist)
        text = self.ctrls.cbSearch.GetValue()
        self._refreshSearchHistoryCombo()
#         self.ctrls.cbSearch.Clear()
#         self.ctrls.cbSearch.AppendItems([tpl[0] for tpl in hist])
        self.ctrls.cbSearch.SetValue(text)



    # TODO Store search mode
    def OnSaveSearch(self, evt):
        sarOp = self.buildSearchReplaceOperation()
        try:
            sarOp.rebuildSearchOpTree()
        except re.error, e:
            self.mainControl.displayErrorMessage(_(u'Error in regular expression'),
                    _(unicode(e)))
            return

        if len(sarOp.searchStr) > 0:
            title = sarOp.getTitle()
            while True:
                title = guiToUni(wx.GetTextFromUser(_(u"Title:"),
                        _(u"Choose search title"), title, self))
                if title == u"":
                    return  # Cancel
                    
#                 if title in self.pWiki.getWikiData().getSavedSearchTitles():
                if (u"savedsearch/" + title) in self.mainControl.getWikiData()\
                        .getDataBlockUnifNamesStartingWith(
                        u"savedsearch/" + title):

                    answer = wx.MessageBox(
                            _(u"Do you want to overwrite existing search '%s'?") %
                            title, _(u"Overwrite search"),
                            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self)
                    if answer == wx.NO:
                        continue

#                 self.pWiki.getWikiData().saveSearch(title,
#                         sarOp.getPackedSettings())
                self.mainControl.getWikiData().storeDataBlock(
                        u"savedsearch/" + title, sarOp.getPackedSettings(),
                        storeHint=Consts.DATABLOCK_STOREHINT_INTERN)

                self._refreshSavedSearchesList()
                break
        else:
            self.mainControl.displayErrorMessage(
                    _(u"Invalid search string, can't save as view"))


    def OnRadioBox(self, evt):
        self.listNeedsRefresh = True
        booleanSearch = self.ctrls.rboxSearchType.GetSelection() == 1
        
        self.ctrls.txtReplace.Enable(not booleanSearch)
        self.ctrls.btnFindNext.Enable(not booleanSearch)
        self.ctrls.btnReplace.Enable(not booleanSearch)
        self.ctrls.btnReplaceAll.Enable(not booleanSearch)


    def OnOptions(self, evt):
        dlg = SearchWikiOptionsDialog(self, self.GetParent(), -1)
        dlg.CenterOnParent(wx.BOTH)

        dlg.ShowModal()
        dlg.Destroy()


    def getResultListPositionTuple(self):
        return getRelativePositionTupleToAncestor(self.ctrls.htmllbPages, self)


    def OnCmdAsResultlist(self, evt):
        self.Hide()
        
        ownPos = self.GetPositionTuple()
        oldRelBoxPos = self.getResultListPositionTuple()
        
        frame = FastSearchPopup(self.GetParent(), self.mainControl, -1,
                srListBox=self.ctrls.htmllbPages)
        frame.setSearchOp(self.buildSearchReplaceOperation())
        
        newRelBoxPos = frame.getResultListPositionTuple()

        # A bit math to ensure that result list in both windows is placed
        # at same position (looks more cool)
        otherPos = (ownPos[0] + oldRelBoxPos[0] - newRelBoxPos[0],
                ownPos[1] + oldRelBoxPos[1] - newRelBoxPos[1])
        
        setWindowPos(frame, pos=otherPos, fullVisible=True)
        self.mainControl.wwSearchDlgs.append(frame)
        frame.Show()
        self.Close()


    def OnCmdAsTab(self, evt):
        self.Hide()

        maPanel = self.mainControl.getMainAreaPanel()
        presenter = LayeredControlPanel(maPanel)
        subCtl = SearchResultPresenterControl(presenter, self.mainControl,
                self.GetParent(), -1, srListBox=self.ctrls.htmllbPages)
        presenter.setSubControl("search result list", subCtl)
        presenter.switchSubControl("search result list")
        maPanel.appendPresenterTab(presenter)
        subCtl.setSearchOp(self.buildSearchReplaceOperation())

        maPanel.showPresenter(presenter)
        self.Close()


    def OnClose(self, evt):
        try:
            self.mainControl.wwSearchDlgs.remove(self)
        except ValueError:
            if self is self.mainControl.mainWwSearchDlg:
                self.mainControl.mainWwSearchDlg = None

        self.Destroy()


    def _refreshSavedSearchesList(self):
        unifNames = self.mainControl.getWikiData()\
                .getDataBlockUnifNamesStartingWith(u"savedsearch/")

#         self.savedSearches = self.pWiki.getWikiData().getSavedSearchTitles()
        self.savedSearches = [name[12:] for name in unifNames]
        self.mainControl.getCollator().sort(self.savedSearches)

        self.ctrls.lbSavedSearches.Clear()
        for search in self.savedSearches:
            self.ctrls.lbSavedSearches.Append(uniToGui(search))


    def _refreshSearchHistoryCombo(self):
        hist = wx.GetApp().getWikiSearchHistory()
        self.ctrls.cbSearch.Clear()
        self.ctrls.cbSearch.AppendItems([tpl[0] for tpl in hist])


    def OnDeleteSearches(self, evt):
        sels = self.ctrls.lbSavedSearches.GetSelections()
        
        if len(sels) == 0:
            return
            
        answer = wx.MessageBox(
                _(u"Do you want to delete %i search(es)?") % len(sels),
                _(u"Delete search"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self)
        if answer == wx.NO:
            return

        for s in sels:
#             self.pWiki.getWikiData().deleteSavedSearch(self.savedSearches[s])
            self.mainControl.getWikiData().deleteDataBlock(
                    u"savedsearch/" + self.savedSearches[s])
        self._refreshSavedSearchesList()


    def OnLoadSearch(self, evt):
        self._loadSearch()
        
    def OnLoadAndRunSearch(self, evt):
        if self._loadSearch():
            try:
                self._refreshPageList()
            except re.error, e:
                self.displayErrorMessage(_(u'Error in regular expression'),
                        _(unicode(e)))


    def _loadSearch(self):
        sels = self.ctrls.lbSavedSearches.GetSelections()
        
        if len(sels) != 1:
            return False
        
#         datablock = self.pWiki.getWikiData().getSearchDatablock(
#                 self.savedSearches[sels[0]])
        datablock = self.mainControl.getWikiData().retrieveDataBlock(
                u"savedsearch/" + self.savedSearches[sels[0]])

        sarOp = SearchReplaceOperation()
        sarOp.setPackedSettings(datablock)
        
        self.showSearchReplaceOperation(sarOp)
        
        return True


    def OnSearchComboSelected(self, evt):
        hist = wx.GetApp().getWikiSearchHistory()
        sarOp = SearchReplaceOperation()
        sarOp.setPackedSettings(hist[evt.GetSelection()][1])
        
        self.showSearchReplaceOperation(sarOp)
        self.ctrls.txtReplace.SetValue(guiToUni(sarOp.replaceStr))


    def OnCopyPageNamesToClipboard(self, evt):
        langHelper = wx.GetApp().createWikiLanguageHelper(
                self.mainControl.getWikiDefaultWikiLanguage())

        wordsText = u"".join([
                langHelper.createStableLinksFromWikiWords((w,)) + "\n"
                for w in self.foundPages])

        copyTextToClipboard(wordsText)


    def OnCharToFind(self, evt):
#         if (evt.GetKeyCode() == WXK_DOWN):
#             if not self.ctrls.lb.IsEmpty():
#                 self.ctrls.lb.SetFocus()
#                 self.ctrls.lb.SetSelection(0)
#         elif (evt.GetKeyCode() == WXK_UP):
#             pass
        if (evt.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)):
            self.OnSearchWiki(evt)
        elif evt.GetKeyCode() == wx.WXK_TAB:
            if evt.ShiftDown():
                self.ctrls.cbSearch.Navigate(wx.NavigationKeyEvent.IsBackward | 
                        wx.NavigationKeyEvent.FromTab)
            else:
                self.ctrls.cbSearch.Navigate(wx.NavigationKeyEvent.IsForward | 
                        wx.NavigationKeyEvent.FromTab)
        else:
            evt.Skip()



class SearchPageDialog(wx.Dialog):   # TODO
    def __init__(self, pWiki, ID, title="",
                 pos=wx.DefaultPosition, size=wx.DefaultSize,
                 style=wx.NO_3D|wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER):
        d = wx.PreDialog()
        self.PostCreate(d)

        self.pWiki = pWiki

        res = wx.xrc.XmlResource.Get()
        res.LoadOnDialog(self, self.pWiki, "SearchPageDialog")

        self.ctrls = XrcControls(self)

        self.ctrls.btnClose.SetId(wx.ID_CANCEL)
        
        self.firstFind = True
        self._refreshSearchHistoryCombo()
        
        # Fixes focus bug under Linux
        self.SetFocus()

        wx.EVT_BUTTON(self, GUI_ID.btnFindNext, self.OnFindNext)        
        wx.EVT_BUTTON(self, GUI_ID.btnReplace, self.OnReplace)
        wx.EVT_BUTTON(self, GUI_ID.btnReplaceAll, self.OnReplaceAll)
        wx.EVT_BUTTON(self, wx.ID_CANCEL, self.OnClose)
        wx.EVT_COMBOBOX(self, GUI_ID.cbSearch, self.OnSearchComboSelected) 
        wx.EVT_CLOSE(self, self.OnClose)


    def OnClose(self, evt):
        self.pWiki.findDlg = None
        self.Destroy()


    def _buildSearchOperation(self):
        sarOp = SearchReplaceOperation()
        sarOp.searchStr = guiToUni(self.ctrls.cbSearch.GetValue())
        sarOp.replaceOp = False
        sarOp.booleanOp = False
        sarOp.caseSensitive = self.ctrls.cbCaseSensitive.GetValue()
        sarOp.wholeWord = self.ctrls.cbWholeWord.GetValue()
        sarOp.cycleToStart = False
        
        if self.ctrls.cbRegEx.GetValue():
            sarOp.wildCard = 'regex'
        else:
            sarOp.wildCard = 'no'

        sarOp.wikiWide = False

        return sarOp


    def buildHistoryTuple(self):
        """
        Build a tuple for the search history from current settings
        """
        return (
                guiToUni(self.ctrls.cbSearch.GetValue()),
                guiToUni(self.ctrls.txtReplace.GetValue()),
                bool(self.ctrls.cbCaseSensitive.GetValue()),
                bool(self.ctrls.cbWholeWord.GetValue()),
                bool(self.ctrls.cbRegEx.GetValue())
                )


    def showHistoryTuple(self, tpl):
        """
        Load settings from history tuple into controls
        """
        self.ctrls.cbSearch.SetValue(uniToGui(tpl[0]))
        self.ctrls.txtReplace.SetValue(uniToGui(tpl[1]))
        self.ctrls.cbCaseSensitive.SetValue(bool(tpl[2]))
        self.ctrls.cbWholeWord.SetValue(bool(tpl[3]))
        self.ctrls.cbRegEx.SetValue(bool(tpl[4]))


    def addCurrentToHistory(self):
        tpl = self.buildHistoryTuple()
        hist = wx.GetApp().getPageSearchHistory()
        try:
            pos = hist.index(tpl)
            del hist[pos]
            hist.insert(0, tpl)
        except ValueError:
            # tpl not in hist
            hist.insert(0, tpl)
            if len(hist) > 10:
                hist = hist[:10]
            
        wx.GetApp().setPageSearchHistory(hist)
#         self.ctrls.cbSearch.Clear()
#         self.ctrls.cbSearch.AppendItems([tpl[0] for tpl in hist])
        self._refreshSearchHistoryCombo()
        text = self.ctrls.cbSearch.GetValue()
        self.ctrls.cbSearch.SetValue(text)

    def _refreshSearchHistoryCombo(self):
        hist = wx.GetApp().getPageSearchHistory()
        self.ctrls.cbSearch.Clear()
        self.ctrls.cbSearch.AppendItems([tpl[0] for tpl in hist])


    def displayErrorMessage(self, errorStr, e=u""):
        """
        Pops up an error dialog box
        """
        wx.MessageBox(uniToGui(u"%s. %s." % (errorStr, e)), _(u"Error!"),
            wx.OK, self)


    def _nextSearch(self, sarOp):
        editor = self.pWiki.getActiveEditor()
        if self.ctrls.rbSearchFrom.GetSelection() == 0:
            # Search from cursor
            contPos = editor.getContinuePosForSearch(sarOp)
        else:
            # Search from beginning
            contPos = 0
            self.ctrls.rbSearchFrom.SetSelection(0)
            
        self.addCurrentToHistory()
        start, end = editor.executeSearch(sarOp,
                contPos)[:2]
        if start == -1:
            # No matches found
            if contPos != 0:
                # We started not at beginning, so ask if to wrap around
                result = wx.MessageBox(_(u"End of document reached. "
                        u"Continue at beginning?"),
                        _(u"Continue at beginning?"),
                        wx.YES_NO | wx.YES_DEFAULT | wx.ICON_QUESTION, self)
                if result == wx.NO:
                    return

                start, end = editor.executeSearch(
                        sarOp, 0)[:2]
                if start != -1:
                    return

            # no more matches possible -> show dialog
            wx.MessageBox(_(u"No matches found"),
                    _(u"No matches found"), wx.OK, self)



    def OnFindNext(self, evt):
        sarOp = self._buildSearchOperation()
        sarOp.replaceOp = False
        self.addCurrentToHistory()
        try:
            self._nextSearch(sarOp)
            self.firstFind = False
        except re.error, e:
            self.displayErrorMessage(_(u'Error in regular expression'),
                    _(unicode(e)))



    def OnReplace(self, evt):
        sarOp = self._buildSearchOperation()
        sarOp.replaceStr = guiToUni(self.ctrls.txtReplace.GetValue())
        sarOp.replaceOp = True
        self.addCurrentToHistory()
        try:
            self.pWiki.getActiveEditor().executeReplace(sarOp)
            self._nextSearch(sarOp)
        except re.error, e:
            self.displayErrorMessage(_(u'Error in regular expression'),
                    _(unicode(e)))



    def OnReplaceAll(self, evt):
        sarOp = self._buildSearchOperation()
        sarOp.replaceStr = guiToUni(self.ctrls.txtReplace.GetValue())
        sarOp.replaceOp = True
        sarOp.cycleToStart = False
        lastSearchPos = 0
        editor = self.pWiki.getActiveEditor()
        self.addCurrentToHistory()
        replaceCount = 0
        editor.BeginUndoAction()
        try:
            while True:
                nextReplacePos = editor.executeSearch(sarOp, lastSearchPos)[1]
                if nextReplacePos == -1:
                    break
                replaceCount += 1
                nextSearchPos = editor.executeReplace(sarOp)
                if lastSearchPos == nextReplacePos:
                    # Otherwise it would run infinitely
                    break
                lastSearchPos = nextSearchPos
        finally:
            editor.EndUndoAction()
            
        wx.MessageBox(_(u"%i replacements done") % replaceCount,
                _(u"Replace All"), wx.OK, self)


    def OnSearchComboSelected(self, evt):
        hist = wx.GetApp().getPageSearchHistory()
        self.showHistoryTuple(hist[evt.GetSelection()])




class WikiPageListConstructionDialog(wx.Dialog, MiscEventSourceMixin):   # TODO
    def __init__(self, parent, pWiki, ID, value=None, allowOrdering=True,
            title="Page List", pos=wx.DefaultPosition, size=wx.DefaultSize,
            style=wx.NO_3D|wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER):
        d = wx.PreDialog()
        self.PostCreate(d)
        MiscEventSourceMixin.__init__(self)

        self.pWiki = pWiki
        self.value = value
        
        self.pageListData = []  # Wiki words in the left pagelist
        self.resultListData = []

        res = wx.xrc.XmlResource.Get()
        res.LoadOnDialog(self, parent, "WikiPageListConstructionDialog")
        
        self.ctrls = XrcControls(self)
        
        self.ctrls.btnOk.SetId(wx.ID_OK)
        self.ctrls.btnCancel.SetId(wx.ID_CANCEL)
        
        self.ctrls.tfPageListToAdd.SetValue(uniToGui(
                self.pWiki.getCurrentWikiWord()))

        if self.value is not None:
            item = self.value.searchOpTree
            
            if item.CLASS_PERSID == "AllPages":
                self.ctrls.rbPagesAll.SetValue(True)
            elif item.CLASS_PERSID == "RegexPage":
                self.ctrls.rbPagesMatchRe.SetValue(True)
                self.ctrls.tfMatchRe.SetValue(item.getPattern())
            elif item.CLASS_PERSID == "ListItemWithSubtreePages":
                self.ctrls.rbPagesInList.SetValue(True)
                self.pageListData = item.rootWords[:]
                self.ctrls.lbPageList.AppendItems(self.pageListData)
                if item.level == -1:
                    self.ctrls.tfSubtreeLevels.SetValue(u"")
                else:
                    self.ctrls.tfSubtreeLevels.SetValue(u"%i" % item.level)
                    
            self.ctrls.chOrdering.SetSelection(
                    self._ORDERNAME_TO_CHOICE[self.value.ordering])

        if not allowOrdering:
            self.ctrls.chOrdering.SetSelection(self._ORDERNAME_TO_CHOICE["no"])
            self.ctrls.chOrdering.Enable(False)
            
        # Fixes focus bug under Linux
        self.SetFocus()

        wx.EVT_TEXT(self, GUI_ID.tfSubtreeLevels,
                lambda evt: self.ctrls.rbPagesInList.SetValue(True))
        wx.EVT_TEXT(self, GUI_ID.tfMatchRe,
                lambda evt: self.ctrls.rbPagesMatchRe.SetValue(True))
        
        wx.EVT_BUTTON(self, wx.ID_CANCEL, self.OnClose)        
        wx.EVT_CLOSE(self, self.OnClose)
        wx.EVT_BUTTON(self, wx.ID_OK, self.OnOk)

        wx.EVT_TEXT_ENTER(self, GUI_ID.tfPageListToAdd, self.OnPageListAdd)
        wx.EVT_BUTTON(self, GUI_ID.btnPageListUp, self.OnPageListUp) 
        wx.EVT_BUTTON(self, GUI_ID.btnPageListDown, self.OnPageListDown) 
        wx.EVT_BUTTON(self, GUI_ID.btnPageListSort, self.OnPageListSort) 

        wx.EVT_BUTTON(self, GUI_ID.btnPageListAdd, self.OnPageListAdd) 
        wx.EVT_BUTTON(self, GUI_ID.btnPageListDelete, self.OnPageListDelete) 
        wx.EVT_BUTTON(self, GUI_ID.btnPageListClearList, self.OnPageListClearList) 

        wx.EVT_BUTTON(self, GUI_ID.btnPageListCopyToClipboard,
                self.OnPageListCopyToClipboard) 

        wx.EVT_BUTTON(self, GUI_ID.btnPageListAddFromClipboard,
                self.OnPageListAddFromClipboard) 
        wx.EVT_BUTTON(self, GUI_ID.btnPageListOverwriteFromClipboard,
                self.OnPageListOverwriteFromClipboard) 
        wx.EVT_BUTTON(self, GUI_ID.btnPageListIntersectWithClipboard,
                self.OnPageListIntersectWithClipboard) 

        wx.EVT_BUTTON(self, GUI_ID.btnResultListPreview, self.OnResultListPreview) 
        wx.EVT_BUTTON(self, GUI_ID.btnResultCopyToClipboard,
                self.OnResultCopyToClipboard) 


#         wx.EVT_BUTTON(self, GUI_ID.btnReplace, self.OnReplace)
#         wx.EVT_BUTTON(self, GUI_ID.btnReplaceAll, self.OnReplaceAll)
#         wx.EVT_BUTTON(self, wxID_CANCEL, self.OnClose)        
#         wx.EVT_CLOSE(self, self.OnClose)

    _ORDERCHOICE_TO_NAME = {
            0: "natural",
            1: "ascending",
            2: "asroottree",
            3: "no"
    }

    _ORDERNAME_TO_CHOICE = {
            "natural": 0,
            "ascending": 1,
            "asroottree": 2,
            "no": 3
    }


    def setValue(self, value):
        self.value = value

    def getValue(self):
        return self.value


    def _buildListPagesOperation(self):
        """
        Construct a ListWikiPagesOperation according to current content of the
        dialog
        """
        import SearchAndReplace as Sar
        
        lpOp = Sar.ListWikiPagesOperation()
        
        if self.ctrls.rbPagesAll.GetValue():
            item = Sar.AllWikiPagesNode(lpOp)
        elif self.ctrls.rbPagesMatchRe.GetValue():
            pattern = self.ctrls.tfMatchRe.GetValue()
            try:
                re.compile(pattern, re.DOTALL | re.UNICODE | re.MULTILINE)
            except re.error, e:
                wx.MessageBox(_(u"Bad regular expression '%s':\n%s") %
                        (pattern, _(unicode(e))), _(u"Error in regular expression"),
                        wx.OK, self)
                return None
            item = Sar.RegexWikiPageNode(lpOp, pattern)
        elif self.ctrls.rbPagesInList.GetValue():
            try:
                level = int(self.ctrls.tfSubtreeLevels.GetValue())
                if level < 0:
                    raise ValueError
            except ValueError:
                level = -1

            item = Sar.ListItemWithSubtreeWikiPagesNode(lpOp,
                    self.pageListData[:], level)
        else:
            return None
            
        lpOp.setSearchOpTree(item)
        lpOp.ordering = self._ORDERCHOICE_TO_NAME[
                self.ctrls.chOrdering.GetSelection()]

        return lpOp


    def OnOk(self, evt):
        val = self._buildListPagesOperation()
        if val is None:
            return
            
        self.value = val 
        if self.IsModal():
            self.EndModal(wx.ID_OK)
        else:
            self.Destroy()
            self.fireMiscEventProps({"nonmodal closed": wx.ID_OK,
                    "listWikiPagesOp": self.value})

    def OnClose(self, evt):
        self.value = None
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()
            self.fireMiscEventProps({"nonmodal closed": wx.ID_CANCEL,
                    "listWikiPagesOp": None})


    def OnPageListUp(self, evt):
        sel = self.ctrls.lbPageList.GetSelection()
        if sel == wx.NOT_FOUND or sel == 0:
            return
            
        dispWord = self.ctrls.lbPageList.GetString(sel)
        word = self.pageListData[sel]
        
        self.ctrls.lbPageList.Delete(sel)
        del self.pageListData[sel]
        
        self.ctrls.lbPageList.Insert(dispWord, sel - 1)
        self.pageListData.insert(sel - 1, word)
        self.ctrls.lbPageList.SetSelection(sel - 1)
        
        
    def OnPageListDown(self, evt):
        sel = self.ctrls.lbPageList.GetSelection()
        if sel == wx.NOT_FOUND or sel == len(self.pageListData) - 1:
            return

        dispWord = self.ctrls.lbPageList.GetString(sel)
        word = self.pageListData[sel]
        
        self.ctrls.lbPageList.Delete(sel)
        del self.pageListData[sel]
        
        self.ctrls.lbPageList.Insert(dispWord, sel + 1)
        self.pageListData.insert(sel + 1, word)
        self.ctrls.lbPageList.SetSelection(sel + 1)


    def OnPageListSort(self, evt):
        self.ctrls.rbPagesInList.SetValue(True)

        self.pWiki.getCollator().sort(self.pageListData)
        
        self.ctrls.lbPageList.Clear()
        self.ctrls.lbPageList.AppendItems(self.pageListData)


    def OnPageListAdd(self, evt):
        self.ctrls.rbPagesInList.SetValue(True)

        word = guiToUni(self.ctrls.tfPageListToAdd.GetValue())

        langHelper = wx.GetApp().createWikiLanguageHelper(
                self.pWiki.getWikiDefaultWikiLanguage())
        word = langHelper.extractWikiWordFromLink(word,
                self.pWiki.getWikiDocument())
        if word is None:
            return

        if word in self.pageListData:
            return  # Already in list

        sel = self.ctrls.lbPageList.GetSelection()
        if sel == wx.NOT_FOUND:
            self.ctrls.lbPageList.Append(uniToGui(word))
            self.pageListData.append(word)
            self.ctrls.lbPageList.SetSelection(len(self.pageListData) - 1)
        else:
            self.ctrls.lbPageList.Insert(uniToGui(word), sel + 1)
            self.pageListData.insert(sel + 1, word)
            self.ctrls.lbPageList.SetSelection(sel + 1)
            
        self.ctrls.tfPageListToAdd.SetValue(u"")


    def OnPageListDelete(self, evt):
        self.ctrls.rbPagesInList.SetValue(True)

        sel = self.ctrls.lbPageList.GetSelection()
        if sel == wx.NOT_FOUND:
            return

        self.ctrls.lbPageList.Delete(sel)
        del self.pageListData[sel]
        
        count = len(self.pageListData)
        if count == 0:
            return
        
        if sel >= count:
            sel = count - 1
        self.ctrls.lbPageList.SetSelection(sel)


    def OnPageListClearList(self, evt):
        self.ctrls.rbPagesInList.SetValue(True)

        self.ctrls.lbPageList.Clear()
        self.pageListData = []
        

    def OnPageListAddFromClipboard(self, evt):
        """
        Take wiki words from clipboard and enter them into the list
        """
        self.ctrls.rbPagesInList.SetValue(True)

        text = getTextFromClipboard()
        if text:
            pageAst = self.pWiki.getCurrentDocPage().parseTextInContext(text)
            wwNodes = pageAst.iterDeepByName("wikiWord")
            found = {}
            # First fill found with already existing entries
            for w in self.pageListData:
                found[w] = None

            for node in wwNodes:
                w = node.wikiWord
                if not found.has_key(w):
                    self.ctrls.lbPageList.Append(uniToGui(w))
                    self.pageListData.append(w)
                    found[w] = None


    def OnPageListOverwriteFromClipboard(self, evt):
        self.ctrls.lbPageList.Clear()
        self.pageListData = []
        
        self.OnPageListAddFromClipboard(evt)


    def OnPageListIntersectWithClipboard(self, evt):
        """
        Take wiki words from clipboard and intersect with the list
        """
        self.ctrls.rbPagesInList.SetValue(True)

        text = getTextFromClipboard()
        
        if text:
            pageAst = self.pWiki.getCurrentDocPage().parseTextInContext(text)
            wwNodes = pageAst.iterDeepByName("wikiWord")
            found = {}

            for node in wwNodes:
                w = node.wikiWord
                found[w] = None

            pageList = self.pageListData
            self.pageListData = []
            self.ctrls.lbPageList.Clear()

            # Now fill all with already existing entries
            for w in pageList:
                if found.has_key(w):
                    self.ctrls.lbPageList.Append(uniToGui(w))
                    self.pageListData.append(w)
                    del found[w]


    def OnPageListCopyToClipboard(self, evt):
        langHelper = wx.GetApp().createWikiLanguageHelper(
                self.pWiki.getWikiDefaultWikiLanguage())

        wordsText = u"".join([
                langHelper.createStableLinksFromWikiWords((w,)) + "\n"
                for w in self.pageListData])

        copyTextToClipboard(wordsText)


    def OnResultCopyToClipboard(self, evt):
        langHelper = wx.GetApp().createWikiLanguageHelper(
                self.pWiki.getWikiDefaultWikiLanguage())

        wordsText = u"".join([
                langHelper.createStableLinksFromWikiWords((w,)) + "\n"
                for w in self.resultListData])

        copyTextToClipboard(wordsText)


    def OnResultListPreview(self, evt):
        lpOp = self._buildListPagesOperation()
        
        if lpOp is None:
            return

        self.SetCursor(wx.HOURGLASS_CURSOR)
        self.Freeze()
        try:
            words = self.pWiki.getWikiDocument().searchWiki(lpOp)
            
            self.ctrls.lbResultPreview.Clear()
            self.ctrls.lbResultPreview.AppendItems(words)
#             for w in words:
#                 self.ctrls.lbResultPreview.Append(uniToGui(w))
                
            self.resultListData = words
        finally:
            self.Thaw()
            self.SetCursor(wx.NullCursor)



class SearchWikiDialog2(wx.Dialog, MiscEventSourceMixin):
    def __init__(self, parent, ID, srListBox=None, allowOrdering=True,
            allowOkCancel=True, value=None,
            title="Search Wiki", pos=wx.DefaultPosition, size=wx.DefaultSize,
            style=wx.NO_3D|wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER):
        d = wx.PreDialog()
        self.PostCreate(d)

        self.mainControl = parent

        res = wx.xrc.XmlResource.Get()
        res.LoadOnDialog(self, parent, "SearchWikiDialog2")
        if srListBox is None:
            srListBox = SearchResultListBox(self, self.mainControl,
                    GUI_ID.htmllbPages)
        else:
            srListBox.Reparent(self)

        res.AttachUnknownControl("htmllbPages", srListBox, self)
        self.ctrls = XrcControls(self)

        if allowOkCancel:
            self.ctrls.btnOk.SetId(wx.ID_OK)
            self.ctrls.btnCancel.SetId(wx.ID_CANCEL)
        else:
            self.ctrls.btnOk.SetId(wx.ID_CANCEL)
            self.ctrls.btnCancel.Show(False)

        self.ctrls.tfPageListToAdd.SetValue(uniToGui(
                self.mainControl.getCurrentWikiWord()))

        self.ctrls.cbSearch.SetWindowStyle(self.ctrls.cbSearch.GetWindowStyle()
                | wx.TE_PROCESS_ENTER)

        self.listNeedsRefresh = True  # Reflects listbox content current
                                      # search criteria?

        self.savedSearches = None
        self.foundPages = []

        self.listPagesOperation = ListWikiPagesOperation()
        self._refreshSavedSearchesList()
        self._refreshSearchHistoryCombo()
        
        # Fixes focus bug under Linux
        self.SetFocus()

        wx.EVT_BUTTON(self, GUI_ID.btnFindPages, self.OnSearchWiki)
        wx.EVT_BUTTON(self, GUI_ID.btnSetPageList, self.OnSetPageList)
        wx.EVT_BUTTON(self, GUI_ID.btnFindNext, self.OnFindNext)        
        wx.EVT_BUTTON(self, GUI_ID.btnReplace, self.OnReplace)
        wx.EVT_BUTTON(self, GUI_ID.btnReplaceAll, self.OnReplaceAll)
        wx.EVT_BUTTON(self, GUI_ID.btnSaveSearch, self.OnSaveSearch)
        wx.EVT_BUTTON(self, GUI_ID.btnDeleteSearches, self.OnDeleteSearches)
        wx.EVT_BUTTON(self, GUI_ID.btnLoadSearch, self.OnLoadSearch)
        wx.EVT_BUTTON(self, GUI_ID.btnLoadAndRunSearch, self.OnLoadAndRunSearch)
        wx.EVT_BUTTON(self, GUI_ID.btnOptions, self.OnOptions)
        wx.EVT_BUTTON(self, GUI_ID.btnCopyPageNamesToClipboard,
                self.OnCopyPageNamesToClipboard)
        wx.EVT_BUTTON(self, GUI_ID.btnAsResultlist, self.OnCmdAsResultlist)
        wx.EVT_BUTTON(self, GUI_ID.btnAsTab, self.OnCmdAsTab)

        wx.EVT_CHAR(self.ctrls.cbSearch, self.OnCharToFind)
        wx.EVT_CHAR(self.ctrls.rboxSearchType, self.OnCharToFind)
        wx.EVT_CHAR(self.ctrls.cbCaseSensitive, self.OnCharToFind)
        wx.EVT_CHAR(self.ctrls.cbWholeWord, self.OnCharToFind)

        wx.EVT_COMBOBOX(self, GUI_ID.cbSearch, self.OnSearchComboSelected) 
        wx.EVT_LISTBOX_DCLICK(self, GUI_ID.lbSavedSearches, self.OnLoadAndRunSearch)
        wx.EVT_RADIOBOX(self, GUI_ID.rboxSearchType, self.OnRadioBox)
        wx.EVT_BUTTON(self, wx.ID_CANCEL, self.OnClose)        
        wx.EVT_CLOSE(self, self.OnClose)
        
        wx.EVT_TEXT(self, GUI_ID.cbSearch, self.OnListRefreshNeeded)
        wx.EVT_CHECKBOX(self, GUI_ID.cbCaseSensitive, self.OnListRefreshNeeded)
        wx.EVT_CHECKBOX(self, GUI_ID.cbWholeWord, self.OnListRefreshNeeded)


    def displayErrorMessage(self, errorStr, e=u""):
        """
        Pops up an error dialog box
        """
        wx.MessageBox(uniToGui(u"%s. %s." % (errorStr, e)), _(u"Error!"),
            wx.OK, self)


    def buildSearchReplaceOperation(self):
        searchType = self.ctrls.rboxSearchType.GetSelection()
        
        sarOp = SearchReplaceOperation()
        sarOp.searchStr = guiToUni(self.ctrls.cbSearch.GetValue())
        sarOp.booleanOp = searchType == Consts.SEARCHTYPE_BOOLEANREGEX
        sarOp.caseSensitive = self.ctrls.cbCaseSensitive.GetValue()
        sarOp.wholeWord = self.ctrls.cbWholeWord.GetValue()
        sarOp.cycleToStart = False
        sarOp.wildCard = 'regex' if searchType != Consts.SEARCHTYPE_ASIS else 'no'
        sarOp.wikiWide = True
        sarOp.listWikiPagesOp = self.listPagesOperation

        if not sarOp.booleanOp:
            sarOp.replaceStr = guiToUni(self.ctrls.txtReplace.GetValue())
            
        return sarOp


    def showSearchReplaceOperation(self, sarOp):
        self.ctrls.cbSearch.SetValue(uniToGui(sarOp.searchStr))
        if sarOp.booleanOp:
            self.ctrls.rboxSearchType.SetSelection(Consts.SEARCHTYPE_BOOLEANREGEX)
        else:
            if sarOp.wildCard == 'regex':
                self.ctrls.rboxSearchType.SetSelection(Consts.SEARCHTYPE_REGEX)
            else:
                self.ctrls.rboxSearchType.SetSelection(Consts.SEARCHTYPE_ASIS)

        self.ctrls.cbCaseSensitive.SetValue(sarOp.caseSensitive)
        self.ctrls.cbWholeWord.SetValue(sarOp.wholeWord)

        if not sarOp.booleanOp and sarOp.replaceOp:
            self.ctrls.txtReplace.SetValue(uniToGui(sarOp.replaceStr))

        self.listPagesOperation = sarOp.listWikiPagesOp

        self.OnRadioBox(None)  # Refresh settings


    def _refreshPageList(self):
        self.ctrls.htmllbPages.showSearching()
        self.SetCursor(wx.HOURGLASS_CURSOR)
        self.Freeze()
        try:
            sarOp = self.buildSearchReplaceOperation()

            if len(sarOp.searchStr) > 0:
                self.foundPages = self.mainControl.getWikiDocument().searchWiki(sarOp)
                self.mainControl.getCollator().sort(self.foundPages)
                self.ctrls.htmllbPages.showFound(sarOp, self.foundPages,
                        self.mainControl.getWikiDocument())
            else:
                self.foundPages = []
                self.ctrls.htmllbPages.showFound(None, None, None)

            self.listNeedsRefresh = False

        finally:
            self.Thaw()
            self.SetCursor(wx.NullCursor)
            self.ctrls.htmllbPages.ensureNotShowSearching()


    def OnSearchWiki(self, evt):
        try:
            self._refreshPageList()
            self.addCurrentToHistory()
            if not self.ctrls.htmllbPages.IsEmpty():
                self.ctrls.htmllbPages.SetFocus()
                self.ctrls.htmllbPages.SetSelection(0)
        except re.error, e:
            self.displayErrorMessage(_(u'Error in regular expression'),
                    _(unicode(e)))

            
    def OnSetPageList(self, evt):
        """
        Show the Page List dialog
        """
        dlg = WikiPageListConstructionDialog(self, self.GetParent(), -1,
                value=self.listPagesOperation, allowOrdering=False)

#         result = dlg.ShowModal()
#         dlg.Destroy()
#         if result == wxID_OK:
#             self.listPagesOperation = dlg.getValue()
#             pass

        dlg.getMiscEvent().addListener(KeyFunctionSink((
                ("nonmodal closed", self.onNonmodalClosedPageList),
        )), False)

        self.Show(False)
        dlg.Show(True)

    def onNonmodalClosedPageList(self, miscevt):
        plop = miscevt.get("listWikiPagesOp")
        if plop is not None:
            self.listPagesOperation = plop

        self.Show(True)


    def OnListRefreshNeeded(self, evt):
        self.listNeedsRefresh = True

    def OnFindNext(self, evt):
        self._findNext()

    def _findNext(self):
        if self.listNeedsRefresh:
            try:
                # Refresh list and start from beginning
                self._refreshPageList()
            except re.error, e:
                self.displayErrorMessage(_(u'Error in regular expression'),
                        _(unicode(e)))
                return

        self.addCurrentToHistory()
        if self.ctrls.htmllbPages.GetCount() == 0:
            return
        
        try:
            while True:            
                    
                #########self.ctrls.lb.SetSelection(self.listPosNext)
                
                wikiWord = guiToUni(self.ctrls.htmllbPages.GetSelectedWord())
                
                if not wikiWord:
                    self.ctrls.htmllbPages.SetSelection(0)
                    wikiWord = guiToUni(self.ctrls.htmllbPages.GetSelectedWord())
    
                if self.mainControl.getCurrentWikiWord() != wikiWord:
                    self.mainControl.openWikiPage(wikiWord)
                    nextOnPage = False
                else:
                    nextOnPage = True
    
                searchOp = self.buildSearchReplaceOperation()
                searchOp.replaceOp = False
                if nextOnPage:
                    pagePosNext = self.mainControl.getActiveEditor().executeSearch(searchOp,
                            -2)[1]
                else:
                    pagePosNext = self.mainControl.getActiveEditor().executeSearch(searchOp,
                            0)[1]
                    
                if pagePosNext != -1:
                    return  # Found
                    
                if self.ctrls.htmllbPages.GetSelection() == \
                        self.ctrls.htmllbPages.GetCount() - 1:
                    # Nothing more found on the last page in list, so back to
                    # begin of list and stop
                    self.ctrls.htmllbPages.SetSelection(0)
                    return
                    
                # Otherwise: Go to next page in list            
                self.ctrls.htmllbPages.SetSelection(
                        self.ctrls.htmllbPages.GetSelection() + 1)
        except re.error, e:
            self.displayErrorMessage(_(u'Error in regular expression'),
                    _(unicode(e)))



    def OnReplace(self, evt):
        sarOp = self.buildSearchReplaceOperation()
        sarOp.replaceOp = True
        try:
            self.mainControl.getActiveEditor().executeReplace(sarOp)
        except re.error, e:
            self.displayErrorMessage(_(u'Error in regular expression'),
                    _(unicode(e)))
            return

        self._findNext()


    def OnReplaceAll(self, evt):
        answer = wx.MessageBox(_(u"Replace all occurrences?"), _(u"Replace All"),
                wx.YES_NO | wx.NO_DEFAULT, self)
        
        if answer == wx.NO:
            return

        try:
            self._refreshPageList()
            
            if self.ctrls.htmllbPages.GetCount() == 0:
                return
                
            # self.pWiki.saveCurrentDocPage()
            
            sarOp = self.buildSearchReplaceOperation()
            sarOp.replaceOp = True
            
            # wikiData = self.pWiki.getWikiData()
            wikiDocument = self.mainControl.getWikiDocument()
            self.addCurrentToHistory()
            
            replaceCount = 0
    
            for i in xrange(self.ctrls.htmllbPages.GetCount()):
                self.ctrls.htmllbPages.SetSelection(i)
                wikiWord = guiToUni(self.ctrls.htmllbPages.GetSelectedWord())
                wikiPage = wikiDocument.getWikiPageNoError(wikiWord)
                text = wikiPage.getLiveTextNoTemplate()
                if text is None:
                    continue
    
                charStartPos = 0
    
                while True:
                    try:
                        found = sarOp.searchText(text, charStartPos)
                        start, end = found[:2]
                    except:
                        # Regex error -> Stop searching
                        return
                        
                    if start is None: break
                    
                    repl = sarOp.replace(text, found)
                    text = text[:start] + repl + text[end:]  # TODO Faster?
                    charStartPos = start + len(repl)
                    replaceCount += 1
                    if start == end:
                        # Otherwise replacing would go infinitely
                        break

                wikiPage.replaceLiveText(text)
                    
            self._refreshPageList()
            
            wx.MessageBox(_(u"%i replacements done") % replaceCount,
                    _(u"Replace All"),
                wx.OK, self)        

        except re.error, e:
            self.displayErrorMessage(_(u'Error in regular expression'),
                    _(unicode(e)))


    def addCurrentToHistory(self):
        sarOp = self.buildSearchReplaceOperation()
        try:
            sarOp.rebuildSearchOpTree()
        except re.error:
            # Ignore silently
            return
        data = sarOp.getPackedSettings()
        tpl = (sarOp.searchStr, sarOp.getPackedSettings())
        hist = wx.GetApp().getWikiSearchHistory()
        try:
            pos = hist.index(tpl)
            del hist[pos]
            hist.insert(0, tpl)
        except ValueError:
            # tpl not in hist
            hist.insert(0, tpl)
            if len(hist) > 10:
                hist = hist[:10]
            
        wx.GetApp().setWikiSearchHistory(hist)
        text = self.ctrls.cbSearch.GetValue()
        self._refreshSearchHistoryCombo()
#         self.ctrls.cbSearch.Clear()
#         self.ctrls.cbSearch.AppendItems([tpl[0] for tpl in hist])
        self.ctrls.cbSearch.SetValue(text)



    # TODO Store search mode
    def OnSaveSearch(self, evt):
        sarOp = self.buildSearchReplaceOperation()
        try:
            sarOp.rebuildSearchOpTree()
        except re.error, e:
            self.mainControl.displayErrorMessage(_(u'Error in regular expression'),
                    _(unicode(e)))
            return

        if len(sarOp.searchStr) > 0:
            title = sarOp.getTitle()
            while True:
                title = guiToUni(wx.GetTextFromUser(_(u"Title:"),
                        _(u"Choose search title"), title, self))
                if title == u"":
                    return  # Cancel
                    
#                 if title in self.pWiki.getWikiData().getSavedSearchTitles():
                if (u"savedsearch/" + title) in self.mainControl.getWikiData()\
                        .getDataBlockUnifNamesStartingWith(
                        u"savedsearch/" + title):

                    answer = wx.MessageBox(
                            _(u"Do you want to overwrite existing search '%s'?") %
                            title, _(u"Overwrite search"),
                            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self)
                    if answer == wx.NO:
                        continue

#                 self.pWiki.getWikiData().saveSearch(title,
#                         sarOp.getPackedSettings())
                self.mainControl.getWikiData().storeDataBlock(
                        u"savedsearch/" + title, sarOp.getPackedSettings(),
                        storeHint=Consts.DATABLOCK_STOREHINT_INTERN)

                self._refreshSavedSearchesList()
                break
        else:
            self.mainControl.displayErrorMessage(
                    _(u"Invalid search string, can't save as view"))


    def OnRadioBox(self, evt):
        self.listNeedsRefresh = True
        booleanSearch = self.ctrls.rboxSearchType.GetSelection() == 1
        
        self.ctrls.txtReplace.Enable(not booleanSearch)
        self.ctrls.btnFindNext.Enable(not booleanSearch)
        self.ctrls.btnReplace.Enable(not booleanSearch)
        self.ctrls.btnReplaceAll.Enable(not booleanSearch)


    def OnOptions(self, evt):
        dlg = SearchWikiOptionsDialog(self, self.GetParent(), -1)
        dlg.CenterOnParent(wx.BOTH)

        dlg.ShowModal()
        dlg.Destroy()


    def getResultListPositionTuple(self):
        return getRelativePositionTupleToAncestor(self.ctrls.htmllbPages, self)


    def OnCmdAsResultlist(self, evt):
        self.Hide()
        
        ownPos = self.GetPositionTuple()
        oldRelBoxPos = self.getResultListPositionTuple()
        
        frame = FastSearchPopup(self.GetParent(), self.mainControl, -1,
                srListBox=self.ctrls.htmllbPages)
        frame.setSearchOp(self.buildSearchReplaceOperation())
        
        newRelBoxPos = frame.getResultListPositionTuple()

        # A bit math to ensure that result list in both windows is placed
        # at same position (looks more cool)
        otherPos = (ownPos[0] + oldRelBoxPos[0] - newRelBoxPos[0],
                ownPos[1] + oldRelBoxPos[1] - newRelBoxPos[1])
        
        setWindowPos(frame, pos=otherPos, fullVisible=True)
        self.mainControl.wwSearchDlgs.append(frame)
        frame.Show()
        self.Close()


    def OnCmdAsTab(self, evt):
        self.Hide()

        maPanel = self.mainControl.getMainAreaPanel()
        presenter = LayeredControlPanel(maPanel)
        subCtl = SearchResultPresenterControl(presenter, self.mainControl,
                self.GetParent(), -1, srListBox=self.ctrls.htmllbPages)
        presenter.setSubControl("search result list", subCtl)
        presenter.switchSubControl("search result list")
        maPanel.appendPresenterTab(presenter)
        subCtl.setSearchOp(self.buildSearchReplaceOperation())

        maPanel.showPresenter(presenter)
        self.Close()


    def OnClose(self, evt):
        try:
            self.mainControl.wwSearchDlgs.remove(self)
        except ValueError:
            if self is self.mainControl.mainWwSearchDlg:
                self.mainControl.mainWwSearchDlg = None

        self.Destroy()


    def _refreshSavedSearchesList(self):
        unifNames = self.mainControl.getWikiData()\
                .getDataBlockUnifNamesStartingWith(u"savedsearch/")

#         self.savedSearches = self.pWiki.getWikiData().getSavedSearchTitles()
        self.savedSearches = [name[12:] for name in unifNames]
        self.mainControl.getCollator().sort(self.savedSearches)

        self.ctrls.lbSavedSearches.Clear()
        for search in self.savedSearches:
            self.ctrls.lbSavedSearches.Append(uniToGui(search))


    def _refreshSearchHistoryCombo(self):
        hist = wx.GetApp().getWikiSearchHistory()
        self.ctrls.cbSearch.Clear()
        self.ctrls.cbSearch.AppendItems([tpl[0] for tpl in hist])


    def OnDeleteSearches(self, evt):
        sels = self.ctrls.lbSavedSearches.GetSelections()
        
        if len(sels) == 0:
            return
            
        answer = wx.MessageBox(
                _(u"Do you want to delete %i search(es)?") % len(sels),
                _(u"Delete search"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self)
        if answer == wx.NO:
            return

        for s in sels:
#             self.pWiki.getWikiData().deleteSavedSearch(self.savedSearches[s])
            self.mainControl.getWikiData().deleteDataBlock(
                    u"savedsearch/" + self.savedSearches[s])
        self._refreshSavedSearchesList()


    def OnLoadSearch(self, evt):
        self._loadSearch()
        
    def OnLoadAndRunSearch(self, evt):
        if self._loadSearch():
            try:
                self._refreshPageList()
            except re.error, e:
                self.displayErrorMessage(_(u'Error in regular expression'),
                        _(unicode(e)))


    def _loadSearch(self):
        sels = self.ctrls.lbSavedSearches.GetSelections()
        
        if len(sels) != 1:
            return False
        
        datablock = self.mainControl.getWikiData().retrieveDataBlock(
                u"savedsearch/" + self.savedSearches[sels[0]])

        sarOp = SearchReplaceOperation()
        sarOp.setPackedSettings(datablock)
        
        self.showSearchReplaceOperation(sarOp)
        
        return True


    def OnSearchComboSelected(self, evt):
        hist = wx.GetApp().getWikiSearchHistory()
        sarOp = SearchReplaceOperation()
        sarOp.setPackedSettings(hist[evt.GetSelection()][1])
        
        self.showSearchReplaceOperation(sarOp)
        self.ctrls.txtReplace.SetValue(guiToUni(sarOp.replaceStr))


    def OnCopyPageNamesToClipboard(self, evt):
        langHelper = wx.GetApp().createWikiLanguageHelper(
                self.mainControl.getWikiDefaultWikiLanguage())

        wordsText = u"".join([
                langHelper.createStableLinksFromWikiWords((w,)) + "\n"
                for w in self.foundPages])

        copyTextToClipboard(wordsText)


    def OnCharToFind(self, evt):
        if (evt.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)):
            self.OnSearchWiki(evt)
        elif evt.GetKeyCode() == wx.WXK_TAB:
            if evt.ShiftDown():
                self.ctrls.cbSearch.Navigate(wx.NavigationKeyEvent.IsBackward | 
                        wx.NavigationKeyEvent.FromTab)
            else:
                self.ctrls.cbSearch.Navigate(wx.NavigationKeyEvent.IsForward | 
                        wx.NavigationKeyEvent.FromTab)
        else:
            evt.Skip()


















class SearchResultPresenterControl(wx.Panel):
    """
    Panel which can be added to presenter in main area panel as tab showing
    search results.
    """
    def __init__(self, presenter, mainControl, searchDialogParent, ID,
            srListBox=None):
        super(SearchResultPresenterControl, self).__init__(presenter, ID)

        self.mainControl = mainControl
        self.presenter = presenter
        self.searchDialogParent = searchDialogParent
        self.sarOp = None

        if srListBox is None:
            self.resultBox = SearchResultListBox(self, self.mainControl,
                    GUI_ID.htmllbPages)
        else:
            srListBox.Reparent(self)
            self.resultBox = srListBox

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.resultBox, 1, wx.EXPAND)


        buttonSizer = wx.BoxSizer(wx.HORIZONTAL)

        self.btnAsResultlist = wx.Button(self,
                GUI_ID.CMD_SEARCH_AS_RESULTLIST, label=_(u"As Resultlist"))
                # TODO Allow hotkey for button
        buttonSizer.Add(self.btnAsResultlist, 0, wx.EXPAND)

        self.btnAsWwSearch = wx.Button(self, GUI_ID.CMD_SEARCH_AS_WWSEARCH,
                label=_(u"As Full Search"))    # TODO Allow hotkey for button
        buttonSizer.Add(self.btnAsWwSearch, 0, wx.EXPAND)

        buttonSizer.AddStretchSpacer()

        res = wx.xrc.XmlResource.Get()
        self.tabContextMenu = res.LoadMenu("MenuSearchResultTabPopup")
        

        sizer.Add(buttonSizer, 0, wx.EXPAND)

        self.SetSizer(sizer)

        wx.EVT_BUTTON(self, GUI_ID.CMD_SEARCH_AS_RESULTLIST, self.OnCmdAsResultlist)
        wx.EVT_BUTTON(self, GUI_ID.CMD_SEARCH_AS_WWSEARCH, self.OnCmdAsWwSearch)

        wx.EVT_MENU(self.tabContextMenu, GUI_ID.CMD_SEARCH_AS_RESULTLIST, self.OnCmdAsResultlist)
        wx.EVT_MENU(self.tabContextMenu, GUI_ID.CMD_SEARCH_AS_WWSEARCH, self.OnCmdAsWwSearch)


    # Next two to fulfill presenter subcontrol protocol
    def close(self):
        pass

    def setLayerVisible(self, vis, scName):
        pass


    def setSearchOp(self, sarOp):
        """
        """
        self.sarOp = sarOp
        self.presenter.setTitle(_(u"<Search: %s>") % self.sarOp.searchStr)


    def getTabContextMenu(self):
        return self.tabContextMenu


    def OnCmdAsResultlist(self, evt):
        self.mainControl.getMainAreaPanel().detachPresenterTab(self.presenter)

        frame = FastSearchPopup(self.searchDialogParent, self.mainControl,
                -1, srListBox=self.resultBox)

        self.mainControl.wwSearchDlgs.append(frame)
        frame.setSearchOp(self.sarOp)
        frame.fixate()
        frame.Show()

        self.presenter.close()
        self.presenter.Destroy()


    def OnCmdAsWwSearch(self, evt):
        self.mainControl.getMainAreaPanel().detachPresenterTab(self.presenter)

        dlg = SearchWikiDialog(self.searchDialogParent, -1, srListBox=self.resultBox)
        dlg.showSearchReplaceOperation(self.sarOp)

        self.mainControl.wwSearchDlgs.append(dlg)
        dlg.Show()

        self.presenter.close()
        self.presenter.Destroy()

#         # Set focus to dialog (hackish)
#         wx.CallLater(100, dlg.SetFocus)




class FastSearchPopup(wx.Frame):
    """
    Popup window which appears when hitting Enter in the fast search text field
    in the main window.
    Using frame because wx.PopupWindow is not available on Mac OS
    """
    def __init__(self, parent, mainControl, ID, srListBox=None,
            pos=wx.DefaultPosition):
        wx.Frame.__init__(self, parent, ID, _(u"Fast Search"), pos=pos,
                style=wx.RESIZE_BORDER | wx.FRAME_FLOAT_ON_PARENT | wx.SYSTEM_MENU |
                wx.FRAME_TOOL_WINDOW | wx.CAPTION | wx.CLOSE_BOX ) # wx.FRAME_NO_TASKBAR)

        self.mainControl = mainControl
        self.sarOp = None
        self.firstMove = True  # Consume first move event
        self.fixed = False  # if window was moved, fix it to not close automatically 

        if srListBox is None:
            self.resultBox = SearchResultListBox(self, self.mainControl,
                    GUI_ID.htmllbPages)
        else:
            srListBox.Reparent(self)
            self.resultBox = srListBox

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.resultBox, 1, wx.EXPAND)


        buttonSizer = wx.BoxSizer(wx.HORIZONTAL)

        self.btnAsWwSearch = wx.Button(self, GUI_ID.CMD_SEARCH_AS_WWSEARCH,
                label=_(u"As Full Search"))    # TODO Allow hotkey for button
        buttonSizer.Add(self.btnAsWwSearch, 0, wx.EXPAND)

        self.btnAsTab = wx.Button(self, GUI_ID.CMD_SEARCH_AS_TAB,
                label=_(u"As Tab"))    # TODO Allow hotkey for button
        buttonSizer.Add(self.btnAsTab, 0, wx.EXPAND)
        buttonSizer.AddStretchSpacer()


        sizer.Add(buttonSizer, 0, wx.EXPAND)

        self.SetSizer(sizer)

        config = self.mainControl.getConfig()
        width = config.getint("main", "fastSearch_sizeX", 200)
        height = config.getint("main", "fastSearch_sizeY", 400)

        setWindowSize(self, (width, height))
        setWindowPos(self, fullVisible=True)

        # Fixes focus bug under Linux
        self.resultBox.SetFocus()

#         self.Bind(wx.EVT_BUTTON, self.OnCloseMe, button)

        self.resultBox.Bind(wx.EVT_KILL_FOCUS, self.OnKillFocus)
        self.btnAsWwSearch.Bind(wx.EVT_KILL_FOCUS, self.OnKillFocus)
        self.btnAsTab.Bind(wx.EVT_KILL_FOCUS, self.OnKillFocus)
#         wx.EVT_KILL_FOCUS(self.resultBox, self.OnKillFocus)
        wx.EVT_BUTTON(self, GUI_ID.CMD_SEARCH_AS_WWSEARCH, self.OnCmdAsWwSearch)
        wx.EVT_BUTTON(self, GUI_ID.CMD_SEARCH_AS_TAB, self.OnCmdAsTab)
        wx.EVT_CLOSE(self, self.OnClose)
        wx.EVT_KEY_DOWN(self.resultBox, self.OnKeyDown)
#         wx.EVT_LEFT_DOWN(self, self.OnLeftDown)
        self.Bind(wx.EVT_MOVE, self.OnMove)


    def fixate(self):
        if self.fixed:
            return
        
        self.resultBox.Unbind(wx.EVT_KILL_FOCUS)
        self.btnAsWwSearch.Unbind(wx.EVT_KILL_FOCUS)
        self.Unbind(wx.EVT_MOVE)
        self.SetTitle(_(u"Search: %s") % self.sarOp.searchStr)
        self.fixed = True
        

    def OnMove(self, evt):
        if self.firstMove:
            self.firstMove = False
            evt.Skip()
            return

        evt.Skip()
        self.fixate()


    def getResultListPositionTuple(self):
        return getRelativePositionTupleToAncestor(self.resultBox, self)


    def OnCmdAsWwSearch(self, evt):
        self.Hide()
        self.fixate()

        ownPos = self.GetPositionTuple()
        oldRelBoxPos = self.getResultListPositionTuple()

        dlg = SearchWikiDialog(self.GetParent(), -1, srListBox=self.resultBox)
        dlg.showSearchReplaceOperation(self.sarOp)

        newRelBoxPos = dlg.getResultListPositionTuple()

        # A bit math to ensure that result list in both windows is placed
        # at same position (looks more cool)
        otherPos = (ownPos[0] + oldRelBoxPos[0] - newRelBoxPos[0],
                ownPos[1] + oldRelBoxPos[1] - newRelBoxPos[1])

        setWindowPos(dlg, pos=otherPos, fullVisible=True)
        self.mainControl.wwSearchDlgs.append(dlg)
        self.Close()
        dlg.Show()

        # Set focus to dialog (hackish)
        wx.CallLater(100, dlg.SetFocus)


    def OnCmdAsTab(self, evt):
        self.Hide()
        self.fixate()

        maPanel = self.mainControl.getMainAreaPanel()
        presenter = LayeredControlPanel(maPanel)
        subCtl = SearchResultPresenterControl(presenter, self.mainControl,
                self.GetParent(), -1, srListBox=self.resultBox)
        presenter.setSubControl("search result list", subCtl)
        presenter.switchSubControl("search result list")
        maPanel.appendPresenterTab(presenter)
        subCtl.setSearchOp(self.sarOp)

        maPanel.showPresenter(presenter)
        self.Close()
        

        
    def displayErrorMessage(self, errorStr, e=u""):
        """
        Pops up an error dialog box
        """
        wx.MessageBox(uniToGui(u"%s. %s." % (errorStr, e)), u"Error!",
            wx.OK, self)


    def OnKeyDown(self, evt):
        accP = getAccelPairFromKeyDown(evt)

        if accP == (wx.ACCEL_NORMAL, wx.WXK_ESCAPE):
            self.Close()
        else:
            evt.Skip()


    # def OnKillFocus(self, evt):

    # TODO What about Mac?
    if isLinux():
        def OnKillFocus(self, evt):
            evt.Skip()
            if self.resultBox.contextMenuSelection == -2 and \
                    not wx.Window.FindFocus() in \
                    (self.resultBox, self.btnAsWwSearch, self.btnAsTab):
                # Close only if context menu is not open
                # otherwise crashes on GTK
                self.Close()
    else:
        def OnKillFocus(self, evt):
            evt.Skip()
            if not wx.Window.FindFocus() in (self.resultBox, self.btnAsWwSearch,
                    self.btnAsTab):
                self.Close()


    def OnClose(self, evt):
        if not self.fixed:
            width, height = self.GetSizeTuple()
            config = self.mainControl.getConfig()
            config.set("main", "fastSearch_sizeX", str(width))
            config.set("main", "fastSearch_sizeY", str(height))
        
        try:
            self.mainControl.wwSearchDlgs.remove(self)
        except ValueError:
            pass

        evt.Skip()


    def buildSearchReplaceOperation(self, searchText):
        config = self.mainControl.getConfig()
        
        searchType = config.getint("main", "fastSearch_searchType")

        # TODO Make configurable
        sarOp = SearchReplaceOperation()
        sarOp.searchStr = searchText
        sarOp.booleanOp = searchType == Consts.SEARCHTYPE_BOOLEANREGEX
        sarOp.caseSensitive = config.getboolean("main",
                "fastSearch_caseSensitive")
        sarOp.wholeWord = config.getboolean("main", "fastSearch_wholeWord")
        sarOp.cycleToStart = False
        sarOp.wildCard = 'regex' if searchType != Consts.SEARCHTYPE_ASIS else 'no'
        sarOp.wikiWide = True

        return sarOp


    def runSearchOnWiki(self, text):
        self.setSearchOp(self.buildSearchReplaceOperation(text))
        try:
            self._refreshPageList()
        except re.error, e:
            self.displayErrorMessage(_(u'Error in regular expression'),
                    _(unicode(e)))


    def setSearchOp(self, sarOp):
        """
        """
        self.sarOp = sarOp


    def _refreshPageList(self):
        self.resultBox.showSearching()
        self.SetCursor(wx.HOURGLASS_CURSOR)
        self.Freeze()
        try:
            # self.mainControl.saveCurrentDocPage()
    
            if len(self.sarOp.searchStr) > 0:
                self.foundPages = self.mainControl.getWikiDocument().searchWiki(self.sarOp)
                self.mainControl.getCollator().sort(self.foundPages)
                self.resultBox.showFound(self.sarOp, self.foundPages,
                        self.mainControl.getWikiDocument())
            else:
                self.foundPages = []
                self.resultBox.showFound(None, None, None)

            self.listNeedsRefresh = False

        finally:
            self.Thaw()
            self.SetCursor(wx.NullCursor)
            self.resultBox.ensureNotShowSearching()


_CONTEXT_MENU_ACTIVATE = \
u"""
Activate;CMD_ACTIVATE_THIS
Activate New Tab;CMD_ACTIVATE_NEW_TAB_THIS
Activate New Tab Backgrd.;CMD_ACTIVATE_NEW_TAB_BACKGROUND_THIS
"""

# Entries to support i18n of context menus

N_(u"Activate")
N_(u"Activate New Tab")
N_(u"Activate New Tab Backgrd.")
