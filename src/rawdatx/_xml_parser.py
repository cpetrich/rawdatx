import xml.etree.ElementTree as _ET  # does the attribute decomposition

# This module is used ONLY as a fall-back if lxml is not installed.

# required functionality:
#   DTD().validate(tree)
#   tree=parse()
#   element=tree.getroot()
#   element.attrib[<attribute-name>]
#   element.tag
#   element.find('..') --> parent
#   element.findall('.//'+element_name) --> return list of elements with name

# Note:
#   lxml creates an object of each element once and
#     returns a reference as needed.
#   here, a new copy of a requested element object
#     is returned for each request.

class DTD(object):
    """Dummy DTD validator class: validation will always succeed."""
    def __init__(self, DTD_definition_string):
        self.DTD_definition_string = DTD_definition_string
    def validate(self, tree):
        return True


class _Tree(object):
    def __init__(self, elements, current_position):
        self._elements = elements # we don't mutate elements, don't copy
        self._pos = current_position[:]
        if self._pos[-1]!=0: self._pos.append(0) # pointing at the head
        self._current = self._get_current_element()

    def _get_current_element(self, pos=None):
        """Returns list we are currently pointing to."""
        sub=self._elements
        if pos is None: pos=self._pos
        for idx in pos:
            if idx==0: break # we're pointing at the head element
            sub=sub[idx]
        return sub
    
    def __eq__(self,other):
        return (self._elements == other._elements) and (self._pos == other._pos)
    def __neq__(self,other):
        return not self.__eq__(other)
    def __len__(self):
        # not used
        return len([child for child in self])    
    def __repr__(self):
        # we do not return id(self) since this doesn't help
        #   identifying if two instances point at the same element.        
        return '<Element %s at %s>' % (self.tag, repr(self._pos))
    
    def __getitem__(self, key):
        # not used
        """Parse attribute from string"""
        return self._current[0][1][key]

    def __getattr__(self, name):
        if name == 'tag':
            # return tag name
            return self._current[0][0]
        elif name == 'attrib':
            # return attribute information
            return self._current[0][1]
        raise AttributeError('Unknown attribute %s.' % name)
    def items(self): # used by tostring()
        return list(self._current[0][1].iteritems())
    
    def _get_tag(self, pos=None):
        if pos is None: pos = self._pos
        if pos[-1] != 0: pos+=[0,]
        return self._get_current_element(pos)[0][0] 
        
    def findall(self, path):
        if not path.startswith('.//'):
            raise NotImplemented('Search path %s is not implemented.' % path)
        tag = path[3:].lower()
        return [element for element in self.getiterator() if element.tag.lower() == tag]

    def find(self, path):
        if path!='..':
            raise NotImplemented('Search path %s is not implemented.' % path)
        if len(self._pos)<2: return None # we're at the root element
        return _Tree(self._elements, self._pos[:-2]+[0])

    def __iter__(self):        
        """Iterate over direct children of current level."""
        # Note: not used
        base = self._pos[:-1]        
        class _next_item(object):
            def __init__(s, base):
                s._base, s._last_item = base, [0]
            def next(s):                              
                s._last_item[-1]+=1                   
                if s._last_item[-1] >= len(self._current):
                    raise StopIteration
                return _Tree(self._elements, s._base+s._last_item)
            def __next__(s): # Python 3
                return s.next()
        return _next_item(base)
    
    def getchildren(self):
        """Return list of direct children"""
        # Note: not used
        return [child for child in self]
    
    def getiterator(self):
        """Return iterator that iterates over flattened list of self and all child elements"""
        base = self._pos[:-1]
        class _iterator(object):
            def __init__(s, base):
                s._base = base
                s._last_item = []
            def __iter__(s):
                s._last_item = []
                return s
            def next(s):                
                while len(s._last_item)>0:
                    s._last_item[-1]+=1                    
                    if s._last_item[-1] >= len(self._get_current_element(s._base+s._last_item[:-1])):
                        s._last_item = s._last_item[:-1]
                        if len(s._last_item) == 0: raise StopIteration
                        continue
                    break
                s._last_item+=[0,]
                return _Tree(self._elements, s._base+s._last_item)
            def __next__(s): # Python 3
                return s.next()
        
        return _iterator(base)
            
class parse(object):
    def __init__(self, filename=None):
        if filename is not None:
            with open(filename,'rt') as f:
                self._data = f.read()
            # get encoding information and convert rest
            #   to unicode string
            encoding, cont = self._get_encoding()            
            
            try: # Python 2
                # convert data to unicode string
                self._text=self._data[cont:].decode(encoding).strip()
            except AttributeError: # Python 3
                with open(filename,'rt',encoding=encoding) as f:
                    self._data = f.read()
                self._text=self._data[cont:].strip() 
            
            self._text_pointer=None            
            self._parse()
            self._current = [0]
    
    def _get_encoding(self):
        """Extract xml encoding from prolog"""
        start = self._data.lower().find('<?xml ')
            
        end = self._data.find('?>',start)
        enc='encoding='        
        idx=self._data.lower().find(enc,start,end)
        if idx != -1:
            # extract encoding string
            idx+=len(enc)
            sep=self._data[idx]
            idx+=1
            last=self._data.find(sep,idx,end)        
            encoding = self._data[idx:last]
        else:
            # assume XML default
            encoding = 'UTF-8'
        self._encoding = u'%s'%encoding
        return self._encoding, end+2
    
    def _find_next_open(self, start=0):
        """returns -1 if none"""
        return self._text.find('<',start)        
    def _find_next_element(self, start=None):
        start=start if start is not None else self._text_pointer if self._text_pointer is not None else 0
        while True:
            check=self._find_next_open(start)
            if self._text[check:check+4] == '<!--':
                # skip comment
                start = self._text.find('-->',check)
                continue
            break
        # element end
        end = self._text.find('>',check)
        
        # new element start?            
        closing = self._text[check+1:check+2]=='/'
        if closing: check += 1 # skip marker
        
        end_tag=self._text.find(' ',check,end)
        if end_tag == -1: end_tag = end        
        
        tag = self._text[check+1:end_tag]
        
        singular = self._text[end-1]=='/'            
            
        self._text_pointer = end+1
        attributes = self._text[end_tag+1:end-(1 if singular else 0)].strip() if not closing else u''
        return tag, attributes, closing, singular, end+1
                    
    def _parse(self):
        """Extract elements."""
        # We ignore comments and text between elements.
        self._elements=None
        self._text_pointer = 0
        levels=[[]]
        while self._text_pointer < len(self._text):
            
            tag, attrib, closing, singular, cont = self._find_next_element()
            type_name = ['opening','closing','singular'][int(closing)+int(singular)*2]
            
            # use 'xml' to generate attribute dictionary
            attrib = _ET.fromstring(('<d %s />' % attrib).encode('utf-8')).attrib

            if type_name in ('opening','singular'):
                levels.append([])
                levels[-1]+=((tag, attrib),)
            if type_name in ('closing','singular'):
                levels[-2].append(levels[-1])
                levels.pop()

        self._elements=levels[-1][-1]
                
    def getroot(self):
        return _Tree(self._elements, [0])
    
