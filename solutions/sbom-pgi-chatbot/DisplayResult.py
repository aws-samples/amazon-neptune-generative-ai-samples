"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

from enum import Enum
from typing import Any


class DisplayResult:
    class DisplayFormat(Enum):
        TABLE = "table"
        SUBGRAPH = "subgraph"
        STRING = "string"
        JSON = "json"
        NOTSPECIFIED = "notspecified"

    class Status(Enum):
        SUCCESS = "success"
        ERROR = "error"

    results = None
    explanation = None

    def __init__(
        self,
        results: Any,
        explanation: Any = None,
        display_format: DisplayFormat = DisplayFormat.NOTSPECIFIED,
        status: Status = Status.SUCCESS,
    ):
        self.results = results
        self.explanation = explanation
        self.display_format = display_format
        self.status = status
