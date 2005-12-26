## -*- coding: ISO-8859-1 -*-

"""
Various string operations, like unicode encoding/decoding,
creating diff information for plain byte sequences
"""



import threading

from struct import pack, unpack

import difflib, codecs
from codecs import BOM_UTF8, BOM_UTF16_BE, BOM_UTF16_LE
from os.path import splitext
from Utilities import DUMBTHREADHOLDER

import srePersistent as re

LINEEND_SPLIT_RE = re.compile(r"\r\n?|\n")


from Configuration import isUnicode, isOSX


# To generate dependencies for py2exe
import encodings.utf_8, encodings.latin_1



# ---------- Encoding conversion ----------


utf8Enc = codecs.getencoder("utf-8")
utf8Dec = codecs.getdecoder("utf-8")
utf8Reader = codecs.getreader("utf-8")
utf8Writer = codecs.getwriter("utf-8")

def convertLineEndings(text, newLe):
    """
    Convert line endings of text to string newLe which should be
    "\n", "\r" or "\r\n". If newLe or text is unicode, the result
    will be unicode, too.
    """
    return newLe.join(LINEEND_SPLIT_RE.split(text))

def lineendToInternal(text):
    return convertLineEndings(text, "\n")
    


if isOSX():      # TODO Linux
    # generate dependencies for py2app
    import encodings.mac_roman
    mbcsEnc = codecs.getencoder("mac_roman")
    mbcsDec = codecs.getdecoder("mac_roman")
    mbcsReader = codecs.getreader("mac_roman")
    mbcsWriter = codecs.getwriter("mac_roman")
    
    def lineendToOs(text):
        return convertLineEndings(text, "\r")
   
else:
    # generate dependencies for py2exe
    import encodings.mbcs
    mbcsEnc = codecs.getencoder("mbcs")
    mbcsDec = codecs.getdecoder("mbcs")
    mbcsReader = codecs.getreader("mbcs")
    mbcsWriter = codecs.getwriter("mbcs")

    # TODO This is suitable for Windows only
    def lineendToOs(text):
        return convertLineEndings(text, "\r\n")


if isUnicode():
    def uniToGui(text):
        """
        Convert unicode text to a format usable for wx GUI
        """
        return text   # Nothing to do
        
    def guiToUni(text):
        """
        Convert wx GUI string format to unicode
        """
        return text   # Nothing to do
else:
    def uniToGui(text):
        """
        Convert unicode text to a format usable for wx GUI
        """
        return mbcsEnc(text, "replace")[0]
        
    def guiToUni(text):
        """
        Convert unicode text to a format usable for wx GUI
        """
        return mbcsDec(text, "replace")[0]


def unicodeToCompFilename(us):
    """
    Encode a unicode filename to a filename compatible to (hopefully)
    any filesystem encoding by converting unicode to '=xx' for
    characters up to 255 and '$xxxx' above. Each 'x represents a hex
    character
    """
    result = []
    for c in us:
        if ord(c) > 255:
            result.append("$%04x" % ord(c))
            continue
        if c in u"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"+\
                u"{}[]()+-*_,.%":   # Allowed characters
            result.append(str(c))
            continue
        
        result.append("=%02x" % ord(c))
        
    return "".join(result)


def strToBool(s, default=False):
    """
    Try to interpret string (or unicode) s as
    boolean, return default if string can't be
    interpreted
    """
    
    if s is None:
        return default
    
    # Try to interpret as integer
    try:
        return int(s) != 0
    except ValueError:
        # Not an integer
        s = s.lower()
        if s in (u"true", u"yes"):
            return True
        if s in (u"false", u"no"):
            return False
            
        return default


# TODO More formats
def fileContentToUnicode(content):
    """
    Try to detect the text encoding of content
    and return converted unicode
    """
    if content.startswith(BOM_UTF8):
        return utf8Dec(content[len(BOM_UTF8):], "replace")[0]
    else:
        return mbcsDec(content, "replace")[0]
        
        
def wikiWordToLabel(word):
    """
    Strip '[' and ']' if non camelcase word and return it
    """
    if word.startswith(u"[") and word.endswith(u"]"):
        return word[1:-1]
    return word


def removeBracketsFilename(fn):
    n, ext = splitext(fn)
    return wikiWordToLabel(n) + ext


def revStr(s):
    """
    Return reversed string
    """
    s = list(s)
    s.reverse()
    return u"".join(s)
    
def splitkeep(s, delim):
    """
    Similar to split, but keeps the delimiter as separate element, e.g.
    splitkeep("aaabaaabaa", "b") -> ["aaa", "b", "aaa", "b", "aa"]
    """
    result = []
    for e in s.split(delim):
        result.append(e)
        result.append(delim)
        
    return result[:-1]

## Copied from xml.sax.saxutils and modified to reduce dependencies
def escapeHtml(data):
    """
    Escape &, <, and > in a unicode string of data.
    """

    # must do ampersand first

#     data = data.replace(u"&", u"&amp;")
#     data = data.replace(u">", u"&gt;")
#     data = data.replace(u"<", u"&lt;")
#     data = data.replace(u"\n", u"<br />")   # ?
#     return data
    return data.replace(u"&", u"&amp;").replace(u">", u"&gt;").\
            replace(u"<", u"&lt;").replace(u"\n", u"<br />")


# ---------- Support for serializing values into binary data (and back) ----------
# Especially used in SearchAndReplace.py, class SearchReplaceOperation

def boolToChar(b):
    if b:
        return "1"
    else:
        return "\0"
        
def charToBool(c):
    return c != "\0"


def strToBin(s):
    """
    s -- String to convert to binary (NOT unicode!)
    """
    return pack(">I", len(s)) + s   # Why big-endian? Why not?
    
def binToStr(b):
    """
    Returns tuple (s, br) with string s and rest of the binary data br
    """
    l = unpack(">I", b[:4])[0]
    s = b[4 : 4+l]
    br = b[4+l : ]
    return (s, br)




# ---------- Breaking text into tokens ----------

class Token(object):
    __slots__ = ("__weakref__", "ttype", "start", "grpdict", "text", "node")
    
    def __init__(self, ttype, start, grpdict, text, node=None):
        self.ttype = ttype
        self.start = start
        self.grpdict = grpdict
        self.text = text
        self.node = node
        
    def __repr__(self):
        return u"Token(%s, %s, %s, <dict>, %s)" % (repr(self.ttype), repr(self.start), repr(self.text), repr(self.node))


class Tokenizer:
    def __init__(self, tokenre, defaultType):
        self.tokenre = tokenre
        self.defaultType = defaultType
        self.tokenThread = None

    def setTokenThread(self, tt):
        self.tokenThread = tt

    def getTokenThread(self):
        return self.tokenThread

#     def tokenize(self, text, sync=True):
#         textlen = len(text)
#         result = []
#         charpos = 0    
#         
#         while True:
#             mat = self.tokenre.search(text, charpos)
#             if mat is None:
#                 if charpos < textlen:
#                     result.append((charpos, self.defaultType, None))
#                 
#                 result.append((textlen, self.defaultType, None))
#                 break
#     
#             groupdict = mat.groupdict()
#             for m in groupdict.keys():
#                 if not groupdict[m] is None and m.startswith(u"style"):
#                     start, end = mat.span()
#                     
#                     # m is of the form:   style<index>
#                     index = int(m[5:])
#                     if charpos < start:
#                         result.append((charpos, self.defaultType, None))                    
#                         charpos = start
#     
#                     result.append((charpos, index, groupdict))
#                     charpos = end
#                     break
#     
#             if not sync and (not threading.currentThread() is self.tokenThread):
#                 break
#                 
#         return result


    def tokenize(self, text, formatMap, defaultType, threadholder=DUMBTHREADHOLDER):
        textlen = len(text)
        result = []
        charpos = 0    
        
        while True:
            mat = self.tokenre.search(text, charpos)
            if mat is None:
                if charpos < textlen:
                    result.append(Token(defaultType, charpos, None,
                            text[charpos:textlen]))
                
                result.append(Token(defaultType, textlen, None, u""))
                break
    
            groupdict = mat.groupdict()
            for m in groupdict.keys():
                if not groupdict[m] is None and m.startswith(u"style"):
                    start, end = mat.span()
                    
                    # m is of the form:   style<index>
                    index = int(m[5:])
                    if charpos < start:
                        result.append(Token(defaultType, charpos, None,
                                text[charpos:start]))                    
                        charpos = start
    
                    result.append(Token(formatMap[index], charpos, groupdict,
                            text[start:end]))
                    charpos = end
                    break
    
            if not threadholder.isCurrent():
                break

        return result



# ---------- Handling diff information ----------


def difflibToCompact(ops, b):
    """
    Rewrite sequence of op_codes returned by difflib.SequenceMatcher.get_opcodes
    to the compact opcode format.

    0: replace,  1: delete,  2: insert

    b -- second string to match
    """
    result = []
    # ops.reverse()
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            continue
        elif tag == "replace":
            result.append((0, i1, i2, b[j1:j2]))
        elif tag == "delete":
            result.append((1, i1, i2))
        elif tag == "insert":
            result.append((2, i1, b[j1:j2]))

    return result


def compactToBinCompact(cops):
    """
    Compress the ops to a compact binary format to store in the database
    as blob
    """
    result = []
    for op in cops:
        if op[0] == 0:
            result.append( pack("<Biii", 0, op[1], op[2], len(op[3])) )
            result.append(op[3])
        elif op[0] == 1:
            result.append( pack("<Bii", *op) )
        elif op[0] == 2:
            result.append( pack("<Bii", 2, op[1], len(op[2])) )
            result.append(op[2])

    return "".join(result)



def binCompactToCompact(bops):
    """
    Uncompress the ops from the binary format
    """
    pos = 0
    result = []
    while pos < len(bops):
        t = ord(bops[pos])
        pos += 1
        if t == 0:
            d = unpack("<iii", bops[pos:pos+12])
            pos += 12
            s = bops[pos:pos+d[2]]
            pos += d[2]
            
            result.append( (0, d[0], d[1], s) )
        elif t == 1:
            d = unpack("<ii", bops[pos:pos+8])
            pos += 8
            
            result.append( (1, d[0], d[1]) )
        elif t == 2:
            d = unpack("<ii", bops[pos:pos+8])
            pos += 8
            s = bops[pos:pos+d[1]]
            pos += d[1]
            
            result.append( (2, d[0], s) )

    return result            


def applyCompact(a, cops):
    """
    Apply compact ops to string a to create and return string b
    """
    result = []
    apos = 0
    for op in cops:
        if apos < op[1]:
            result.append(a[apos:op[1]])  # equal

        if op[0] == 0:
            result.append(op[3])
            apos = op[2]
        elif op[0] == 1:
            apos = op[2]
        elif op[0] == 2:
            result.append(op[2])
            apos = op[1]

    if apos < len(a):
        result.append(a[apos:])  # equal

    return "".join(result)


def applyBinCompact(a, bops):
    """
    Apply binary diff operations bops to a to create b
    """
    return applyCompact(a, binCompactToCompact(bops))


def getBinCompactForDiff(a, b):
    """
    Return the binary compact codes to change string a to b.
    For strings a and b (NOT unicode) it is true that
        applyBinCompact(a, getBinCompactForDiff(a, b)) == b
    """

    sm = difflib.SequenceMatcher(None, a, b)
    ops = sm.get_opcodes()
    return compactToBinCompact(difflibToCompact(ops, b))

