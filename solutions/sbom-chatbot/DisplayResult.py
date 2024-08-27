from enum import Enum
from typing import Any

class DisplayResult:
    class DisplayFormat(Enum):
        TABLE = 'table'
        SUBGRAPH = 'subgraph'
        STRING = 'string'
        NOTSPECIFIED = 'notspecified'
    
    results = None
    explaination = None
    
    def __init__(self, results:Any, explaination:Any = None, display_format:DisplayFormat = DisplayFormat.NOTSPECIFIED):
        self.results = results
        self.explaination = explaination
        self.display_format = display_format
    
