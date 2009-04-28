import sys

## import hotshot
## _prof = hotshot.Profile("hotshot.prf")

import wx, wx.xrc

import customtreectrl

from wxHelper import GUI_ID, wxKeyFunctionSink, textToDataObject, \
        appendToMenuByMenuDesc, copyTextToClipboard
from MiscEvent import DebugSimple   # , KeyFunctionSink

from WikiExceptions import WikiWordNotFoundException, InternalError
from Utilities import StringPathSet, SingleThreadExecutor

from Configuration import MIDDLE_MOUSE_CONFIG_TO_TABMODE
import PropertyHandling
import DocPages
from SearchAndReplace import SearchReplaceOperation

from StringOps import mbcsEnc, guiToUni, uniToGui, strToBool, \
        pathWordAndAnchorToWikiUrl, escapeForIni, unescapeForIni, \
        htmlColorToRgbTuple

from AdditionalDialogs import SelectWikiWordDialog


class NodeStyle(object):
    """
    A simple structure to hold all necessary information to present a tree node.
    """
    
    __slots__ = ("__weakref__", "label", "bold", "icon", "color", "hasChildren")
    def __init__(self):
        self.label = u""
        
        self.bold = u"False"
        self.icon = u"page"
        self.color = u"null"
        
        self.hasChildren = False
    
    def emptyFields(self):
        self.label = u""
        
        self.bold = u""
        self.icon = u""
        self.color = u"null"



_SETTABLE_PROPS = (u"bold", u"icon", u"color")


# New style class to allow __slots__ for efficiency
class AbstractNode(object):
    """
    Especially for view nodes. An instance of a derived class
    is saved in funcData for such special nodes
    """
    
    __slots__ = ("__weakref__",   # just in case...
            "treeCtrl", "parentNode", "unifiedName")
            
    def __init__(self, tree, parentNode):
        self.treeCtrl = tree
        self.parentNode = parentNode
        # self.unifiedName = None
    
    def setRoot(self, flag = True):
        """
        Sets if this node is a logical root of the tree or not
        (currently the physical root is the one and only logical root)
        """
        pass
        
    def getParentNode(self):
        return self.parentNode

    def getNodePresentation(self):
        """
        return a NodeStyle object for the node
        """
        return NodeStyle()
        
    def representsFamilyWikiWord(self):
        """
        True iff the node type represents a wiki word and is bound into its
        family of parent and children
        """
        return False
        
    def representsWikiWord(self):
        """
        Returns true if node represents a wiki word (not necessarily
        a defined one).
        """
        return False
        
    def listChildren(self):
        """
        Returns a sequence of Nodes for the children of this node.
        This is called before expanding the node
        """
        return ()

    def onActivate(self):
        """
        React on activation
        """
        pass
        
    def prepareContextMenu(self, menu):
        """
        Return a context menu for this item or None
        """
        return None

    def getUnifiedName(self):
        """
        Return unistring describing this node. It is used to build a "path"
        in tree to identify a particular node (esp. to store if node is
        expanded or not).
        """
        return self.unifiedName
        
    def getNodePath(self):
        """
        Return a "path" (=list of node descriptors) to identify a particular
        node in tree.
        
        A single node descriptor isn't enough as a node for the same wiki word
        has the same descriptor and can appear in multiple places in tree.
        """
        if self.parentNode is None:
            return [self.getUnifiedName()]

        result = self.parentNode.getNodePath()
        result.append(self.getUnifiedName())
        return result

    def nodeEquality(self, other):
        """
        Test for node equality
        """
        return self.__class__ == other.__class__ 



class WikiWordNode(AbstractNode):
    """
    Represents a wiki word
    """
    __slots__ = ("wikiWord", "flagChildren", "flagRoot", "ancestors")
    
    def __init__(self, tree, parentNode, wikiWord):
        AbstractNode.__init__(self, tree, parentNode)
        self.wikiWord = wikiWord
        self.flagChildren = None
        self.unifiedName = u"wikipage/" + self.wikiWord

        self.flagRoot = False
        self.ancestors = None

    def getNodePresentation(self):
        return self._createNodePresentation(self.wikiWord)

    def setRoot(self, flag = True):
        self.flagRoot = flag

    def getAncestors(self):  # TODO Check for cache clearing conditions
        """
        Returns a set with the ancestor words (parent, grandparent, ...).
        """
        if self.ancestors is None:
            parent = self.getParentNode()
            if parent is not None:
                result = parent.getAncestors().copy()
                result.add(parent.getWikiWord())
            else:
                result = set()

            self.ancestors = result

        return self.ancestors            
       

    def _getValidChildren(self, wikiPage, withFields=()):
        """
        Get all valid children, filter out undefined and/or cycles
        if options are set accordingly
        """
        config = self.treeCtrl.pWiki.getConfig()

        if config.getboolean("main", "tree_no_cycles"):
            # Filter out cycles
            ancestors = self.getAncestors()
        else:
            ancestors = frozenset()  # Empty

        relations = wikiPage.getChildRelationships(
                existingonly=self.treeCtrl.getHideUndefined(),
                selfreference=False, withFields=withFields,
                excludeSet=ancestors)

        return relations


    def _hasValidChildren(self, wikiPage):  # TODO More efficient
        """
        Check if represented word has valid children, filter out undefined
        and/or cycles if options are set accordingly
        """
        if self.treeCtrl.pWiki.getConfig().getboolean("main", "tree_no_cycles"):
            # Filter out cycles
            ancestors = self.getAncestors()
        else:
            ancestors = frozenset()  # Empty

        relations = wikiPage.getChildRelationships(
                existingonly=self.treeCtrl.getHideUndefined(),
                selfreference=False, withFields=())

        if len(relations) > len(ancestors):
            return True
            
        for r in relations:
            if r not in ancestors:
                return True
                
        return False


    def _createNodePresentation(self, baselabel):
        """
        Splitted to support derived class WikiWordSearchNode
        """
        wikiDataManager = self.treeCtrl.pWiki.getWikiDataManager()
        wikiData = wikiDataManager.getWikiData()
        wikiPage = wikiDataManager.getWikiPageNoError(self.wikiWord)

        style = NodeStyle()
        
        style.label = baselabel

        # Has children?
        if self.flagRoot:
            self.flagChildren = True # Has at least Views
        else:
            self.flagChildren = self._hasValidChildren(wikiPage)

        style.hasChildren = self.flagChildren
        
        # apply custom properties to nodes
        wikiPage = wikiPage.getNonAliasPage() # Ensure we don't have an alias

        # if this is the scratch pad set the icon and return
        if (self.wikiWord == "ScratchPad"):
            style.icon = "note"
            return style # ?


        # fetch the global properties
        globalProps = self.treeCtrl.pWiki.getWikiData().getGlobalProperties() # TODO More elegant
        # get the wikiPage properties
        props = wikiPage.getProperties()

        # priority
        priority = props.get("priority", (None,))[-1]

        # priority is special. it can create an "importance" and it changes
        # the text of the node            
        if priority:
            style.label += u" (%s)" % priority
            # set default importance based on priority
            if not props.has_key(u'importance'):
                try:
                    priorNum = int(priority)    # TODO Error check
                    if (priorNum < 3):
                        props[u'importance'] = [u'high']
                    elif (priorNum > 3):
                        props[u'importance'] = [u'low']
                except ValueError:
                    pass

        propsItems = props.items()

        # apply the global props based on the props of this node
        for p in _SETTABLE_PROPS:
            # Check per page props first
            if props.has_key(p):
                setattr(style, p, props[p][-1])
                continue

            # Check props on page against global presentation props.
            # The dots in the key matter. The more dots the more specific
            # is the global prop and wins over less specific props
            gPropVal = None
            dots = -1
            for (key, values) in propsItems:
                newGPropVal = None
                newDots = key.count(u".") + 1 # key dots plus one for value
                if newDots > dots:
                    for val in values:
                        newGPropVal = globalProps.get(u"global.%s.%s.%s" % (key, val, p))
                        if newGPropVal:
                            gPropVal = newGPropVal
                            dots = newDots
                            break

                    newDots -= 1
                    while newDots > dots:
                        newGPropVal = globalProps.get(u"global.%s.%s" % (key, p))
                        if newGPropVal:
                            break
    
                        dotpos = key.rfind(u".")
                        if dotpos == -1:
                            break
                        key = key[:dotpos]
                        newDots -= 1
    
                    if newGPropVal:
                        gPropVal = newGPropVal
                        dots = newDots

            # If a value is found, we stop searching for this presentation
            # property here
            if gPropVal:
                setattr(style, p, gPropVal)
                continue

        return style


    def representsFamilyWikiWord(self):
        """
        True iff the node type is bound into its family of parent and children
        """
        return True


    def representsWikiWord(self):
        return True


    def listChildren(self):
##         _prof.start()
        wikiDocument = self.treeCtrl.pWiki.getWikiDocument()
        wikiPage = wikiDocument.getWikiPageNoError(self.wikiWord)

        if self.treeCtrl.pWiki.getConfig().getboolean("main", "tree_no_cycles"):
            # Filter out cycles
            ancestors = self.getAncestors()
        else:
            ancestors = frozenset()  # Empty

        if self.treeCtrl.pWiki.getConfig().getboolean(
                "main", "tree_force_scratchpad_visibility", False) and \
                self.flagRoot:
            includeSet = frozenset((u"ScratchPad",))
        else:
            includeSet = frozenset()

        children = wikiPage.getChildRelationshipsTreeOrder(
                existingonly=self.treeCtrl.getHideUndefined(),
                excludeSet=ancestors, includeSet=includeSet)

        result = [WikiWordNode(self.treeCtrl, self, c)
                for c in children]

        if self.flagRoot:
            result.append(MainViewNode(self.treeCtrl, self))

##         _prof.stop()

        return result


    def onActivate(self):
#         tracer.runctx('self.treeCtrl.pWiki.openWikiPage(self.wikiWord)', globals(), locals())
        self.treeCtrl.pWiki.openWikiPage(self.wikiWord)

    def getWikiWord(self):
        return self.wikiWord

    def prepareContextMenu(self, menu):
        # Take context menu from tree   # TODO Better solution esp. for event handling
        return self.treeCtrl.contextMenuWikiWords

    def nodeEquality(self, other):
        """
        Test for node equality
        """
        return AbstractNode.nodeEquality(self, other) and \
                self.wikiWord == other.wikiWord


class WikiWordRelabelNode(WikiWordNode):
    """
    Derived from WikiWordNode with ability to set label differently from
    wikiWord
    """
    __slots__ = ("newLabel",)    
    
    def __init__(self, tree, parentNode, wikiWord, newLabel = None):
        WikiWordNode.__init__(self, tree, parentNode, wikiWord)

        self.newLabel = newLabel

    def getAncestors(self):
        """
        Returns a set with the ancestor words (parent, grandparent, ...).
        """
        return set()

    def getNodePresentation(self):
        if self.newLabel:
            return WikiWordNode._createNodePresentation(self, self.newLabel)
        else:
            return WikiWordNode.getNodePresentation(self)

    def _getValidChildren(self, wikiPage, withFields=False):
        """
        Get all valid children, filter out undefined and/or cycles
        if options are set accordingly. A WikiWordSearchNode has no children.
        """        
        return []

    def _hasValidChildren(self, wikiPage):  # TODO More efficient
        """
        Check if represented word has valid children, filter out undefined
        and/or cycles if options are set accordingly. A WikiWordSearchNode
        has no children.
        """
        return False

    def representsFamilyWikiWord(self):
        """
        A search node is alone as child of a view subnode without
        its children or real parent
        """
        return False

    def nodeEquality(self, other):
        """
        Test for node equality
        """
        return WikiWordNode.nodeEquality(self, other) and \
                self.newLabel == other.newLabel



class WikiWordSearchNode(WikiWordRelabelNode):
    """
    Derived from WikiWordRelabelNode with ability to set label different from
    wikiWord and to set search information
    """
    __slots__ = ("searchOp",)    
    
    def __init__(self, tree, parentNode, wikiWord, newLabel = None,
            searchOp = None):
        WikiWordRelabelNode.__init__(self, tree, parentNode, wikiWord, newLabel)

        self.searchOp = searchOp

    def onActivate(self):
        # WikiWordNode.onActivate(self)
        WikiWordRelabelNode.onActivate(self)
        if self.searchOp:
            self.treeCtrl.pWiki.getActiveEditor().executeSearch(self.searchOp, 0)   # TODO



class MainViewNode(AbstractNode):
    """
    Represents the "Views" node
    """
    __slots__ = ()


    def __init__(self, tree, parentNode):
        AbstractNode.__init__(self, tree, parentNode)
        self.unifiedName = u"helpernode/main/view"

    def getNodePresentation(self):
        style = NodeStyle()
        style.label = _(u"Views")
        style.icon = u"orgchart"
        style.hasChildren = True
        return style
        
    def listChildren(self):
##         _prof.start()
        wikiData = self.treeCtrl.pWiki.getWikiData()
        result = []

        # add to do list nodes
        result += TodoNode(self.treeCtrl, self, ()).listChildren()
        # add property names   
        result += PropCategoryNode(self.treeCtrl, self, ()).listChildren()
        # add "searches" view
        node = MainSearchesNode(self.treeCtrl, self)
        if node.isVisible():
            result.append(node)
        # add "last modified" view
        result.append(MainModifiedWithinNode(self.treeCtrl, self))
        # add "parentless" view
        node = MainParentlessNode(self.treeCtrl, self)
        if node.isVisible():
            result.append(node)
        # add "undefined" view
        node = MainUndefinedNode(self.treeCtrl, self)
        if node.isVisible():
            result.append(node)

        result.append(MainFuncPagesNode(self.treeCtrl, self))
##         _prof.stop()
            
        return result



class TodoNode(AbstractNode):
    """
    Represents a todo node or subnode
    """
    
    __slots__ = ("categories", "isRightSide")
            
    def __init__(self, tree, parentNode, cats):  # , isRightSide=False):
        """
        cats -- Sequence of category (todo, action, done, ...) and
                subcategories, may also include the todo-value (=right side)
        isRightSide -- If true, the last element of cats is the
                "right side" of todo (e.g.: todo.work: This is the right side)
        """
        AbstractNode.__init__(self, tree, parentNode)
        self.categories = cats
        self.unifiedName = u"todo/" + u".".join(self.categories)


    def getNodePresentation(self):
        style = NodeStyle()
        style.emptyFields()

        style.hasChildren = True
        
        wikiDocument = self.treeCtrl.pWiki.getWikiDocument()
        langHelper = wx.GetApp().createWikiLanguageHelper(
                wikiDocument.getWikiDefaultWikiLanguage())
        
        nodes = langHelper.parseTodoValue(self.categories[-1], wikiDocument)
        if nodes is not None:
            for propNode in nodes.iterDeepByName("property"):
                for key, value in propNode.props:
                    if key in _SETTABLE_PROPS:
                        setattr(style, key, value)

        if style.label == u"":
            style.label = self.categories[-1]
        if style.icon == u"":
            style.icon = "pin"

        return style


    def listChildren(self):
        """
        Returns a sequence of Nodes for the children of this node.
        This is called before expanding the node
        """
        wikiData = self.treeCtrl.pWiki.getWikiData()
        addedTodoSubCategories = []
        addedWords = []
        for (wikiWord, todo) in wikiData.getTodos():
            # parse the todo for name and value
            wikiDocument = self.treeCtrl.pWiki.getWikiDocument()
            langHelper = wx.GetApp().createWikiLanguageHelper(
                    wikiDocument.getWikiDefaultWikiLanguage())

            node = langHelper.parseTodoEntry(todo, wikiDocument)
            if node is not None:
                entryCats = tuple(node.keyComponents +
                        [node.valueNode.getString()])

                if len(entryCats) < len(self.categories):
                    # Can't match
                    continue
                elif (len(entryCats) == len(self.categories)) and \
                        (entryCats == self.categories):
                    # Same category sequence -> wiki word node
                    addedWords.append((wikiWord, todo))
                elif len(entryCats) > len(self.categories) and \
                        entryCats[:len(self.categories)] == self.categories:
                    # Subcategories -> category node
    
                    nextSubCategory = entryCats[len(self.categories)]
    
                    if nextSubCategory not in addedTodoSubCategories:
                        addedTodoSubCategories.append(nextSubCategory)

        collator = self.treeCtrl.pWiki.getCollator()
        
        def cmpAddWords(left, right):
            result = collator.strcoll(left[0], right[0])
            if result != 0:
                return result
            
            return collator.strcoll(left[1], right[1])

        collator.sort(addedTodoSubCategories)

#         collator.sort(addedWords)
        addedWords.sort(cmpAddWords)

        result = []
        # First list real categories, then right sides, then words
        result += [TodoNode(self.treeCtrl, self, self.categories + (c,))
                for c in addedTodoSubCategories]

#         result += [TodoNode(self.treeCtrl, self, self.categories + (c,),
#                 isRightSide=True) for c in addedRightSides]

        def createSearchNode(wt):
            searchOp = SearchReplaceOperation()
            searchOp.wildCard = "no"
            searchOp.searchStr = wt[1]
            return WikiWordSearchNode(self.treeCtrl, self, wt[0], searchOp=searchOp)

        result += [createSearchNode(wt) for wt in addedWords]

        return result

    def nodeEquality(self, other):
        """
        Test for node equality
        """
        return AbstractNode.nodeEquality(self, other) and \
                self.categories == other.categories


class PropCategoryNode(AbstractNode):
    """
    Node representing a property category or subcategory
    """
    
    __slots__ = ("categories", "propIcon")
            
    def __init__(self, tree, parentNode, cats, propertyIcon=u"page"):
        AbstractNode.__init__(self, tree, parentNode)
        self.categories = cats
        self.propIcon = propertyIcon
        self.unifiedName = u"helpernode/propcategory/" + \
                u".".join(self.categories)

    def getNodePresentation(self):   # TODO Retrieve prop icon here
        style = NodeStyle()
        globalProps = self.treeCtrl.pWiki.getWikiData().getGlobalProperties()
        key = u".".join(self.categories)
        propertyIcon = globalProps.get(u"global.%s.icon" % (key), u"page")

        style.icon = propertyIcon   # u"page"  # self.propIcon
        style.label = self.categories[-1]
        style.hasChildren = True
        return style

    def listChildren(self):
        wikiData = self.treeCtrl.pWiki.getWikiData()
        result = []
        key = u".".join(self.categories + (u"",))
        
        # Start with subcategories
        addedSubCategories = set()
        for name in wikiData.getPropertyNamesStartingWith(key):
            # Cut off uninteresting
            name = name[len(key):]

            nextcat = name.split(u".", 1)[0]
            addedSubCategories.add(nextcat)
            
        subCats = list(addedSubCategories)
        self.treeCtrl.pWiki.getCollator().sort(subCats)
        result += map(lambda c: PropCategoryNode(self.treeCtrl, self,
                self.categories + (c,)), subCats)
                
        # Now the values:
        vals = wikiData.getDistinctPropertyValues(u".".join(self.categories))
        self.treeCtrl.pWiki.getCollator().sort(vals)
        result += map(lambda v: PropValueNode(self.treeCtrl, self,
                self.categories, v), vals)
                
        # Replace a single "true" value node by its children
        if len(result) == 1 and isinstance(result[0], PropValueNode) and \
                result[0].getValue().lower() == u"true":
            result = result[0].listChildren()

        return result
        

    def nodeEquality(self, other):
        """
        Test for node equality
        """
        return AbstractNode.nodeEquality(self, other) and \
                self.categories == other.categories


class PropValueNode(AbstractNode):
    """
    Node representing a property value. Children are WikiWordSearchNode's
    """
    
    __slots__ = ("categories", "value", "propIcon")
            
    def __init__(self, tree, parentNode, cats, value, propertyIcon=u"page"):
        AbstractNode.__init__(self, tree, parentNode)
        self.categories = cats
        self.value = value
        self.propIcon = propertyIcon
        self.unifiedName = u"helpernode/propvalue/" + \
                u".".join(self.categories) + u"/" + self.value

    def getValue(self):
        return self.value

    def getNodePresentation(self):
        style = NodeStyle()
        style.icon = u"page"
        style.label = self.value
        style.hasChildren = True
        return style

    def listChildren(self):
        wikiDocument = self.treeCtrl.pWiki.getWikiDocument()
        result = []
        key = u".".join(self.categories)
#         words = wikiData.getWordsWithPropertyValue(key, self.value)
        words = list(set(w for w,k,v in wikiDocument.getPropertyTriples(
                None, key, self.value)))
        self.treeCtrl.pWiki.getCollator().sort(words)                
        return [WikiWordPropertySearchNode(self.treeCtrl, self, w,
                key, self.value) for w in words]


    def nodeEquality(self, other):
        """
        Test for node equality
        """
        return AbstractNode.nodeEquality(self, other) and \
                self.categories == other.categories and \
                self.value == other.value


class WikiWordPropertySearchNode(WikiWordRelabelNode):
    """
    Derived from WikiWordRelabelNode, specialized to locate and select
    in the active editor a particular property with given propName and
    propValue.
    """
    __slots__ = ("propName", "propValue")    
    
    def __init__(self, tree, parentNode, wikiWord, propName, propValue):
        super(WikiWordPropertySearchNode, self).__init__(tree, parentNode,
                wikiWord)

        self.propName = propName
        self.propValue = propValue


    def onActivate(self):
        super(WikiWordPropertySearchNode, self).onActivate()

        editor = self.treeCtrl.pWiki.getActiveEditor()
        pageAst = editor.getPageAst()
        if pageAst is None:
            return
            
        wikiDataManager = self.treeCtrl.pWiki.getWikiDataManager()
        wikiPage = wikiDataManager.getWikiPageNoError(self.wikiWord)
            
        propNodes = wikiPage.extractPropertyNodesFromPageAst(pageAst)
        for node in propNodes:
            if (self.propName, self.propValue) in node.props:
                editor.SetSelectionByCharPos(node.pos, node.pos + node.strLength)
                break



class MainSearchesNode(AbstractNode):
    """
    Represents the "searches" node
    """
    __slots__ = ()
    
    def __init__(self, tree, parentNode):
        AbstractNode.__init__(self, tree, parentNode)
        self.unifiedName = u"helpernode/main/searches"

    def getNodePresentation(self):
        style = NodeStyle()
        style.label = _(u"searches")
        style.icon = u"lens"
        style.hasChildren = True
        return style
        
    def isVisible(self):
#         return bool(self.treeCtrl.pWiki.getWikiData().getSavedSearchTitles())
        return bool(self.treeCtrl.pWiki.getWikiData()\
                .getDataBlockUnifNamesStartingWith(u"savedsearch/"))

    def listChildren(self):
        wikiData = self.treeCtrl.pWiki.getWikiData()

        unifNames = wikiData.getDataBlockUnifNamesStartingWith(
                u"savedsearch/")

#         return map(lambda s: SearchNode(self.treeCtrl, self, s), searchTitles)
        return [SearchNode(self.treeCtrl, self, name[12:]) for name in unifNames]



    
class SearchNode(AbstractNode):
    """
    Represents a search below the "searches" node
    """
    
    __slots__ = ("searchTitle",)
            
    def __init__(self, tree, parentNode, searchTitle):
        AbstractNode.__init__(self, tree, parentNode)
        self.searchTitle = searchTitle
        self.unifiedName = u"savedsearch/" + self.searchTitle

    def getNodePresentation(self):
        style = NodeStyle()
        style.icon = u"lens"
        style.label = unicode(self.searchTitle)
        style.hasChildren = True
        return style

    def listChildren(self):
        pWiki = self.treeCtrl.pWiki
#         datablock = pWiki.getWikiData().getSearchDatablock(self.searchTitle)
        datablock = pWiki.getWikiData().retrieveDataBlock(
                u"savedsearch/" + self.searchTitle)

        searchOp = SearchReplaceOperation()
        searchOp.setPackedSettings(datablock)
        searchOp.setTitle(self.searchTitle)
        searchOp.replaceOp = False
        words = pWiki.getWikiDocument().searchWiki(searchOp)
        self.treeCtrl.pWiki.getCollator().sort(words)

        return [WikiWordSearchNode(self.treeCtrl, self, w, searchOp=searchOp)
                for w in words]

#         return map(lambda w: WikiWordSearchNode(self.treeCtrl,
#                 wikiData.getPage(w, toload=[""]), searchOp=searchOp),   # TODO
#                 words)

    def nodeEquality(self, other):
        """
        Test for node equality
        """
        return AbstractNode.nodeEquality(self, other) and \
                self.searchTitle == other.searchTitle



class MainModifiedWithinNode(AbstractNode):
    """
    Represents the "modified-within" node
    """
    __slots__ = ()

    def __init__(self, tree, parentNode):
        AbstractNode.__init__(self, tree, parentNode)
        self.unifiedName = u"helpernode/main/modifiedwithin"
    
    def getNodePresentation(self):
        style = NodeStyle()
        style.label = _(u"modified-within")
        style.icon = u"date"
        style.hasChildren = True
        return style
        
    def listChildren(self):
        return map(lambda d: ModifiedWithinNode(self.treeCtrl, self, d),
                [1, 3, 7, 30])



class ModifiedWithinNode(AbstractNode):
    """
    Represents a time span below the "modified-within" node
    """
    
    __slots__ = ("daySpan",)
            
    def __init__(self, tree, parentNode, daySpan):
        AbstractNode.__init__(self, tree, parentNode)
        self.daySpan = daySpan
        self.unifiedName = u"helpernode/modifiedwithin/days/" + \
                unicode(self.daySpan)

    def getNodePresentation(self):
        style = NodeStyle()
        style.icon = u"date"
        if self.daySpan == 1:
            style.label = _(u"1 day")
        else:
            style.label = _(u"%i days") % self.daySpan
        style.hasChildren = True   #?
        return style

    def listChildren(self):
#         wikiData = self.treeCtrl.pWiki.getWikiData()
#         words = wikiData.getWikiWordsModifiedLastDays(self.daySpan)
        wikiDocument = self.treeCtrl.pWiki.getWikiDocument()
        words = wikiDocument.getWikiWordsModifiedLastDays(self.daySpan)
        self.treeCtrl.pWiki.getCollator().sort(words)

        return [WikiWordSearchNode(self.treeCtrl, self, w) for w in words]

#         return map(lambda w: WikiWordSearchNode(self.treeCtrl,
#                 wikiData.getPage(w, toload=[""])),
#                 words)

    def nodeEquality(self, other):
        """
        Test for node equality
        """
        return AbstractNode.nodeEquality(self, other) and \
                self.daySpan == other.daySpan



class MainParentlessNode(AbstractNode):
    """
    Represents the "parentless" node
    """
    __slots__ = ()
    
    def __init__(self, tree, parentNode):
        AbstractNode.__init__(self, tree, parentNode)
        self.unifiedName = u"helpernode/main/parentless"

    def getNodePresentation(self):
        style = NodeStyle()
        style.label = u"parentless-nodes"
        style.icon = u"link"
        style.hasChildren = True
        return style

    def isVisible(self):
        wikiData = self.treeCtrl.pWiki.getWikiData()
        return len(wikiData.getParentlessWikiWords()) > 0  # TODO Test if root is single element

    def listChildren(self):
        wikiData = self.treeCtrl.pWiki.getWikiData()
        words = wikiData.getParentlessWikiWords()
        self.treeCtrl.pWiki.getCollator().sort(words)
        
        return [WikiWordSearchNode(self.treeCtrl, self, w) for w in words
                if w != self.treeCtrl.pWiki.wikiName]



class MainUndefinedNode(AbstractNode):
    """
    Represents the "undefined" node
    """
    __slots__ = ()
    
    def __init__(self, tree, parentNode):
        AbstractNode.__init__(self, tree, parentNode)
        self.unifiedName = u"helpernode/main/undefined"

    def getNodePresentation(self):
        style = NodeStyle()
        style.label = _(u"undefined-nodes")
        style.icon = u"question"
        style.hasChildren = True
        return style

    def isVisible(self):
        wikiData = self.treeCtrl.pWiki.getWikiData()
        return len(wikiData.getUndefinedWords()) > 0

    def listChildren(self):
        wikiData = self.treeCtrl.pWiki.getWikiData()
        words = wikiData.getUndefinedWords()
        self.treeCtrl.pWiki.getCollator().sort(words)

        return [WikiWordSearchNode(self.treeCtrl, self, w) for w in words
                if w != self.treeCtrl.pWiki.wikiName]


class MainFuncPagesNode(AbstractNode):
    """
    Represents the "Func pages" node
    """
    __slots__ = ()

    def __init__(self, tree, parentNode):
        AbstractNode.__init__(self, tree, parentNode)
        self.unifiedName = u"helpernode/main/funcpages"

    def getNodePresentation(self):
        style = NodeStyle()
        style.label = _(u"Func. pages")
        style.icon = u"cog"
        style.hasChildren = True
        return style
        
    def listChildren(self):
        return [
                FuncPageNode(self.treeCtrl, self, u"global/TextBlocks"),
                FuncPageNode(self.treeCtrl, self, u"wiki/TextBlocks"),
                FuncPageNode(self.treeCtrl, self, u"global/PWL"),
                FuncPageNode(self.treeCtrl, self, u"wiki/PWL"),
                FuncPageNode(self.treeCtrl, self, u"global/CCBlacklist"),
                FuncPageNode(self.treeCtrl, self, u"wiki/CCBlacklist"),
                FuncPageNode(self.treeCtrl, self, u"global/FavoriteWikis")
                ]


class FuncPageNode(AbstractNode):
    """
    Node representing a functional page
    """
    
    __slots__ = ("funcTag", "label")
    
    def __init__(self, tree, parentNode, funcTag):
        AbstractNode.__init__(self, tree, parentNode)
        self.funcTag = funcTag
        self.label = DocPages.getHrNameForFuncTag(self.funcTag)
        self.unifiedName = u"funcpage/" + self.funcTag

    def getNodePresentation(self):
        """
        return a NodeStyle object for the node
        """
        style = NodeStyle()
        style.label = self.label
        style.icon = u"cog"
        style.hasChildren = False

        return style

    def onActivate(self):
        """
        React on activation
        """
        self.treeCtrl.pWiki.openFuncPage(self.funcTag)

#     def getContextMenu(self):
#         """
#         Return a context menu for this item or None
#         """
#         return None
        
    def nodeEquality(self, other):
        """
        Test for node equality
        """
        return AbstractNode.nodeEquality(self, other) and \
                self.funcTag == other.funcTag




# ----------------------------------------------------------------------


class WikiTreeCtrl(customtreectrl.CustomTreeCtrl):          # wxTreeCtrl):
    def __init__(self, pWiki, parent, ID, treeType):        
        # wxTreeCtrl.__init__(self, parent, ID, style=wxTR_HAS_BUTTONS)
        customtreectrl.CustomTreeCtrl.__init__(self, parent, ID,
                style=wx.TR_HAS_BUTTONS |
                customtreectrl.TR_HAS_VARIABLE_ROW_HEIGHT)

        self.pWiki = pWiki

        # Bytestring "main" for main tree or "views" for views tree
        # The setting affects the configuration entries used to set up tree
        self.treeType = treeType

#         self.SetBackgroundColour(wx.WHITE)

        self.SetSpacing(0)
        self.refreshGenerator = None  # Generator called in OnIdle
        self.refreshExecutor = SingleThreadExecutor(1)
#        self.refreshCheckChildren = [] # List of nodes to check for new/deleted children
        self.sizeVisible = True
        # Descriptor pathes of all expanded nodes to remember or None
        # if functionality was switched off by user
        self.expandedNodePathes = StringPathSet()
        
        self.onOptionsChanged(None)


        # EVT_TREE_ITEM_ACTIVATED(self, ID, self.OnTreeItemActivated)
        # EVT_TREE_SEL_CHANGED(self, ID, self.OnTreeItemActivated)
        wx.EVT_RIGHT_DOWN(self, self.OnRightButtonDown)
        wx.EVT_RIGHT_UP(self, self.OnRightButtonUp)
        wx.EVT_MIDDLE_DOWN(self, self.OnMiddleButtonDown)
        wx.EVT_SIZE(self, self.OnSize)

        self._bindActivation()

        wx.EVT_TREE_BEGIN_RDRAG(self, ID, self.OnTreeBeginRDrag)
        wx.EVT_TREE_ITEM_EXPANDING(self, ID, self.OnTreeItemExpand)
        wx.EVT_TREE_ITEM_COLLAPSED(self, ID, self.OnTreeItemCollapse)
        wx.EVT_TREE_BEGIN_DRAG(self, ID, self.OnTreeBeginDrag)

#        EVT_LEFT_DOWN(self, self.OnLeftDown)

        res = wx.xrc.XmlResource.Get()
        self.contextMenuWikiWords = res.LoadMenu("MenuTreectrlWikiWords")

        self.contextMenuWikiWords.AppendSeparator()

#         # Build icon menu (low resource version)
#         # Add only menu item for icon select dialog
#         menuID = wx.NewId()
#         self.contextMenuWikiWords.Append(menuID, _(u'Add icon attribute'),
#                 _(u'Open icon select dialog'))
#         wx.EVT_MENU(self, menuID, lambda evt: self.pWiki.showSelectIconDialog())

        # Build icon menu
        # Build full submenu for icons
        iconsMenu, self.cmdIdToIconName = \
                PropertyHandling.buildIconsSubmenu(wx.GetApp().getIconCache())
        for cmi in self.cmdIdToIconName.keys():
            wx.EVT_MENU(self, cmi, self.OnInsertIconAttribute)

        self.contextMenuWikiWords.AppendMenu(wx.NewId(),
                _(u'Add icon attribute'), iconsMenu)

        # Build submenu for colors
        colorsMenu, self.cmdIdToColorName = PropertyHandling.buildColorsSubmenu()
        for cmi in self.cmdIdToColorName.keys():
            wx.EVT_MENU(self, cmi, self.OnInsertColorAttribute)

        self.contextMenuWikiWords.AppendMenu(wx.NewId(), _(u'Add color attribute'),
                colorsMenu)

        self.contextMenuNode = None  # Tree node for which a context menu was shown
        self.selectedNodeWhileContext = None # Tree node which was selected
                # before context menu was shown (when context menu is closed
                # selection jumps normally back to this node

        # TODO Let PersonalWikiFrame handle this 
        wx.EVT_MENU(self, GUI_ID.CMD_RENAME_THIS_WIKIWORD,
                lambda evt: self.pWiki.showWikiWordRenameDialog(
                    self.GetPyData(self.contextMenuNode).getWikiWord()))
        wx.EVT_MENU(self, GUI_ID.CMD_DELETE_THIS_WIKIWORD,
                lambda evt: self.pWiki.showWikiWordDeleteDialog(
                    self.GetPyData(self.contextMenuNode).getWikiWord()))
        wx.EVT_MENU(self, GUI_ID.CMD_BOOKMARK_THIS_WIKIWORD,
                lambda evt: self.pWiki.insertAttribute("bookmarked", "true",
                    self.GetPyData(self.contextMenuNode).getWikiWord()))
        wx.EVT_MENU(self, GUI_ID.CMD_SETASROOT_THIS_WIKIWORD,
                lambda evt: self.pWiki.setWikiWordAsRoot(
                    self.GetPyData(self.contextMenuNode).getWikiWord()))

        wx.EVT_MENU(self, GUI_ID.CMD_COLLAPSE_TREE,
                lambda evt: self.collapseAll())

        wx.EVT_MENU(self, GUI_ID.CMD_APPEND_WIKIWORD_FOR_THIS,
                self.OnAppendWikiWord)
        wx.EVT_MENU(self, GUI_ID.CMD_PREPEND_WIKIWORD_FOR_THIS,
                self.OnPrependWikiWord)
        wx.EVT_MENU(self, GUI_ID.CMD_ACTIVATE_NEW_TAB_THIS,
                self.OnActivateNewTabThis)
        wx.EVT_MENU(self, GUI_ID.CMD_CLIPBOARD_COPY_URL_TO_THIS_WIKIWORD,
                self.OnCmdClipboardCopyUrlToThisWikiWord)
                


        # Register for pWiki events
        self.__sinkMc = wxKeyFunctionSink((
                ("loading wiki page", self.onLoadingCurrentWikiPage),
                ("closing current wiki", self.onClosingCurrentWiki),
                ("closed current wiki", self.onClosedCurrentWiki),
                ("changed current presenter",
                    self.onChangedPresenter)
        ), self.pWiki.getMiscEvent(), None)

        self.__sinkDocPagePresenter = wxKeyFunctionSink((
                ("loading wiki page", self.onLoadingCurrentWikiPage),
        ), self.pWiki.getCurrentPresenterProxyEvent(), self)

        self.__sinkWikiDoc = wxKeyFunctionSink((
                ("renamed wiki page", self.onRenamedWikiPage),
                ("deleted wiki page", self.onDeletedWikiPage),
                ("updated wiki page", self.onWikiPageUpdated),
                ("changed wiki configuration", self.onChangedWikiConfiguration)
        ), self.pWiki.getCurrentWikiDocumentProxyEvent(), self)

        self.__sinkApp = wxKeyFunctionSink((
                ("options changed", self.onOptionsChanged),
        ), wx.GetApp().getMiscEvent(), self)
        

        self.refreshExecutor.start()


    def _bindActivation(self):
        self.Bind(wx.EVT_TREE_SEL_CHANGED, self.OnTreeItemActivated)
        self.Bind(wx.EVT_TREE_SEL_CHANGING, self.OnTreeItemSelChanging)

    def _unbindActivation(self):
        self.Unbind(wx.EVT_TREE_SEL_CHANGING)
        self.Unbind(wx.EVT_TREE_SEL_CHANGED)
        
    def close(self):
        self.__sinkMc.disconnect()
        self.__sinkDocPagePresenter.disconnect()
        self.__sinkWikiDoc.disconnect()
        self.__sinkApp.disconnect()
        self.refreshExecutor.end(hardEnd=True)


    def collapse(self):
        """
        Called before rebuilding tree
        """
        rootNode = self.GetRootItem()
        self.CollapseAndReset(rootNode)

    def collapseAll(self):
#         selId = self.GetSelection()
        # notCollapse = set()
        self.UnselectAll()
        rootNode = self.GetRootItem()
        rootOb = self.GetPyData(rootNode)
        if self.expandedNodePathes is not None:
            self.expandedNodePathes = StringPathSet()

        if not self.IsExpanded(rootNode):
            return

        self.Freeze()
        try:
            nodeId, cookie = self.GetFirstChild(rootNode)
            while nodeId is not None and nodeId.IsOk():
                if self.IsExpanded(nodeId):
                    self.CollapseAndReset(nodeId)

                nodeId, cookie = self.GetNextChild(rootNode, cookie)
#             if selId is not None and selId.IsOk():
#                 print "--collapseAll21", repr((self.selectedNodeWhileContext, selId))
#                 self.selectedNodeWhileContext = selId
#                 self._sendSelectionEvents(None, selId)
        finally:
            self.Thaw()


#         if selId is not None and selId.IsOk():
#             self.SelectItem(selId)
#         
#         print "--collapseAll30", repr((selId, self.GetSelection()))




    def expandRoot(self):
        """
        Called after rebuilding tree
        """
        rootNode = self.GetRootItem()
        self.Expand(rootNode)
        self.selectedNodeWhileContext = rootNode
        self._sendSelectionEvents(None, rootNode)

    def getHideUndefined(self):
        return self.pWiki.getConfig().getboolean("main", "hideundefined")

    def onLoadingCurrentWikiPage(self, miscevt):
#         if miscevt.get("forceTreeSyncFromRoot", False):
#             self.buildTreeForWord(self.pWiki.getCurrentWikiWord(),
#                     selectNode=True)
#         else:
        currentNode = self.GetSelection()
        currentWikiWord = self.pWiki.getCurrentWikiWord()
        if currentNode is not None and currentNode.IsOk():
            node = self.GetPyData(currentNode)
            if node.representsWikiWord():                    
                if self.pWiki.getWikiDocument()\
                        .getUnAliasedWikiWordOrAsIs(node.getWikiWord()) ==\
                        currentWikiWord and currentWikiWord is not None:
                    return  # Is already on word -> nothing to do
                if currentWikiWord is None:
                    self.Unselect()
                    return
            if node.representsFamilyWikiWord():
                # If we know the motionType, tree selection can be moved smart
                motionType = miscevt.get("motionType", "random")
                if motionType == "parent":
                    parentnodeid = self.GetItemParent(currentNode)
                    if parentnodeid is not None and parentnodeid.IsOk():
                        parentnode = self.GetPyData(parentnodeid)
                        if parentnode.representsWikiWord() and \
                                (parentnode.getWikiWord() == \
                                self.pWiki.getCurrentWikiWord()):
                            self._unbindActivation()
                            self.SelectItem(parentnodeid)
                            self._bindActivation()
                            return
                elif motionType == "child":
                    if not self.IsExpanded(currentNode) and \
                            self.pWiki.getConfig().getboolean("main",
                            "tree_auto_follow"):
                        # Expand node to find child
                        self.Expand(currentNode)

                    if self.IsExpanded(currentNode):
                        child = self.findChildTreeNodeByWikiWord(currentNode,
                                self.pWiki.getCurrentWikiWord())
                        if child:
                            self._unbindActivation()
                            self.SelectItem(child)
                            self._bindActivation()
                            return
#                         else:
#                             # TODO Better method if child doesn't even exist!
#                             # Move to child but child not found ->
#                             # subtree below currentNode might need
#                             # a refresh
#                             self.CollapseAndReset(currentNode)  # AndReset?
#                             self.Expand(currentNode)
# 
#                             child = self.findChildTreeNodeByWikiWord(currentNode,
#                                     self.pWiki.getCurrentWikiWord())
#                             if child:
#                                 self.SelectItem(child)
#                                 return

        if currentWikiWord is not None:
            # No cheap way to find current word in tree    
            if  self.pWiki.getConfig().getboolean("main", "tree_auto_follow") or \
                    miscevt.get("forceTreeSyncFromRoot", False):
                # Configuration or event says to use expensive way
                if not self.buildTreeForWord(self.pWiki.getCurrentWikiWord(),
                        selectNode=True):
                    self.Unselect()
            else:    
                # Can't find word -> remove selection
                self.Unselect()


    def onChangedPresenter(self, miscevt):
        self.onLoadingCurrentWikiPage(miscevt)


    def onWikiPageUpdated(self, miscevt):
        if not self.pWiki.getConfig().getboolean("main", "tree_update_after_save"):
            return

        self.refreshGenerator = self._generatorRefreshNodeAndChildren(
                self.GetRootItem())
        self.Bind(wx.EVT_IDLE, self.OnIdle)



    def onDeletedWikiPage(self, miscevt):  # TODO May be called multiple times if
                                           # multiple pages are deleted at once
        if not self.pWiki.getConfig().getboolean("main", "tree_update_after_save"):
            return

        self.refreshGenerator = self._generatorRefreshNodeAndChildren(
                self.GetRootItem())
        self.Bind(wx.EVT_IDLE, self.OnIdle)
        
    
    def _addExpandedNodesToPathSet(self, parentNodeId):
        """
        Called by onChangedWikiConfiguration (and by itself) if expanded nodes
        will now be recorded.
        The function does intentionally not record the (presumably) expanded 
        parent node as this parent node is the tree root which is assumed
        to be nearly always expanded.
        """
        nodeId, cookie = self.GetFirstChild(parentNodeId)
        while nodeId is not None and nodeId.IsOk():
            if self.IsExpanded(nodeId):
                node = self.GetPyData(nodeId)
                self.expandedNodePathes.add(tuple(node.getNodePath()))
                # Recursively handle childs of expanded node
                self._addExpandedNodesToPathSet(nodeId)
            nodeId, cookie = self.GetNextChild(parentNodeId, cookie)


    def onOptionsChanged(self, miscevt):
        config = self.pWiki.getConfig()

        coltuple = htmlColorToRgbTuple(config.get("main", "tree_bg_color"))   

        if coltuple is None:
            coltuple = (255, 255, 255)

        self.SetBackgroundColour(wx.Colour(*coltuple))
        
#         self.SetDefaultScrollVisiblePos("middle")

        self.Refresh()
        
        self.refreshGenerator = self._generatorRefreshNodeAndChildren(
                self.GetRootItem())
        self.Bind(wx.EVT_IDLE, self.OnIdle)



    def onChangedWikiConfiguration(self, miscevt):
        config = self.pWiki.getConfig()
        durat = config.getint(
                "main", "tree_expandedNodes_rememberDuration", 2)
        if durat == 0:
            # Don't remember nodes
            self.expandedNodePathes = None
        else:
            if self.expandedNodePathes is None:
                self.expandedNodePathes = StringPathSet()
                # Add curently expanded nodes to the set
                self._addExpandedNodesToPathSet(self.GetRootItem())

        if durat != 2:
            # Clear pathes stored in config
            config.set("main",
                    "tree_expandedNodes_descriptorPathes_" + self.treeType,
                    u"")

    def _generatorRefreshNodeAndChildren(self, parentnodeid):
        """
        This is some sort of user-space thread. It is executed inside
        the main thread as most things are GUI operations which must
        be done in GUI thread.
        Some non-GUI things are handed over to the refreshExecutor which
        runs them in a different thread.
        """
        try:        
            nodeObj = self.GetPyData(parentnodeid)
        except Exception:
            raise StopIteration

        wikiData = self.pWiki.getWikiData()


        retObj = self.refreshExecutor.executeAsync(0, nodeObj.getNodePresentation)
        while retObj.state == 0:  # Dangerous!
#             print "--_generatorRefreshNodeAndChildren13"
            yield None
#         print "--_generatorRefreshNodeAndChildren14"
        nodeStyle = retObj.getReturn() 
#         nodeStyle = nodeObj.getNodePresentation()

        self.setNodePresentation(parentnodeid, nodeStyle)

        if not nodeStyle.hasChildren and self.expandedNodePathes is not None:
            self.expandedNodePathes.discardStartsWith(
                    tuple(nodeObj.getNodePath()))

        if not self.IsExpanded(parentnodeid):
            raise StopIteration

#         if nodeObj.representsWikiWord():
#             retObj = self.refreshExecutor.executeAsync(
#                     0, wikiData.getUnAliasedWikiWord, nodeObj.getWikiWord())
#             while retObj.state == 0:  # Dangerous!
#                 yield None
#             wikiWord = retObj.getReturn() 

        if True:
            # We have to recreate the children of this node
            

            # This is time consuming
            retObj = self.refreshExecutor.executeAsync(0, nodeObj.listChildren)
            while retObj.state == 0:  # Dangerous!
#                 print "--_generatorRefreshNodeAndChildren34"
                yield None
            children = retObj.getReturn() 

#             # This is time consuming
#             children = nodeObj.listChildren()
            
            if self.expandedNodePathes is not None:
                # Pathes for all children
                childrenPathes = set(tuple(c.getNodePath()) for c in children)
            
            oldChildNodeIds = []
            nodeid, cookie = self.GetFirstChild(parentnodeid)
            while nodeid is not None and nodeid.IsOk():
                oldChildNodeIds.append(nodeid)
                nodeid, cookie = self.GetNextChild(parentnodeid, cookie)
            
            idIdx = 0
            
#             nodeid, cookie = self.GetFirstChild(parentnodeid)
            del nodeid
            
            tci = 0  # Tree child index
            for c in children:
                if idIdx < len(oldChildNodeIds):
                    nodeid = oldChildNodeIds[idIdx]
                    nodeObj = self.GetPyData(nodeid)
                    if c.nodeEquality(nodeObj):
                        # Previous child matches new child -> normal refreshing
                        if self.IsExpanded(nodeid):
                            # Recursive generator call
                            for sg in self._generatorRefreshNodeAndChildren(nodeid):
                                yield sg
                        else:
                            retObj = self.refreshExecutor.executeAsync(0,
                                    nodeObj.getNodePresentation)
                            while retObj.state == 0:  # Dangerous!
                                yield None
                            nodeStyle = retObj.getReturn()
#                             nodeStyle = nodeObj.getNodePresentation()

                            self.setNodePresentation(nodeid, nodeStyle)

                            if not nodeStyle.hasChildren and \
                                    self.expandedNodePathes is not None:
                                self.expandedNodePathes.discardStartsWith(
                                        tuple(nodeObj.getNodePath()))

                            yield None
                            
                        
                        idIdx += 1
                        tci += 1                           

                    else:
                        # Old and new don't match -> Insert new child
                        newnodeid = self.InsertItemBefore(parentnodeid, tci, "")
                        tci += 1
                        self.SetPyData(newnodeid, c)

                        retObj = self.refreshExecutor.executeAsync(0,
                                c.getNodePresentation)
                        while retObj.state == 0:  # Dangerous!
                            yield None
                        nodeStyle = retObj.getReturn()
                        self.setNodePresentation(newnodeid, nodeStyle)
#                         self.setNodePresentation(newnodeid,
#                                 c.getNodePresentation())

                        yield None

                else:
                    # No more nodes in tree, but some in new children list
                    # -> append one to tree
                    newnodeid = self.AppendItem(parentnodeid, "")
                    self.SetPyData(newnodeid, c)
                    
                    retObj = self.refreshExecutor.executeAsync(0,
                            c.getNodePresentation)
                    while retObj.state == 0:  # Dangerous!
                        yield None
                    nodeStyle = retObj.getReturn()
                    self.setNodePresentation(newnodeid, nodeStyle)
#                     self.setNodePresentation(newnodeid,
#                             c.getNodePresentation())


            # End of loop, no more new children, remove possible remaining
            # children in tree

            while idIdx < len(oldChildNodeIds):
                nodeid = oldChildNodeIds[idIdx]
                # Trying to prevent failure of GetNextChild() after deletion
                delnodeid = nodeid                
                idIdx += 1

                if self.expandedNodePathes is not None:
                    nodeObj = self.GetPyData(nodeid)
                    nodePath = tuple(nodeObj.getNodePath())
                    if nodePath not in childrenPathes:
                        self.expandedNodePathes.discardStartsWith(nodePath)

                self.Delete(delnodeid)
                yield None

        else:
            # Recreation of children not necessary -> simple refresh
            nodeid, cookie = self.GetFirstChild(parentnodeid)
            while nodeid is not None and nodeid.IsOk():
                if self.IsExpanded(nodeid):
                    # Recursive generator call
                    for sg in self._generatorRefreshNodeAndChildren(nodeid):
                        yield sg
                else:
                    nodeObj = self.GetPyData(nodeid)
                    retObj = self.refreshExecutor.executeAsync(0,
                            nodeObj.getNodePresentation)
                    while retObj.state == 0:  # Dangerous!
                        yield None
                    nodeStyle = retObj.getReturn()
                    self.setNodePresentation(nodeid, nodeStyle)
#                     self.setNodePresentation(nodeid, nodeObj.getNodePresentation())

                    yield None

                nodeid, cookie = self.GetNextChild(parentnodeid, cookie)
            
        raise StopIteration


    def onRenamedWikiPage(self, miscevt):
        rootItem = self.GetPyData(self.GetRootItem())
        if isinstance(rootItem, WikiWordNode) and \
                miscevt.get("wikiPage").getWikiWord() == \
                rootItem.getWikiWord():

            # Renamed word was root of the tree, so set it as root again
            self.pWiki.setWikiWordAsRoot(miscevt.get("newWord"))
            
            # Updating the tree isn't necessary then, so return
            return

        if not self.pWiki.getConfig().getboolean("main", "tree_update_after_save"):
            return

        self.refreshGenerator = self._generatorRefreshNodeAndChildren(
                self.GetRootItem())
        self.Bind(wx.EVT_IDLE, self.OnIdle)
#         self.collapse()   # TODO?


    def onClosingCurrentWiki(self, miscevt):
        config = self.pWiki.getConfig()

        durat = config.getint("main", "tree_expandedNodes_rememberDuration", 2)
        if durat == 2 and self.expandedNodePathes is not None:
            pathStrs = []
            for path in self.expandedNodePathes:
                pathStrs.append(u",".join(
                        [escapeForIni(item, u";,") for item in path]))
            
            remString = u";".join(pathStrs)

            config.set("main",
                    "tree_expandedNodes_descriptorPathes_" + self.treeType,
                    remString)
        else:
            config.set("main",
                    "tree_expandedNodes_descriptorPathes_" + self.treeType,
                    u"")

        self.refreshGenerator = None
        self.refreshExecutor.end(hardEnd=True)
        self.refreshExecutor.start()


    def onClosedCurrentWiki(self, miscevt):
#         self.refreshExecutor.end(hardEnd=True)
#         self.refreshGenerator = None
        self.Unbind(wx.EVT_IDLE)
        if self.expandedNodePathes is not None:
            self.expandedNodePathes = StringPathSet()

    def OnInsertIconAttribute(self, evt):
        self.pWiki.insertAttribute("icon", self.cmdIdToIconName[evt.GetId()],
                self.GetPyData(self.contextMenuNode).getWikiWord())

    def OnInsertColorAttribute(self, evt):
        self.pWiki.insertAttribute("color", self.cmdIdToColorName[evt.GetId()],
                self.GetPyData(self.contextMenuNode).getWikiWord())

#         self.activeEditor.AppendText(u"\n\n[%s=%s]" % (name, value))

    def OnAppendWikiWord(self, evt):
        toWikiWord = SelectWikiWordDialog.runModal(self.pWiki, self.pWiki, -1,
                title=_(u"Append Wiki Word"))

        if toWikiWord is not None:
            parentWord = self.GetPyData(self.contextMenuNode).getWikiWord()
            page = self.pWiki.getWikiDataManager().getWikiPageNoError(parentWord)
            
            langHelper = wx.GetApp().createWikiLanguageHelper(
                    page.getWikiLanguageName())

            page.appendLiveText(u"\n" +
                    langHelper.createStableLinksFromWikiWords((toWikiWord,)))


    def OnPrependWikiWord(self, evt):
        toWikiWord = SelectWikiWordDialog.runModal(self.pWiki, self.pWiki, -1,
                title=_(u"Prepend Wiki Word"))

        if toWikiWord is not None:
            parentWord = self.GetPyData(self.contextMenuNode).getWikiWord()
            page = self.pWiki.getWikiDataManager().getWikiPageNoError(parentWord)
            
            langHelper = wx.GetApp().createWikiLanguageHelper(
                    page.getWikiLanguageName())
                    
            text = page.getLiveText()
            page.replaceLiveText(
                    langHelper.createStableLinksFromWikiWords((toWikiWord,)) +
                    u"\n" + text)


    def OnActivateNewTabThis(self, evt):
        wikiWord = self.GetPyData(self.contextMenuNode).getWikiWord()
        presenter = self.pWiki.createNewDocPagePresenterTab()
        presenter.openWikiPage(wikiWord)
        presenter.getMainControl().getMainAreaPanel().\
                        showPresenter(presenter)
        self.selectedNodeWhileContext = self.contextMenuNode
        self.SelectItem(self.contextMenuNode)
        if self.pWiki.getConfig().getboolean("main", "tree_autohide", False):
            # Auto-hide tree
            self.pWiki.setShowTreeControl(False)


    def OnCmdClipboardCopyUrlToThisWikiWord(self, evt):
        wikiWord = self.GetPyData(self.contextMenuNode).getWikiWord()
        path = self.pWiki.getWikiDocument().getWikiConfigPath()
        copyTextToClipboard(pathWordAndAnchorToWikiUrl(path, wikiWord, None))


    def buildTreeForWord(self, wikiWord, selectNode=False, doexpand=False):
        """
        First tries to find a path from wikiWord to the currently selected node.
        If nothing is found, searches for a path from wikiWord to the root.
        Expands the tree out and returns True if a path is found 
        """
#         if selectNode:
#             doexpand = True

        wikiData = self.pWiki.getWikiData()
        currentNode = self.GetSelection()    # self.GetRootItem()
        
        crumbs = None

        if currentNode is not None and currentNode.IsOk() and \
                self.GetPyData(currentNode).representsFamilyWikiWord():
            # check for path from wikiWord to currently selected tree node            
            currentWikiWord = self.GetPyData(currentNode).getWikiWord() #self.getNodeValue(currentNode)
            crumbs = wikiData.findBestPathFromWordToWord(wikiWord, currentWikiWord)
            
            if crumbs and self.pWiki.getConfig().getboolean("main",
                    "tree_no_cycles"):
                ancestors = self.GetPyData(currentNode).getAncestors()
                # If an ancestor of the current node is in the crumbs, the
                # crumbs path is invalid because it contains a cycle
                for c in crumbs:
                    if c in ancestors:
                        crumbs = None
                        break
        
        # if a path is not found try to get a path to the root node
        if not crumbs:
            currentNode = self.GetRootItem()
            if currentNode is not None and currentNode.IsOk() and \
                    self.GetPyData(currentNode).representsFamilyWikiWord():
                currentWikiWord = self.GetPyData(currentNode).getWikiWord()
                crumbs = wikiData.findBestPathFromWordToWord(wikiWord,
                        currentWikiWord)


        if crumbs:
            numCrumbs = len(crumbs)

            # expand all of the parents
            for i in range(0, numCrumbs):
                # fill in the missing nodes for each parent. expand can actually
                # replace currentNode under special conditions, which would invalidate
                # the currentNode pointer
                try:
                    if doexpand:
                        self.Expand(currentNode)

                    # fetch the next crumb node
                    if (i+1) < numCrumbs:
                        self.Expand(currentNode)
                        currentNode = self.findChildTreeNodeByWikiWord(currentNode,
                                crumbs[i+1])
                except Exception, e:
                    sys.stderr.write("error expanding tree node: %s\n" % e)


            # set the ItemHasChildren marker if the node is not expanded
            if currentNode:
                currentWikiWord = self.GetPyData(currentNode).getWikiWord()

                # the only time this could be 0 really is if the expand above
                # invalidated the root pointer
                

            # TODO Check if necessary:
                
#                 if len(currentWikiWord) > 0:
#                     try:
#                         currentNodePage = wikiData.getPage(currentWikiWord, toload=[""])   # 'children', 
#                         self.updateTreeNode(currentNodePage, currentNode)
#                     except Exception, e:
#                         sys.stderr.write(str(e))

                if doexpand:
                    self.EnsureVisible(currentNode)
                if selectNode:
                    self._unbindActivation()
                    self.SelectItem(currentNode)
                    self._bindActivation()
                
                return True
        
        return False    

    def findChildTreeNodeByWikiWord(self, fromNode, findWord):
        (child, cookie) = self.GetFirstChild(fromNode)    # , 0
        while child:
            nodeobj = self.GetPyData(child)
#             if nodeobj.representsFamilyWikiWord() and nodeobj.getWikiWord() == findWord:
            if nodeobj.representsFamilyWikiWord() and \
                    self.pWiki.getWikiData().getUnAliasedWikiWord(nodeobj.getWikiWord())\
                    == findWord:
                return child
            
            (child, cookie) = self.GetNextChild(fromNode, cookie)
        return None


    def setRootByWord(self, rootword):
        self.setRootByUnifiedName(u"wikipage/" + rootword)


    def setViewsAsRoot(self):
        self.setRootByUnifiedName(u"helpernode/main/view")


    def setRootByUnifiedName(self, unifName):
        """
        Clear the tree and use a node described by unifName as root of the tree.
        """
        self.DeleteAllItems()
        # add the root node to the tree
        nodeobj = self.createNodeObjectByUnifiedName(unifName)
        nodeobj.setRoot(True)
        root = self.AddRoot(u"")
        self.SetPyData(root, nodeobj)
        self.setNodePresentation(root, nodeobj.getNodePresentation())
        if self.expandedNodePathes is not None:
            self.expandedNodePathes = StringPathSet()

        self.SelectItem(root)

        
    def createNodeObjectByUnifiedName(self, unifName):
        # TODO Support all node types
        if unifName.startswith(u"wikipage/"):
            return WikiWordNode(self, None, unifName[9:])
        elif unifName == u"helpernode/main/view":
            return MainViewNode(self, None)
        else:
            raise InternalError(
                    "createNodeObjectByUnifiedName called with invalid parameter")


    def readExpandedNodesFromConfig(self):
        """
        Called by PersonalWikiFrame during opening of a wiki.
        Checks first if nodes should be read from there.
        """
        config = self.pWiki.getConfig()
        
        durat = config.getint("main", "tree_expandedNodes_rememberDuration", 2)
        if durat == 0:
            # Don't remember nodes
            self.expandedNodePathes = None
        elif durat == 2:
            pathSet = StringPathSet()
            remString = config.get("main",
                    "tree_expandedNodes_descriptorPathes_" + self.treeType,
                    u"")
            
            # remString consists of node pathes delimited by ';'
            # the items of the paath are delimited by , and are
            # ini-escaped
            
            if not remString == u"":
                for pathStr in remString.split(u";"):
                    path = tuple(unescapeForIni(item)
                            for item in pathStr.split(u","))
                    pathSet.add(path)
                    
            self.expandedNodePathes = pathSet
        else:  # durat == 1
            # Remember only during session
            self.expandedNodePathes = StringPathSet()


    def setNodeImage(self, node, image):
        try:
            index = self.pWiki.lookupIconIndex(image)
            if index == -1:
                index = self.pWiki.lookupIconIndex(u"page")
            ## if icon:
                ## self.SetItemImage(node, index, wx.TreeItemIcon_Selected)
                ## self.SetItemImage(node, index, wx.TreeItemIcon_Expanded)
                ## self.SetItemImage(node, index, wx.TreeItemIcon_SelectedExpanded)
            self.SetItemImage(node, index, wx.TreeItemIcon_Normal)
        except:
            try:
                self.SetItemImage(node, 0, wx.TreeItemIcon_Normal)
            except:
                pass    
                
                    
    def setNodeColor(self, node, color):
        if color == "null":
            self.SetItemTextColour(node, wx.NullColour)
        else:
            self.SetItemTextColour(node, wx.NamedColour(color))


    def setNodePresentation(self, node, style):
        self.SetItemText(node, uniToGui(style.label), recalcSize=False)
        self.setNodeImage(node, style.icon)
        self.SetItemBold(node, strToBool(style.bold, False))
        self.setNodeColor(node, style.color)
        self.SetItemHasChildren(node, style.hasChildren)
        
    
    def _sendSelectionEvents(self, oldNode, newNode):
        # Simulate selection events
        event = customtreectrl.TreeEvent(wx.wxEVT_COMMAND_TREE_SEL_CHANGING,
                self.GetId())
        event.SetItem(newNode)
        event.SetOldItem(oldNode)
        event.SetEventObject(self)
        self.GetEventHandler().ProcessEvent(event)
        event.SetEventType(wx.wxEVT_COMMAND_TREE_SEL_CHANGED)
        self.GetEventHandler().ProcessEvent(event)

        
    def OnTreeItemActivated(self, event):
        item = event.GetItem()   
        if item is not None and item.IsOk():
            self.GetPyData(item).onActivate()
            if self.pWiki.getConfig().getboolean("main", "tree_autohide", False):
                # Auto-hide tree
                self.pWiki.setShowTreeControl(False)
        
        # Is said to fix a selection redraw problem
        self.Refresh()


    def OnTreeItemSelChanging(self, evt):
        pass


    def OnTreeBeginRDrag(self, evt):
        pass

    def OnTreeItemExpand(self, event):
        ## _prof.start()
        item = event.GetItem()
        if self.IsExpanded(item):   # TODO Check if a good idea
            return

        itemobj = self.GetPyData(item)
        if self.expandedNodePathes is not None:
            self.expandedNodePathes.add(tuple(itemobj.getNodePath()))

        childnodes = itemobj.listChildren()

        self.Freeze()
        try:
            for ch in childnodes:
                newit = self.AppendItem(item, u"")
                self.SetPyData(newit, ch)
                nodeStyle = ch.getNodePresentation()
                self.setNodePresentation(newit, nodeStyle)
                
                if self.expandedNodePathes is not None:
                    if nodeStyle.hasChildren:
                        if tuple(ch.getNodePath()) in self.expandedNodePathes:
                            self.Expand(newit)
#                     else:
#                         self.expandedNodePathes.discardStartsWith(
#                                 tuple(ch.getNodePath()))
        finally:
            self.Thaw()

        ## _prof.stop()


    def OnTreeItemCollapse(self, event):
        itemobj = self.GetPyData(event.GetItem())

        if self.expandedNodePathes is not None:
            self.expandedNodePathes.discard(tuple(itemobj.getNodePath()))
        self.DeleteChildren(event.GetItem())
        # Is said to fix a selection redraw problem
        self.Refresh()


    def OnTreeBeginDrag(self, event):
        langHelper = wx.GetApp().createWikiLanguageHelper(
                self.pWiki.getWikiDocument().getWikiDefaultWikiLanguage())

        itemobj = self.GetPyData(event.GetItem())
        if isinstance(itemobj, WikiWordNode):
            textDataOb = textToDataObject(
                    langHelper.createStableLinksFromWikiWords(
                    (itemobj.getWikiWord(),)))

            wikiWordDataOb = wx.DataObjectSimple(wx.CustomDataFormat(
                    "application/x-wikidpad-unifiedname"))
            wikiWordDataOb.SetData(
                    (u"wikipage/" + itemobj.getWikiWord()).encode("utf-8"))

            dataOb = wx.DataObjectComposite()
            dataOb.Add(textDataOb, True)
            dataOb.Add(wikiWordDataOb)

            dropsource = wx.DropSource(self)
            dropsource.SetData(dataOb)
            dropsource.DoDragDrop(wx.Drag_AllowMove)


#     def OnLeftDown(self, event):
# #         dataOb = textToDataObject(u"Test")
#         dataOb = wx.TextDataObject("Test")
#         dropsource = wx.DropSource(self)
#         dropsource.SetData(dataOb)
#         dropsource.DoDragDrop(wxDrag_AllowMove)



    def OnRightButtonDown(self, event):
        pass


    def OnRightButtonUp(self, event):
        selnode = self.GetSelection()
        
        clickPos = event.GetPosition()
        if clickPos == wx.DefaultPosition:
            # E.g. context menu key was pressed on Windows keyboard
            item = selnode
        else:
            item, flags = self.HitTest(clickPos)

        if item is None or not item.IsOk():
            return

        self.contextMenuNode = item

        menu = wx.Menu()
        menu = self.GetPyData(item).prepareContextMenu(menu)

        if menu is not None:
            self.selectedNodeWhileContext = selnode
            
            self._unbindActivation()
            self.SelectItem(item)
            self._bindActivation()

            self.PopupMenuXY(menu, event.GetX(), event.GetY())

            selnode = self.selectedNodeWhileContext

            self._unbindActivation()
            if selnode is None:
                self.Unselect()
            else:
                self.SelectItem(selnode, expand_if_necessary=False)
            self._bindActivation()

            newsel = self.GetSelection()
            if selnode != newsel:
                self._sendSelectionEvents(selnode, newsel)
        else:
            self.contextMenuNode = None


    def OnMiddleButtonDown(self, event):
        selnode = self.GetSelection()
        
        clickPos = event.GetPosition()
        if clickPos == wx.DefaultPosition:
            item = selnode
        else:
            item, flags = self.HitTest(clickPos)

        if item is None or not item.IsOk():
            return

        nodeObj = self.GetPyData(item)

        if event.ControlDown():
            configCode = self.pWiki.getConfig().getint("main",
                    "mouse_middleButton_withCtrl")
        else:
            configCode = self.pWiki.getConfig().getint("main",
                    "mouse_middleButton_withoutCtrl")
                    
        tabMode = MIDDLE_MOUSE_CONFIG_TO_TABMODE[configCode]

        if (tabMode & 2) and isinstance(nodeObj, WikiWordNode):
#             self.pWiki.activateWikiWord(nodeObj.getWikiWord(), tabMode)
            self.pWiki.activatePageByUnifiedName(
                    u"wikipage/" + nodeObj.getWikiWord(), tabMode)
            
            if not (tabMode & 1) and self.pWiki.getConfig().getboolean("main",
                    "tree_autohide", False):
                # Not opened in background -> auto-hide tree if option selected
                self.pWiki.setShowTreeControl(False)
        else:
            self.SelectItem(item)

#             # Create new tab
#             presenter = self.pWiki.createNewDocPagePresenterTab()
#             presenter.openWikiPage(nodeObj.getWikiWord())
#             if configCode == 0:
#                 # New tab in foreground
#                 presenter.getMainControl().getMainAreaPanel().\
#                                 showDocPagePresenter(presenter)
# 
#         elif configCode == 2:
#             self.SelectItem(item)



    def OnIdle(self, event):
        gen = self.refreshGenerator
        if gen is not None:
            try:
                gen.next()
            except StopIteration:
                if self.refreshGenerator == gen:
                    self.refreshGenerator = None
                    self.Unbind(wx.EVT_IDLE)


    def isVisibleEffect(self):
        """
        Is this control effectively visible?
        """
        return self.sizeVisible


    def handleVisibilityChange(self):
        """
        Only call after isVisibleEffect() really changed its value.
        The new value is taken from isVisibleEffect(), the old is assumed
        to be the opposite.
        """
        if not self.isVisibleEffect():
            if wx.Window.FindFocus() is self:
                self.pWiki.getMainAreaPanel().SetFocus()


    def OnSize(self, evt):
        evt.Skip()
        oldVisible = self.isVisibleEffect()
        size = evt.GetSize()
        self.sizeVisible = size.GetHeight() >= 5 and size.GetWidth() >= 5

        if oldVisible != self.isVisibleEffect():
            self.handleVisibilityChange()





# _CONTEXT_MENU_WIKIWORD = \
# u"""
# Activate New Tab;CMD_ACTIVATE_NEW_TAB_THIS
# Rename;CMD_RENAME_THIS_WIKIWORD
# Delete;CMD_DELETE_THIS_WIKIWORD
# Bookmark;CMD_BOOKMARK_THIS_WIKIWORD
# Set As Root;CMD_SETASROOT_THIS_WIKIWORD
# Append wiki word;CMD_APPEND_WIKIWORD_FOR_THIS
# Prepend wiki word;CMD_PREPEND_WIKIWORD_FOR_THIS
# Copy URL to clipboard;CMD_CLIPBOARD_COPY_URL_TO_THIS_WIKIWORD
# """
# 
# 
# # Entries to support i18n of context menus
# 
# N_(u"Activate New Tab")
# N_(u"Rename")
# N_(u"Delete")
# N_(u"Bookmark")
# N_(u"Set As Root")
# N_(u"Append wiki word")
# N_(u"Prepend wiki word")
# N_(u"Copy URL to clipboard")



